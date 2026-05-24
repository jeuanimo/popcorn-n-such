from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView

from core.security import RoleRequiredMixin

from .forms import FundraiserCampaignApprovalForm, FundraiserCampaignRequestForm, FundraiserRequestReviewForm, FundraiserSignupForm
from .models import FundraiserCampaign, FundraiserCampaignStatus, FundraiserRequest
from .services import FundraiserCampaignService


class PublicFundraiserCampaignListView(ListView):
	model = FundraiserCampaign
	template_name = "fundraisers/public_campaign_list.html"
	context_object_name = "campaigns"

	def get_queryset(self):
		return FundraiserCampaign.objects.filter(status=FundraiserCampaignStatus.ACTIVE, is_active=True)


class PublicFundraiserCampaignDetailView(DetailView):
	model = FundraiserCampaign
	template_name = "fundraisers/public_campaign_detail.html"
	slug_field = "slug"
	slug_url_kwarg = "slug"

	def get_queryset(self):
		return FundraiserCampaign.objects.filter(is_active=True).prefetch_related("teams", "sellers")

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(FundraiserCampaignService.campaign_progress_context(campaign=self.object))
		return context


class OrganizationManagerCampaignListView(RoleRequiredMixin, LoginRequiredMixin, ListView):
	model = FundraiserCampaign
	template_name = "fundraisers/campaign_list.html"
	allowed_roles = ("organization_manager",)

	def get_queryset(self):
		return FundraiserCampaign.objects.filter(organization__manager=self.request.user).select_related("organization")


@login_required
def campaign_create_view(request):
	if not request.user.has_any_role("organization_manager"):
		raise PermissionDenied("Only organization managers can create fundraiser campaigns.")

	if request.method == "POST":
		form = FundraiserCampaignRequestForm(request.POST, request.FILES, user=request.user)
		if form.is_valid():
			FundraiserCampaignService.request_campaign(manager=request.user, form=form)
			messages.success(request, "Fundraiser campaign request submitted.")
			return redirect("fundraisers:manager-campaigns")
	else:
		form = FundraiserCampaignRequestForm(user=request.user)

	return render(request, "fundraisers/campaign_form.html", {"form": form})


class StaffCampaignQueueView(RoleRequiredMixin, LoginRequiredMixin, ListView):
	model = FundraiserCampaign
	template_name = "fundraisers/staff_campaign_queue.html"
	allowed_roles = ("staff", "admin")

	def get_queryset(self):
		return FundraiserCampaign.objects.select_related("organization").order_by("-created_at")[:200]

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		monitor_rows = []
		for campaign in context["object_list"]:
			issues = FundraiserCampaignService.post_publish_check_issues(campaign=campaign)
			monitor_rows.append({"campaign": campaign, "issues": issues})
		context["monitor_rows"] = monitor_rows
		return context


@login_required
def staff_approve_campaign_view(request, slug: str):
	if not (request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin")):
		raise PermissionDenied("Only staff can approve campaigns.")

	campaign = get_object_or_404(FundraiserCampaign, slug=slug)
	if request.method == "POST":
		form = FundraiserCampaignApprovalForm(request.POST, instance=campaign)
		if form.is_valid():
			FundraiserCampaignService.approve_campaign(campaign=campaign, approver=request.user, form=form)
			messages.success(request, "Campaign approval updated.")
			return redirect("fundraisers:staff-campaign-queue")
	else:
		form = FundraiserCampaignApprovalForm(instance=campaign)

	return render(request, "fundraisers/staff_campaign_approve.html", {"form": form, "campaign": campaign})


@login_required
def staff_toggle_campaign_live_view(request, slug: str):
	if not (request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin")):
		raise PermissionDenied("Only staff can change campaign live status.")
	if request.method != "POST":
		return redirect("fundraisers:staff-campaign-queue")

	campaign = get_object_or_404(FundraiserCampaign, slug=slug)
	action = (request.POST.get("action") or "").strip()
	if action == "kill":
		campaign.is_active = False
		campaign.save(update_fields=["is_active", "updated_at"])
		messages.warning(request, f"Campaign '{campaign.campaign_name}' was paused.")
	elif action == "restore":
		campaign.is_active = True
		if campaign.status in [FundraiserCampaignStatus.DRAFT, FundraiserCampaignStatus.SCHEDULED]:
			campaign.status = FundraiserCampaignStatus.ACTIVE
		campaign.save(update_fields=["is_active", "status", "updated_at"])
		messages.success(request, f"Campaign '{campaign.campaign_name}' was reactivated.")
	return redirect("fundraisers:staff-campaign-queue")


@login_required
def fundraiser_signup_view(request):
	"""Logged-in users provision their own fundraiser campaign."""
	if request.method == "POST":
		form = FundraiserSignupForm(request.POST)
		if form.is_valid():
			FundraiserCampaignService.signup_and_provision(
				form=form, request=request, user=request.user
			)
			return redirect("fundraisers:signup-thanks")
	else:
		u = request.user
		form = FundraiserSignupForm(initial={
			"contact_first_name": u.first_name,
			"contact_last_name": u.last_name,
			"contact_email": u.email,
		})
	return render(request, "fundraisers/signup.html", {"form": form})


def fundraiser_signup_thanks_view(request):
	return render(request, "fundraisers/signup_thanks.html")


class StaffFundraiserRequestQueueView(RoleRequiredMixin, LoginRequiredMixin, ListView):
	"""Staff queue for pending fundraiser requests (pre-campaign)."""
	template_name = "fundraisers/staff_request_queue.html"
	context_object_name = "requests"
	allowed_roles = ("staff", "admin")

	def get_queryset(self):
		return FundraiserRequest.objects.filter(status="pending").order_by("-created_at")


@login_required
def staff_provision_campaign_view(request, pk: int):
	"""Staff reviews a FundraiserRequest and provisions the full campaign stack."""
	if not (request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin")):
		raise PermissionDenied("Only staff can provision campaigns.")

	fr = get_object_or_404(FundraiserRequest, pk=pk)
	review_form = FundraiserRequestReviewForm(instance=fr)

	if request.method == "POST":
		action = request.POST.get("action")
		if action == "provision":
			campaign = FundraiserCampaignService.provision_from_request(request=fr, approver=request.user)
			messages.success(request, f"Campaign '{campaign.campaign_name}' provisioned. Manager account: {fr.contact_email}")
			return redirect("fundraisers:staff-campaign-queue")
		elif action == "decline":
			fr.status = "declined"
			fr.staff_notes = request.POST.get("staff_notes", "")
			fr.save(update_fields=["status", "staff_notes", "updated_at"])
			messages.info(request, "Request declined.")
			return redirect("fundraisers:staff-request-queue")

	return render(request, "fundraisers/staff_request_detail.html", {"fr": fr, "review_form": review_form})


class FundraiserCampaignDashboardView(LoginRequiredMixin, DetailView):
	model = FundraiserCampaign
	template_name = "fundraisers/campaign_dashboard.html"
	slug_field = "slug"
	slug_url_kwarg = "slug"

	def _get_campaign(self):
		user = self.request.user
		qs = FundraiserCampaign.objects.all() if (
			user.is_staff or user.is_superuser or user.has_any_role("staff", "admin")
		) else FundraiserCampaign.objects.filter(organization__manager=user)
		return get_object_or_404(qs, slug=self.kwargs["slug"])

	def get_queryset(self):
		user = self.request.user
		if user.is_staff or user.is_superuser or user.has_any_role("staff", "admin"):
			return FundraiserCampaign.objects.all()
		if user.has_any_role("organization_manager"):
			return FundraiserCampaign.objects.filter(organization__manager=user)
		raise PermissionDenied("You do not have access to this campaign dashboard.")

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(FundraiserCampaignService.dashboard_metrics(campaign=self.object))
		return context

	def post(self, request, slug):
		campaign = self._get_campaign()
		action = request.POST.get("action")
		if action == "upload_image":
			self._replace_image(request, campaign, "campaign_image", "Campaign image updated.")
		elif action == "upload_banner":
			self._replace_image(request, campaign, "campaign_banner", "Campaign banner updated.")
		elif action == "delete_image":
			self._delete_image(request, campaign, "campaign_image", "Campaign image removed.")
		elif action == "delete_banner":
			self._delete_image(request, campaign, "campaign_banner", "Campaign banner removed.")
		return redirect("fundraisers:campaign-dashboard", slug=campaign.slug)

	def _replace_image(self, request, campaign, field, msg):
		file = request.FILES.get(field)
		if not file:
			return
		existing = getattr(campaign, field)
		if existing:
			existing.delete(save=False)
		setattr(campaign, field, file)
		campaign.save(update_fields=[field])
		messages.success(request, msg)

	def _delete_image(self, request, campaign, field, msg):
		existing = getattr(campaign, field)
		if not existing:
			return
		existing.delete(save=False)
		setattr(campaign, field, None)
		campaign.save(update_fields=[field])
		messages.success(request, msg)
