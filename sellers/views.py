from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView

from cart.services import CartService
from core.security import RoleRequiredMixin
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .forms import SellerStoreForm
from .models import SellerStore
from .services import SellerStoreService


def _is_staff_or_admin(user) -> bool:
    return (
        user.is_staff
        or user.is_superuser
        or (hasattr(user, "has_any_role") and user.has_any_role("staff", "admin"))
    )


# ---------------------------------------------------------------------------
# Public store
# ---------------------------------------------------------------------------

class PublicSellerStoreView(DetailView):
    """No login required.  Sets secure session-based attribution when visited."""

    model = SellerStore
    template_name = "sellers/public_store.html"
    context_object_name = "store"

    def get_queryset(self):
        return SellerStore.objects.filter(is_active=True).select_related(
            "seller", "team", "campaign"
        )

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        store = self.object
        # Set attribution server-side — spoof-proof
        CartService.set_seller_store_attribution(request=request, store=store)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.object
        products = SellerStoreService.public_store_products(store)
        metrics = SellerStoreService.dashboard_metrics(store=store)
        context["products"] = products
        context["goal_progress_percent"] = metrics["goal_progress_percent"]
        context["total_sales_cents"] = metrics["total_sales_cents"]
        context["total_orders"] = metrics["total_orders"]
        context["share_link"] = metrics["share_link"]
        context["qr_data_uri"] = metrics["qr_data_uri"]
        return context


# ---------------------------------------------------------------------------
# Seller: create / edit own store
# ---------------------------------------------------------------------------

@login_required
def seller_store_edit_view(request, slug=None):
    """
    Create a new store (slug=None) or edit an existing one.
    Sellers can only edit stores they own; staff can edit any.
    """
    if slug:
        store = get_object_or_404(SellerStore, slug=slug)
        if store.seller_id != request.user.pk and not _is_staff_or_admin(request.user):
            raise PermissionDenied("You can only edit your own seller store.")
        is_new = False
    else:
        store = None
        is_new = True

    if request.method == "POST":
        form = SellerStoreForm(request.POST, request.FILES, instance=store, user=request.user)
        if form.is_valid():
            created_store = SellerStoreService.create_or_update_store(user=request.user, form=form)
            log_audit_event(
                action=AuditAction.UPDATE if not is_new else AuditAction.CREATE,
                message=f"Seller store {'created' if is_new else 'updated'}: {created_store.slug}",
                actor=request.user,
                request=request,
                target=created_store,
            )
            messages.success(request, "Your store has been saved.")
            return redirect("sellers:dashboard", slug=created_store.slug)
    else:
        form = SellerStoreForm(instance=store, user=request.user)

    return render(request, "sellers/store_form.html", {"form": form, "store": store, "is_new": is_new})


# ---------------------------------------------------------------------------
# Seller dashboard
# ---------------------------------------------------------------------------

@login_required
def seller_dashboard_view(request, slug: str):
    store = get_object_or_404(SellerStore, slug=slug)
    # Sellers see only their own; staff can see any
    if store.seller_id != request.user.pk and not _is_staff_or_admin(request.user):
        raise PermissionDenied("You can only view your own seller dashboard.")

    metrics = SellerStoreService.dashboard_metrics(store=store)
    return render(request, "sellers/seller_dashboard.html", {
        "store": store,
        **metrics,
    })


# ---------------------------------------------------------------------------
# Seller: my stores list
# ---------------------------------------------------------------------------

@login_required
def my_stores_view(request):
    stores = SellerStore.objects.filter(seller=request.user).select_related("team", "campaign")
    return render(request, "sellers/my_stores.html", {"stores": stores})


# ---------------------------------------------------------------------------
# Staff: manage all stores
# ---------------------------------------------------------------------------

class StaffSellerStoreListView(RoleRequiredMixin, ListView):
    model = SellerStore
    template_name = "sellers/staff_store_list.html"
    context_object_name = "stores"
    allowed_roles = ("staff", "admin")
    paginate_by = 50

    def get_queryset(self):
        return SellerStore.objects.select_related("seller", "team", "campaign").order_by("-created_at")
