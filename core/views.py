import json

from django.db import connection
from django.utils.html import json_script
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.views.generic import CreateView, ListView, TemplateView, UpdateView
from django.views import View
from django.contrib import messages
from django.urls import reverse
from core.security import RoleRequiredMixin

from .forms import ContactForm, SiteContentBlockForm
from .models import SiteContentBlock

from products.models import Product


MANAGED_PAGE_PREVIEW_ROUTE_NAMES = {
    "home": "home",
    "about": "about",
    "fundraising": "fundraising-landing",
    "corporate_gifts": "corporate-gifts",
    "contact": "contact",
    "faq": "faq",
}

MANAGED_PAGE_LABELS = {
    "home": "Home",
    "about": "About",
    "fundraising": "Fundraising",
    "corporate_gifts": "Corporate Gifts",
    "contact": "Contact",
    "faq": "FAQ",
}

HERO_SECTION_LABEL = "① Hero — Page banner & headline"
CTA_SECTION_LABEL = "④ CTA — Call-to-action strip"

MANAGED_PAGE_SECTIONS = {
    "home": [
        ("hero",         "① Hero — Top banner & headline"),
        ("featured",     "② Featured Products — Below the hero"),
        ("testimonials", "③ Testimonials — Social proof section"),
        ("promo-banner", "④ Promo Banner — Promotional callout"),
        ("cta",          "⑤ CTA — Call-to-action strip"),
    ],
    "about": [
        ("hero",   HERO_SECTION_LABEL),
        ("story",  "② Our Story — Company history"),
        ("values", "③ Values / Team — Middle section"),
        ("cta",    CTA_SECTION_LABEL),
    ],
    "fundraising": [
        ("hero",          HERO_SECTION_LABEL),
        ("how-it-works",  "② How It Works — Step-by-step"),
        ("benefits",      "③ Benefits — Why choose us"),
        ("cta",           CTA_SECTION_LABEL),
    ],
    "corporate_gifts": [
        ("hero",          HERO_SECTION_LABEL),
        ("intro",         "② Intro — Overview section"),
        ("custom-orders", "③ Custom Orders — Ordering info"),
        ("cta",           CTA_SECTION_LABEL),
    ],
    "contact": [
        ("hero",         "① Hero — Page banner"),
        ("contact-info", "② Contact Info — Phone, email, address"),
        ("hours",        "③ Hours — Business hours block"),
    ],
    "faq": [
        ("intro", "① Intro — Page intro text"),
        ("faq",   "② FAQ — Question & answer blocks"),
    ],
}

MANAGED_SECTION_LABELS = {
    "hero": "Top hero/banner area",
    "intro": "Intro text area",
    "testimonial": "Testimonials area",
    "promo-banner": "Promotional banner area",
    "cta": "Call-to-action button area",
    "faq": "FAQ answer block",
    "contact": "Contact details block",
}


class HomeView(TemplateView):
	template_name = "base/home.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context["featured_products"] = Product.objects.public_store().filter(is_featured=True).prefetch_related("skus")[:6]
		return context


class FundraisingLandingView(TemplateView):
	template_name = "core/fundraising_landing.html"


class StartFundraiserView(TemplateView):
	template_name = "core/start_fundraiser.html"

	def get(self, request, *args, **kwargs):
		if request.user.is_authenticated:
			return redirect("fundraisers:signup")
		return render(
			request,
			self.template_name,
			{"next_url": request.GET.get("next") or "/fundraisers/start/"},
		)


class CorporateGiftsView(TemplateView):
	template_name = "core/corporate_gifts.html"


class AboutView(TemplateView):
	template_name = "core/about.html"



class ContactView(View):
	template_name = "core/contact.html"

	def get(self, request):
		form = ContactForm()
		return render(request, self.template_name, {"form": form})

	def post(self, request):
		form = ContactForm(request.POST)
		if form.is_valid():
			name = form.cleaned_data["name"]
			email = form.cleaned_data["email"]
			message = form.cleaned_data["message"]
			print(f"Contact form submitted by {name} <{email}>: {message}")
			messages.success(request, "Thank you for reaching out! We'll get back to you soon.")
			return redirect("core:contact")
		return render(request, self.template_name, {"form": form})


class FAQView(TemplateView):
	template_name = "core/faq.html"


class SiteContentListView(RoleRequiredMixin, ListView):
    template_name = "staff/site_content_list.html"
    model = SiteContentBlock
    context_object_name = "blocks"
    allowed_roles = ("staff", "admin")

    def get_queryset(self):
        qs = SiteContentBlock.objects.select_related("updated_by")
        page_key = (self.request.GET.get("page_key") or "").strip()
        if page_key:
            qs = qs.filter(page_key=page_key)
        return qs


class SiteContentCreateView(RoleRequiredMixin, CreateView):
    template_name = "staff/site_content_form.html"
    model = SiteContentBlock
    form_class = SiteContentBlockForm
    allowed_roles = ("staff", "admin")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_page_key = (
            self.request.GET.get("page_key")
            or self.request.POST.get("page_key")
            or getattr(context.get("form"), "initial", {}).get("page_key")
            or "home"
        )
        return _add_site_config_preview_context(context, selected_page_key)

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.updated_by = self.request.user
        obj.save()
        messages.success(self.request, "Content block created.")
        return redirect("site-config-list")


class SiteContentUpdateView(RoleRequiredMixin, UpdateView):
    template_name = "staff/site_content_form.html"
    model = SiteContentBlock
    form_class = SiteContentBlockForm
    allowed_roles = ("staff", "admin")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_page_key = (
            self.request.POST.get("page_key")
            or getattr(self.object, "page_key", None)
            or "home"
        )
        return _add_site_config_preview_context(context, selected_page_key)

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.updated_by = self.request.user
        obj.save()
        messages.success(self.request, "Content block updated.")
        return redirect("site-config-list")


class SiteContentDeleteView(RoleRequiredMixin, View):
    allowed_roles = ("staff", "admin")

    def post(self, request, pk: int):
        block = get_object_or_404(SiteContentBlock, pk=pk)
        block.delete()
        messages.success(request, "Content block deleted.")
        return redirect("site-config-list")


def health_check(_request):
    """Liveness + readiness probe used by load balancers and Render health checks."""
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    status = 200 if db_ok else 503
    return JsonResponse({"status": "ok" if db_ok else "error", "db": db_ok}, status=status)


def _add_site_config_preview_context(context: dict, selected_page_key: str):
    page_preview_urls = {key: reverse(route_name) for key, route_name in MANAGED_PAGE_PREVIEW_ROUTE_NAMES.items()}
    page_sections_map = {key: [] for key in MANAGED_PAGE_PREVIEW_ROUTE_NAMES.keys()}

    blocks = SiteContentBlock.objects.all().order_by("page_key", "sort_order", "id")
    for block in blocks:
        label = MANAGED_SECTION_LABELS.get(block.section_key, "Custom editable section")
        page_sections_map.setdefault(block.page_key, []).append(
            {
                "key": block.section_key,
                "label": label,
                "title": block.title or "",
                "active": block.is_active,
            }
        )

    context["selected_page_key"] = selected_page_key
    context["page_preview_urls"] = page_preview_urls
    context["page_preview_urls_script"] = json_script(page_preview_urls, "page-preview-urls")
    context["page_sections_map"] = page_sections_map
    context["page_sections_map_script"] = json_script(page_sections_map, "page-sections-map")
    context["managed_pages"] = [(key, MANAGED_PAGE_LABELS.get(key, key)) for key in MANAGED_PAGE_PREVIEW_ROUTE_NAMES]
    context["page_sections_script"] = json_script(
        {key: [{"key": k, "label": l} for k, l in sections] for key, sections in MANAGED_PAGE_SECTIONS.items()},
        "page-sections-options",
    )
    return context
