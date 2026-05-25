from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import DetailView, ListView

from core.security import RoleRequiredMixin, TeamCaptainQuerysetMixin
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event

from .forms import JoinTeamByCodeForm, MemberReminderForm, MoveSellerForm, TeamCreateForm, TeamEditForm
from .models import Team, TeamMembership, TeamMemberRole
from .services import TeamService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEAM_FORM_TEMPLATE = "teams/team_form.html"

def _is_staff_or_admin(user) -> bool:
    return user.is_staff or user.is_superuser or user.has_any_role("staff", "admin")


def _active_member_or_staff(user, team) -> bool:
    """Return True if the user is an active member / captain of *team* or is staff."""
    if _is_staff_or_admin(user):
        return True
    return TeamMembership.objects.filter(team=team, member=user, is_active=True).exists()


def _resolve_team_organization(request, *, has_staff_access: bool, existing_org=None):
    if existing_org is not None:
        return existing_org, None
    if not has_staff_access:
        return None, "No organization found for your account."

    from organizations.models import Organization

    org_id = request.POST.get("organization")
    if not org_id:
        return None, "Please specify an organization."
    return get_object_or_404(Organization, pk=org_id), None


# ---------------------------------------------------------------------------
# Public views
# ---------------------------------------------------------------------------

class PublicTeamDetailView(DetailView):
    model = Team
    template_name = "teams/public_team_detail.html"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return Team.objects.filter(is_active=True).select_related("campaign", "organization", "captain")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        team = self.object
        metrics = TeamService.dashboard_metrics(team=team)
        context["share_link"] = metrics["share_link"]
        context["qr_data_uri"] = metrics["qr_data_uri"]
        context["total_sales_cents"] = metrics["total_sales_cents"]
        context["total_orders"] = metrics["total_orders"]
        context["goal_progress_percent"] = metrics["goal_progress_percent"]
        return context


# ---------------------------------------------------------------------------
# Join by invite code
# ---------------------------------------------------------------------------

@login_required
def join_team_view(request, slug: str):
    team = get_object_or_404(Team, slug=slug, is_active=True)

    # If the invite code is in the URL query param, auto-join — no form needed.
    url_code = request.GET.get("code", "").strip()
    if url_code and url_code == team.invite_code:
        if not TeamMembership.objects.filter(team=team, member=request.user, is_active=True).exists():
            try:
                membership = TeamService.join_team_by_code(
                    user=request.user,
                    invite_code=url_code,
                )
                log_audit_event(
                    actor=request.user,
                    action=AuditAction.UPDATE,
                    message=f"User joined team {team.slug} via invite link",
                    request=request,
                    target=membership,
                )
                messages.success(request, f"You joined {team.name}!")
            except ValidationError as exc:
                messages.error(request, str(exc))
        else:
            messages.info(request, f"You're already a member of {team.name}.")
        return redirect("teams:dashboard", slug=team.slug)

    form = JoinTeamByCodeForm(request.POST or None, initial={"invite_code": url_code})

    if request.method == "POST" and form.is_valid():
        try:
            membership = TeamService.join_team_by_code(
                user=request.user,
                invite_code=form.cleaned_data["invite_code"],
            )
            log_audit_event(
                actor=request.user,
                action=AuditAction.UPDATE,
                message=f"User joined team {team.slug} via invite code",
                request=request,
                target=membership,
            )
            messages.success(request, f"You joined {team.name}!")
            return redirect("teams:dashboard", slug=team.slug)
        except ValidationError as exc:
            form.add_error("invite_code", exc)

    return render(request, "teams/join_team.html", {"form": form, "team": team})


# ---------------------------------------------------------------------------
# Team dashboard (members + captains + staff)
# ---------------------------------------------------------------------------

@login_required
def team_dashboard_view(request, slug: str):
    team = get_object_or_404(Team, slug=slug)
    if not _active_member_or_staff(request.user, team):
        raise PermissionDenied("You must be an active team member to view this dashboard.")

    metrics = TeamService.dashboard_metrics(team=team)
    fundraising_shop_link = ""
    if team.campaign:
        fundraising_shop_link = request.build_absolute_uri(
            reverse("fundraisers:public-campaign-detail", kwargs={"slug": team.campaign.slug})
        )

    return render(
        request,
        "teams/team_dashboard.html",
        {"team": team, "fundraising_shop_link": fundraising_shop_link, **metrics},
    )


# ---------------------------------------------------------------------------
# Team member list (captain + staff)
# ---------------------------------------------------------------------------

@login_required
def team_members_view(request, slug: str):
    team = get_object_or_404(Team, slug=slug)
    is_captain = team.captain_id == request.user.pk
    if not (is_captain or _is_staff_or_admin(request.user)):
        raise PermissionDenied("Only the team captain or staff can view the member list.")

    memberships = TeamMembership.objects.filter(team=team).select_related("member").order_by(
        "-role", "member__username"
    )
    return render(
        request,
        "teams/team_members.html",
        {"team": team, "memberships": memberships, "is_captain": is_captain},
    )


# ---------------------------------------------------------------------------
# Send member reminders (captain only)
# ---------------------------------------------------------------------------

@login_required
def send_reminder_view(request, slug: str):
    team = get_object_or_404(Team, slug=slug)
    if team.captain_id != request.user.pk:
        raise PermissionDenied("Only the team captain can send reminders.")

    form = MemberReminderForm(request.POST or None, team=team)
    if request.method == "POST" and form.is_valid():
        recipients_qs = form.cleaned_data.get("recipients") or None
        sent = TeamService.send_member_reminders(
            team=team,
            captain=request.user,
            subject=form.cleaned_data["subject"],
            message=form.cleaned_data["message"],
            memberships=recipients_qs if recipients_qs else None,
        )
        messages.success(request, f"Reminder sent to {sent} member(s).")
        return redirect("teams:members", slug=team.slug)

    return render(request, "teams/send_reminder.html", {"team": team, "form": form})


# ---------------------------------------------------------------------------
# Captain team list
# ---------------------------------------------------------------------------

class TeamCaptainTeamListView(RoleRequiredMixin, TeamCaptainQuerysetMixin, ListView):
    model = Team
    template_name = "teams/team_list.html"
    context_object_name = "teams"
    allowed_roles = ("team_captain",)


# ---------------------------------------------------------------------------
# Team create (captain / org manager)
# ---------------------------------------------------------------------------

@login_required
def team_create_view(request):
    has_staff_access = _is_staff_or_admin(request.user)
    if not (request.user.has_any_role("team_captain", "organization_manager") or has_staff_access):
        raise PermissionDenied("You do not have permission to create a team.")

    organization = None
    if request.user.has_any_role("organization_manager"):
        from organizations.models import Organization
        organization = Organization.objects.filter(manager=request.user).first()

    form = TeamCreateForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        organization, org_error = _resolve_team_organization(
            request,
            has_staff_access=has_staff_access,
            existing_org=organization,
        )
        if org_error:
            messages.error(request, org_error)
            return render(request, TEAM_FORM_TEMPLATE, {"form": form})

        team = TeamService.create_team(user=request.user, organization=organization, form=form)
        messages.success(request, f"Team '{team.name}' created.")
        return redirect("teams:dashboard", slug=team.slug)

    return render(request, TEAM_FORM_TEMPLATE, {"form": form})


# ---------------------------------------------------------------------------
# Team edit (captain or staff)
# ---------------------------------------------------------------------------

@login_required
def team_edit_view(request, slug: str):
    team = get_object_or_404(Team, slug=slug)
    is_captain = team.captain_id == request.user.pk
    if not (is_captain or _is_staff_or_admin(request.user)):
        raise PermissionDenied("Only the team captain or staff can edit this team.")

    from django.conf import settings as django_settings

    old_slug = team.slug
    form = TeamEditForm(request.POST or None, request.FILES or None, instance=team, user=request.user)
    if request.method == "POST" and form.is_valid():
        updated_team = form.save()
        if updated_team.slug != old_slug:
            base_url = getattr(django_settings, "SITE_BASE_URL", "http://localhost:8000")
            updated_team.public_team_link = f"{base_url}/teams/{updated_team.slug}/"
            updated_team.save(update_fields=["public_team_link"])
        log_audit_event(
            actor=request.user,
            action=AuditAction.UPDATE,
            message=f"Team updated: {updated_team.slug}",
            request=request,
            target=updated_team,
        )
        messages.success(request, f"Team '{updated_team.name}' updated.")
        return redirect("teams:dashboard", slug=updated_team.slug)

    return render(request, "teams/team_edit.html", {"form": form, "team": team})


# ---------------------------------------------------------------------------
# Team delete (captain or staff)
# ---------------------------------------------------------------------------

@login_required
def team_delete_view(request, slug: str):
    team = get_object_or_404(Team, slug=slug)
    is_captain = team.captain_id == request.user.pk
    if not (is_captain or _is_staff_or_admin(request.user)):
        raise PermissionDenied("Only the team captain or staff can delete this team.")

    if request.method == "POST":
        try:
            team_name = team.name
            log_audit_event(
                actor=request.user,
                action=AuditAction.DELETE,
                message=f"Team deleted: {team_name} ({slug})",
                request=request,
                metadata={"name": team_name, "slug": slug},
            )
            from orders.models import Order as _Order
            _Order.objects.filter(team=team).update(team=None)
            team.delete()
            messages.success(request, f"Team '{team_name}' has been deleted.")
            if _is_staff_or_admin(request.user):
                return redirect("teams:staff-list")
            return redirect("teams:my-teams")
        except Exception as exc:
            import traceback
            err = traceback.format_exc()
            messages.error(request, f"Delete failed — {type(exc).__name__}: {exc}")
            return render(request, "teams/team_confirm_delete.html", {"team": team, "err": err})

    return render(request, "teams/team_confirm_delete.html", {"team": team})


# ---------------------------------------------------------------------------
# Staff views
# ---------------------------------------------------------------------------

class StaffTeamListView(RoleRequiredMixin, ListView):
    model = Team
    template_name = "teams/staff_team_list.html"
    context_object_name = "teams"
    allowed_roles = ("staff", "admin")

    def get_queryset(self):
        return Team.objects.select_related("campaign", "organization", "captain").order_by("name")


@login_required
def staff_move_seller_view(request):
    if not _is_staff_or_admin(request.user):
        raise PermissionDenied("Only staff can move sellers between teams.")

    form = MoveSellerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            TeamService.move_seller(
                seller_link=form.cleaned_data["seller_link"],
                from_team=form.cleaned_data["from_team"],
                to_team=form.cleaned_data["to_team"],
                staff_user=request.user,
            )
            messages.success(request, "Seller moved successfully.")
            log_audit_event(
                actor=request.user,
                action=AuditAction.UPDATE,
                message="Seller moved between teams",
                request=request,
                target=form.cleaned_data["seller_link"],
                metadata={
                    "from_team": form.cleaned_data["from_team"].slug,
                    "to_team": form.cleaned_data["to_team"].slug,
                },
            )
            return redirect("teams:staff-list")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))

    return render(request, "teams/staff_move_seller.html", {"form": form})
