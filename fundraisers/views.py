from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView

from django.db.models import OuterRef, Subquery

from cart.services import CartService
from core.security import RoleRequiredMixin
from products.models import Product, SKU

from sellers.models import SellerStore

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

	def get(self, request, *args, **kwargs):
		response = super().get(request, *args, **kwargs)
		if self.object.is_accepting_orders():
			CartService.set_campaign_attribution(request=request, campaign=self.object)
		return response

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(FundraiserCampaignService.campaign_progress_context(campaign=self.object))
		context["is_accepting_orders"] = self.object.is_accepting_orders()
		_active_sku = SKU.objects.filter(product=OuterRef("pk"), is_active=True).order_by("retail_price")
		context["products"] = (
			Product.objects.active()
			.prefetch_related("skus")
			.annotate(
				fundraiser_sku_id=Subquery(_active_sku.values("id")[:1]),
				fundraiser_price=Subquery(_active_sku.values("retail_price")[:1]),
			)
			.order_by("-is_featured", "name")
		)
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
	"""Staff queue for fundraiser requests — shows all statuses."""
	template_name = "fundraisers/staff_request_queue.html"
	context_object_name = "requests"
	allowed_roles = ("staff", "admin")

	def get_queryset(self):
		return FundraiserRequest.objects.order_by("-created_at")


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


@login_required
def fundraiser_request_delete_view(request, pk: int):
	if not (request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin")):
		raise PermissionDenied("Only staff can delete fundraiser requests.")
	fr = get_object_or_404(FundraiserRequest, pk=pk)
	if request.method == "POST":
		name = fr.organization_name
		fr.delete()
		messages.success(request, f"Fundraiser request from '{name}' deleted.")
	return redirect("fundraisers:staff-request-queue")


@login_required
def fundraiser_campaign_delete_view(request, slug: str):
	if not (request.user.is_staff or request.user.is_superuser or request.user.has_any_role("staff", "admin")):
		raise PermissionDenied("Only staff can delete fundraiser campaigns.")
	campaign = get_object_or_404(FundraiserCampaign, slug=slug)
	if request.method == "POST":
		name = campaign.campaign_name
		from orders.models import Order as _Order
		_Order.objects.filter(fundraiser_campaign=campaign).update(fundraiser_campaign=None)
		from teams.models import Team as _Team
		_Team.objects.filter(campaign=campaign).update(campaign=None)
		campaign.delete()
		messages.success(request, f"Campaign '{name}' deleted.")
	return redirect("fundraisers:staff-campaign-queue")


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
		# Allow the campaign creator or the linked organization's manager
		from django.db.models import Q
		return FundraiserCampaign.objects.filter(
			Q(created_by=user) | Q(organization__manager=user)
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context.update(FundraiserCampaignService.dashboard_metrics(campaign=self.object))
		context["campaign_teams"] = (
			self.object.campaign_teams.select_related("captain").order_by("name")
		)
		context["campaign_sellers"] = (
			self.object.seller_stores.select_related("seller").order_by("display_name")
		)
		from django.urls import reverse
		context["seller_invite_url"] = self.request.build_absolute_uri(
			reverse("fundraisers:seller-join", kwargs={"slug": self.object.slug})
		)
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
		elif action == "create_team":
			self._create_team(request, campaign)
		elif action == "rename_team":
			self._rename_team(request, campaign)
		elif action == "delete_team":
			self._delete_team(request, campaign)
		elif action == "change_status":
			self._change_status(request, campaign)
		elif action == "send_invite":
			self._send_invite(request, campaign)
		return redirect("fundraisers:campaign-dashboard", slug=campaign.slug)

	def _change_status(self, request, campaign):
		new_status = request.POST.get("new_status", "").strip()
		allowed = {
			FundraiserCampaignStatus.DRAFT: [FundraiserCampaignStatus.ACTIVE, FundraiserCampaignStatus.SCHEDULED],
			FundraiserCampaignStatus.SCHEDULED: [FundraiserCampaignStatus.ACTIVE, FundraiserCampaignStatus.DRAFT],
			FundraiserCampaignStatus.ACTIVE: [FundraiserCampaignStatus.CLOSED],
			FundraiserCampaignStatus.CLOSED: [FundraiserCampaignStatus.ACTIVE],
		}
		if new_status in allowed.get(campaign.status, []):
			campaign.status = new_status
			campaign.save(update_fields=["status", "updated_at"])
			messages.success(request, f"Campaign status updated to {campaign.get_status_display()}.")
		else:
			messages.error(request, f"Cannot change from {campaign.get_status_display()} to {new_status}.")

	def _create_team(self, request, campaign):
		from django.utils.text import slugify
		from teams.models import Team
		name = request.POST.get("team_name", "").strip()
		if not name:
			messages.error(request, "Team name is required.")
			return
		base_slug = slugify(name)[:270]
		team_slug = base_slug
		counter = 1
		while Team.objects.filter(slug=team_slug).exists():
			team_slug = f"{base_slug}-{counter}"
			counter += 1
		Team.objects.create(
			campaign=campaign,
			organization=campaign.organization,
			name=name,
			slug=team_slug,
			captain=request.user,
		)
		messages.success(request, f"Team '{name}' created.")

	def _rename_team(self, request, campaign):
		from teams.models import Team
		team_pk = request.POST.get("team_pk", "").strip()
		new_name = request.POST.get("team_name", "").strip()
		if not team_pk or not new_name:
			messages.error(request, "Team name is required.")
			return
		team = get_object_or_404(Team, pk=team_pk, campaign=campaign)
		old_name = team.name
		team.name = new_name
		team.save(update_fields=["name", "updated_at"])
		messages.success(request, f"Team renamed from '{old_name}' to '{new_name}'.")

	def _delete_team(self, request, campaign):
		from django.db import ProtectedError
		from teams.models import Team
		team_pk = request.POST.get("team_pk", "").strip()
		if not team_pk:
			messages.error(request, "No team specified.")
			return
		team = get_object_or_404(Team, pk=team_pk, campaign=campaign)
		name = team.name
		try:
			team.delete()
			messages.success(request, f"Team '{name}' deleted.")
		except ProtectedError:
			# Team has orders — soft delete instead
			team.is_active = False
			team.save(update_fields=["is_active", "updated_at"])
			messages.success(request, f"Team '{name}' deactivated (it has existing orders).")

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

	def _send_invite(self, request, campaign):
		from django.core.validators import validate_email
		from django.core.exceptions import ValidationError as DjangoValidationError

		raw_emails = request.POST.get("invite_emails", "")
		recipient_name = request.POST.get("invite_name", "").strip()
		inviter_name = (
			request.user.get_full_name() or request.user.username
		)

		emails = [e.strip() for e in raw_emails.replace(",", "\n").splitlines() if e.strip()]
		if not emails:
			messages.error(request, "Please enter at least one email address.")
			return

		sent, failed = 0, 0
		for email in emails:
			try:
				validate_email(email)
			except DjangoValidationError:
				failed += 1
				continue
			ok = FundraiserCampaignService.send_seller_invite_email(
				campaign=campaign,
				recipient_email=email,
				recipient_name=recipient_name,
				inviter_name=inviter_name,
				request=request,
			)
			if ok:
				sent += 1
			else:
				failed += 1

		if sent:
			messages.success(request, f"Invite sent to {sent} recipient(s).")
		if failed:
			messages.warning(request, f"{failed} address(es) could not be sent.")


@login_required
def campaign_seller_join_view(request, slug):
	"""Sellers land here from the invite link to create their personal store for a campaign."""
	from django.utils.text import slugify

	campaign = get_object_or_404(FundraiserCampaign, slug=slug, is_active=True)

	# If they already have a store for this campaign, send them straight to it.
	existing = SellerStore.objects.filter(seller=request.user, campaign=campaign).first()
	if existing:
		messages.info(request, "You already have a store for this campaign.")
		return redirect("sellers:dashboard", slug=existing.slug)

	if request.method == "POST":
		display_name = request.POST.get("display_name", "").strip() or (
			request.user.get_full_name() or request.user.username
		)
		personal_message = request.POST.get("personal_message", "").strip()
		try:
			seller_goal = max(0, float(request.POST.get("seller_goal") or 0))
		except (ValueError, TypeError):
			seller_goal = 0

		# Auto-generate a unique slug
		base_slug = slugify(f"{request.user.username}-{campaign.slug}")[:180]
		store_slug = base_slug
		counter = 1
		while SellerStore.objects.filter(slug=store_slug).exists():
			store_slug = f"{base_slug[:175]}-{counter}"
			counter += 1

		store = SellerStore.objects.create(
			seller=request.user,
			campaign=campaign,
			display_name=display_name,
			slug=store_slug,
			personal_message=personal_message,
			seller_goal=seller_goal,
		)
		messages.success(request, f"Your seller store for {campaign.campaign_name} is live!")
		return redirect("sellers:dashboard", slug=store.slug)

	context = {
		"campaign": campaign,
		"default_display_name": request.user.get_full_name() or request.user.username,
	}
	return render(request, "fundraisers/seller_join.html", context)
