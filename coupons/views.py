from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from core.security import RoleRequiredMixin

from .forms import CouponAdminForm
from .models import Coupon


class CouponAdminListView(RoleRequiredMixin, ListView):
    model = Coupon
    template_name = "coupons/admin_coupon_list.html"
    context_object_name = "coupons"
    allowed_roles = ("staff", "admin")
    paginate_by = 30


class CouponCreateView(RoleRequiredMixin, CreateView):
    model = Coupon
    form_class = CouponAdminForm
    template_name = "coupons/coupon_form.html"
    allowed_roles = ("staff", "admin")
    success_url = reverse_lazy("coupons:admin-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Coupon {self.object.code} created successfully.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = "Create Coupon"
        context["submit_label"] = "Create Coupon"
        return context
