from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView

from cart.models import Cart
from cart.services import CartService
from core.security import role_required
from fundraisers.models import FundraiserInvite, FundraiserParticipation
from orders.models import Order
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event
from sellers.models import SellerLink
from teams.models import TeamMembership

from .forms import (
	AvatarUploadForm,
	CustomerProfileForm,
	CustomerRegistrationForm,
	FundraiserJoinForm,
	NotificationPreferencesForm,
	ProfileAddressForm,
	ProfileCommentForm,
	ProfilePostForm,
	SavedAddressForm,
	UserAccountForm,
	UserProfileBioForm,
)

from .models import CustomerProfile, NotificationPreference, ProfileComment, ProfilePost, SavedAddress, UserRole
from .admin_user_create_view import admin_user_create_view


ACCOUNT_DASHBOARD_URL = "accounts:dashboard"
ACCOUNT_DASHBOARD_PATH = "/accounts/dashboard/"
ACCOUNT_ADDRESSES_URL = "accounts:addresses"
ACCOUNT_PROFILE_URL = "accounts:profile"


class RegisterView(TemplateView):
	template_name = "accounts/register.html"

	def get(self, request, *args, **kwargs):
		if request.user.is_authenticated:
			return HttpResponseRedirect(ACCOUNT_DASHBOARD_PATH)  # NOSONAR
		return render(
			request,
			self.template_name,
			{"form": CustomerRegistrationForm(), "next": ACCOUNT_DASHBOARD_PATH},
		)

	def post(self, request, *args, **kwargs):
		if request.user.is_authenticated:
			return HttpResponseRedirect(ACCOUNT_DASHBOARD_PATH)  # NOSONAR

		form = CustomerRegistrationForm(request.POST)
		if not form.is_valid():
			return render(request, self.template_name, {"form": form, "next": ACCOUNT_DASHBOARD_PATH})

		user = form.save()
		login(request, user)

		log_audit_event(
			action=AuditAction.SECURITY_EVENT,
			message="Customer account registered",
			actor=user,
			request=request,
			target=user,
		)
		return HttpResponseRedirect(ACCOUNT_DASHBOARD_PATH)  # NOSONAR


class AccountDashboardView(LoginRequiredMixin, TemplateView):
	template_name = "accounts/dashboard.html"

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		user = self.request.user

		customer_profile, _ = CustomerProfile.objects.get_or_create(user=user)
		notification_preference, _ = NotificationPreference.objects.get_or_create(
			user=user,
			defaults={"email_opt_in": user.profile.marketing_opt_in, "sms_opt_in": user.profile.sms_opt_in},
		)

		from orders.models import OrderSubscription, SubscriptionStatus

		orders = Order.objects.filter(customer=user).order_by("-created_at")
		cart = Cart.objects.filter(user=user, is_active=True).order_by("-updated_at").first()
		saved_items = cart.saved_items.select_related("sku", "sku__product") if cart else []
		active_subscriptions = (
			OrderSubscription.objects.filter(user=user, status=SubscriptionStatus.ACTIVE)
			.prefetch_related("items__sku__product")
			.order_by("next_order_date")[:4]
		)

		context.update(
			{
				"customer_profile": customer_profile,
				"notification_preference": notification_preference,
				"saved_addresses": SavedAddress.objects.filter(user=user),
				"orders": orders[:8],
				"active_cart": cart,
				"saved_items": saved_items,
				"active_subscriptions": active_subscriptions,
				"team_memberships": TeamMembership.objects.filter(member=user).select_related("team")[:8],
				"seller_links": SellerLink.objects.filter(user=user, is_active=True)[:8],
			}
		)
		return context


@login_required
def profile_view(request):
	profile = request.user.profile
	customer_profile, _ = CustomerProfile.objects.get_or_create(user=request.user, defaults={"display_name": profile.display_name})
	default_address = SavedAddress.objects.filter(user=request.user, is_default=True).order_by("-updated_at").first()
	address_initial = {}
	if default_address:
		address_initial = {
			"recipient_name": default_address.recipient_name,
			"phone_number": default_address.phone_number,
			"address_line_1": default_address.address_line_1,
			"address_line_2": default_address.address_line_2,
			"city": default_address.city,
			"state": default_address.state,
			"postal_code": default_address.postal_code,
			"country": default_address.country,
		}

	if request.method == "POST":
		account_form = UserAccountForm(request.POST, instance=request.user)
		profile_form = CustomerProfileForm(request.POST, instance=customer_profile)
		address_form = ProfileAddressForm(request.POST)
		if account_form.is_valid() and profile_form.is_valid() and address_form.is_valid():
			account_form.save()
			updated_profile = profile_form.save()
			if profile.display_name != updated_profile.display_name:
				profile.display_name = updated_profile.display_name
				profile.save(update_fields=["display_name", "updated_at"])

			if address_form.has_address_data():
				address = default_address or SavedAddress(user=request.user, label="Profile Default")
				address.recipient_name = address_form.cleaned_data["recipient_name"].strip()
				address.phone_number = address_form.cleaned_data["phone_number"].strip()
				address.address_line_1 = address_form.cleaned_data["address_line_1"].strip()
				address.address_line_2 = address_form.cleaned_data["address_line_2"].strip()
				address.city = address_form.cleaned_data["city"].strip()
				address.state = address_form.cleaned_data["state"].strip()
				address.postal_code = address_form.cleaned_data["postal_code"].strip()
				address.country = address_form.cleaned_data["country"].strip().upper() or "US"
				address.is_default = True
				address.save()
				SavedAddress.objects.filter(user=request.user).exclude(id=address.id).update(is_default=False)

			messages.success(request, "Profile updated.")
			return redirect(ACCOUNT_PROFILE_URL)
	else:
		account_form = UserAccountForm(instance=request.user)
		profile_form = CustomerProfileForm(instance=customer_profile)
		address_form = ProfileAddressForm(initial=address_initial)

	posts = (
		ProfilePost.objects.filter(author=request.user)
		.prefetch_related("comments__author")
		.order_by("-created_at")[:20]
	)
	return render(
		request,
		"accounts/profile.html",
		{
			"account_form": account_form,
			"profile_form": profile_form,
			"address_form": address_form,
			"bio_form": UserProfileBioForm(instance=request.user.profile),
			"avatar_form": AvatarUploadForm(),
			"post_form": ProfilePostForm(),
			"comment_form": ProfileCommentForm(),
			"posts": posts,
			"saved_addresses": SavedAddress.objects.filter(user=request.user).order_by("-is_default", "label", "created_at"),
			"fundraiser_participations": FundraiserParticipation.objects.filter(user=request.user).select_related("invite")[:8],
			"fundraiser_join_form": FundraiserJoinForm(),
		},
	)


@login_required
def notification_preferences_view(request):
	profile = request.user.profile
	notification_preference, _ = NotificationPreference.objects.get_or_create(
		user=request.user,
		defaults={"email_opt_in": profile.marketing_opt_in, "sms_opt_in": profile.sms_opt_in},
	)
	if request.method == "POST":
		form = NotificationPreferencesForm(request.POST, instance=notification_preference)
		if form.is_valid():
			preferences = form.save()
			profile.marketing_opt_in = preferences.email_opt_in
			profile.sms_opt_in = preferences.sms_opt_in
			profile.save(update_fields=["marketing_opt_in", "sms_opt_in", "updated_at"])
			messages.success(request, "Notification preferences updated.")
			return redirect("accounts:preferences")
	else:
		form = NotificationPreferencesForm(instance=notification_preference)

	return render(request, "accounts/preferences.html", {"form": form})


@login_required
def saved_addresses_view(request):
	if request.method == "POST":
		form = SavedAddressForm(request.POST)
		if form.is_valid():
			address = form.save(commit=False)
			address.user = request.user
			address.save()
			messages.success(request, "Address saved.")
			return redirect(ACCOUNT_ADDRESSES_URL)
	else:
		form = SavedAddressForm()

	addresses = SavedAddress.objects.filter(user=request.user)
	return render(request, "accounts/addresses.html", {"form": form, "addresses": addresses})


@login_required
def edit_saved_address_view(request, public_id):
	address = get_object_or_404(SavedAddress, public_id=public_id, user=request.user)
	if request.method == "POST":
		form = SavedAddressForm(request.POST, instance=address)
		if form.is_valid():
			form.save()
			messages.success(request, "Address updated.")
			return redirect(ACCOUNT_ADDRESSES_URL)
	else:
		form = SavedAddressForm(instance=address)

	return render(request, "accounts/address_edit.html", {"form": form, "address": address})


@login_required
def delete_saved_address_view(request, public_id):
	address = get_object_or_404(SavedAddress, public_id=public_id, user=request.user)
	if request.method == "POST":
		address.delete()
		messages.success(request, "Address deleted.")
	return redirect(ACCOUNT_ADDRESSES_URL)


@login_required
def join_fundraiser_view(request):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)

	form = FundraiserJoinForm(request.POST)
	if not form.is_valid():
		messages.error(request, "Please provide a valid invite code.")
		return redirect(ACCOUNT_PROFILE_URL)

	invite = FundraiserInvite.objects.filter(code=form.cleaned_data["invite_code"]).first()
	if not invite or not invite.is_valid:
		messages.error(request, "That fundraiser invite code is invalid or expired.")
		return redirect(ACCOUNT_PROFILE_URL)

	FundraiserParticipation.objects.get_or_create(user=request.user, invite=invite)
	messages.success(request, "Fundraiser joined successfully.")
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
def create_fundraiser_request_view(request):
	# Legacy URL — redirect to the full self-service signup flow
	return redirect("fundraisers:signup")


@login_required
def avatar_upload_view(request):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)
	form = AvatarUploadForm(request.POST, request.FILES, instance=request.user.profile)
	if form.is_valid():
		form.save()
		messages.success(request, "Profile picture updated.")
	else:
		messages.error(request, "Please choose a valid image file.")
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
def avatar_delete_view(request):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)
	profile = request.user.profile
	if profile.avatar:
		profile.avatar.delete(save=False)
		profile.avatar = None
		profile.save(update_fields=["avatar", "updated_at"])
		messages.success(request, "Profile picture removed.")
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
def post_create_view(request):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)
	form = ProfilePostForm(request.POST, request.FILES)
	if form.is_valid():
		post = form.save(commit=False)
		post.author = request.user
		post.save()
	else:
		messages.error(request, "Could not save post. Please try again.")
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
def post_edit_view(request, post_id):
	post = get_object_or_404(ProfilePost, id=post_id, author=request.user)
	if request.method == "POST":
		form = ProfilePostForm(request.POST, request.FILES, instance=post)
		if form.is_valid():
			form.save()
			messages.success(request, "Post updated.")
			return redirect(ACCOUNT_PROFILE_URL)
	else:
		form = ProfilePostForm(instance=post)
	return render(request, "accounts/post_edit.html", {"form": form, "post": post})


@login_required
def post_delete_view(request, post_id):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)
	post = get_object_or_404(ProfilePost, id=post_id, author=request.user)
	post.delete()
	messages.success(request, "Post deleted.")
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
def comment_create_view(request, post_id):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)
	post = get_object_or_404(ProfilePost, id=post_id)
	form = ProfileCommentForm(request.POST)
	if form.is_valid():
		comment = form.save(commit=False)
		comment.post = post
		comment.author = request.user
		comment.save()
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
def comment_delete_view(request, comment_id):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)
	comment = get_object_or_404(ProfileComment, id=comment_id, author=request.user)
	comment.delete()
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
def bio_update_view(request):
	if request.method != "POST":
		return redirect(ACCOUNT_PROFILE_URL)
	form = UserProfileBioForm(request.POST, instance=request.user.profile)
	if form.is_valid():
		form.save()
		messages.success(request, "Bio updated.")
	else:
		messages.error(request, "Could not update bio.")
	return redirect(ACCOUNT_PROFILE_URL)


@login_required
@role_required([UserRole.STAFF, UserRole.ADMIN])
def staff_console_view(request):
	return render(
		request,
		"accounts/staff_console.html",
		{"can_create_users": request.user.has_role(UserRole.ADMIN)},
	)
