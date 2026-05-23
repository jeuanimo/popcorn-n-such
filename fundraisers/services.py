from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.text import slugify

from core.mail import send_runtime_mail
from orders.models import Order, OrderStatus
from organizations.models import LeadStatus, Organization, OrganizationType
from teams.models import Team

from .models import FundraiserCampaign, FundraiserCampaignStatus, FundraiserRequest
from sharing.services import ShareLinkService

User = get_user_model()


class FundraiserCampaignService:
    ORDER_STATUSES_FOR_METRICS = (
        OrderStatus.PLACED,
        OrderStatus.PAID,
        OrderStatus.FULFILLING,
        OrderStatus.SHIPPED,
    )

    @classmethod
    def request_campaign(cls, *, manager, form):
        campaign = form.save(commit=False)
        if campaign.organization.manager_id != manager.id:
            raise PermissionDenied("You can only create campaigns for your organizations.")

        campaign.created_by = manager
        campaign.status = FundraiserCampaignStatus.DRAFT
        campaign.is_active = False
        campaign.approved_by = None
        campaign.save()
        form.save_m2m()
        return campaign

    @classmethod
    def approve_campaign(cls, *, campaign: FundraiserCampaign, approver, form):
        if not (approver.is_staff or approver.is_superuser or approver.has_any_role("staff", "admin")):
            raise PermissionDenied("Only staff can approve campaigns.")

        updated = form.save(commit=False)
        updated.approved_by = approver
        if updated.status == FundraiserCampaignStatus.DRAFT:
            updated.status = FundraiserCampaignStatus.SCHEDULED
        updated.save()
        form.save_m2m()
        return updated

    @classmethod
    def validate_order_attribution(cls, *, campaign: FundraiserCampaign | None):
        if campaign is None:
            return
        if not campaign.is_accepting_orders():
            raise ValidationError("This fundraiser campaign is not currently accepting attributed orders.")

    @classmethod
    def dashboard_metrics(cls, *, campaign: FundraiserCampaign) -> dict:
        orders = Order.objects.filter(fundraiser_campaign=campaign, status__in=cls.ORDER_STATUSES_FOR_METRICS)
        total_sales = int(orders.aggregate(total=Sum("total_cents")).get("total") or 0)
        total_orders = orders.count()

        profit_ratio = Decimal(campaign.profit_percentage) / Decimal("100")
        profit_estimate = int(Decimal(total_sales) * profit_ratio)

        top_teams = (
            orders.filter(team__isnull=False)
            .values("team__id", "team__name")
            .annotate(order_count=Count("id"), sales_cents=Sum("total_cents"))
            .order_by("-sales_cents", "team__name")[:5]
        )
        top_sellers = (
            orders.filter(seller__isnull=False)
            .values("seller__id", "seller__display_name", "seller__slug")
            .annotate(order_count=Count("id"), sales_cents=Sum("total_cents"))
            .order_by("-sales_cents", "seller__display_name")[:5]
        )

        return {
            "total_sales_cents": total_sales,
            "total_orders": total_orders,
            "profit_estimate_cents": profit_estimate,
            "goal_progress_percent": campaign.goal_progress_percent(total_sales),
            "top_teams": top_teams,
            "top_sellers": top_sellers,
            "recent_orders": orders.select_related("customer", "team", "seller").order_by("-created_at")[:10],
            "share_link": ShareLinkService.build_public_url(
                ShareLinkService.get_or_create_campaign_link(campaign=campaign, created_by=campaign.created_by).token
            ),
            "qr_data_uri": ShareLinkService.qr_data_uri_for_link(
                ShareLinkService.get_or_create_campaign_link(campaign=campaign, created_by=campaign.created_by)
            ),
            "suggested_message": f"Support {campaign.campaign_name}! Shop here: "
            f"{ShareLinkService.build_public_url(ShareLinkService.get_or_create_campaign_link(campaign=campaign, created_by=campaign.created_by).token)}",
        }

    @classmethod
    @transaction.atomic
    def signup_and_provision(cls, *, form, request=None) -> FundraiserCampaign:
        """
        Public fundraiser signup: save the request, provision the full
        campaign stack immediately, and email the organizer.
        """
        data = form.cleaned_data

        # Persist the intake record
        fr = FundraiserRequest.objects.create(
            contact_first_name=data["contact_first_name"],
            contact_last_name=data["contact_last_name"],
            contact_email=data["contact_email"],
            contact_phone=data.get("contact_phone", ""),
            organization_name=data["organization_name"],
            org_type=data["org_type"],
            estimated_sellers=data["estimated_sellers"],
            fundraising_purpose=data["fundraising_purpose"],
            desired_start_date=data.get("desired_start_date"),
            goal_amount=data.get("goal_amount"),
        )

        # Create or retrieve manager user account
        username_base = slugify(data["contact_email"].split("@")[0])[:140] or "user"
        username = username_base
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{username_base}{counter}"
            counter += 1

        manager, is_new_user = User.objects.get_or_create(
            email=data["contact_email"],
            defaults={
                "username": username,
                "first_name": data["contact_first_name"],
                "last_name": data["contact_last_name"],
            },
        )
        if is_new_user:
            manager.set_unusable_password()
            manager.save(update_fields=["password"])

        # Create or retrieve organization
        org, _ = Organization.objects.get_or_create(
            name=data["organization_name"],
            defaults={
                "org_type": data.get("org_type") or OrganizationType.SCHOOL,
                "lead_status": LeadStatus.ACTIVE_FUNDRAISER,
                "manager": manager,
                "email": data["contact_email"],
                "phone": data.get("contact_phone", ""),
            },
        )

        # Build unique campaign slug
        base_slug = slugify(data["organization_name"])[:180]
        slug = base_slug
        counter = 1
        while FundraiserCampaign.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        from datetime import date, timedelta
        start = data.get("desired_start_date") or date.today()
        campaign = FundraiserCampaign.objects.create(
            organization=org,
            campaign_name=f"{data['organization_name']} Fundraiser",
            slug=slug,
            fundraising_purpose=data["fundraising_purpose"],
            start_date=start,
            end_date=start + timedelta(days=30),
            goal_amount=data.get("goal_amount") or Decimal("1000.00"),
            status=FundraiserCampaignStatus.ACTIVE,
            is_active=True,
            created_by=manager,
        )

        # Create default team
        Team.objects.create(
            campaign=campaign,
            organization=org,
            name=f"{data['organization_name']} Team",
            slug=f"{slug}-team",
        )

        # Mark request approved and link user
        fr.user = manager
        fr.status = "approved"
        fr.save(update_fields=["user", "status", "updated_at"])

        # Send confirmation email
        cls._send_campaign_ready_email(
            manager=manager,
            campaign=campaign,
            is_new_user=is_new_user,
            request=request,
        )

        return campaign

    @classmethod
    def _send_campaign_ready_email(cls, *, manager, campaign, is_new_user, request=None):
        if not manager.email:
            return

        if request:
            campaign_url = request.build_absolute_uri(
                f"/fundraisers/campaign/{campaign.slug}/"
            )
            dashboard_url = request.build_absolute_uri(
                f"/fundraisers/manage/{campaign.slug}/dashboard/"
            )
        else:
            campaign_url = f"/fundraisers/campaign/{campaign.slug}/"
            dashboard_url = f"/fundraisers/manage/{campaign.slug}/dashboard/"

        password_reset_url = ""
        if is_new_user and request:
            uid = urlsafe_base64_encode(force_bytes(manager.pk))
            token = default_token_generator.make_token(manager)
            password_reset_url = request.build_absolute_uri(
                f"/accounts/reset/{uid}/{token}/"
            )

        context = {
            "first_name": manager.first_name or manager.username,
            "campaign_name": campaign.campaign_name,
            "campaign_url": campaign_url,
            "dashboard_url": dashboard_url,
            "contact_email": manager.email,
            "password_reset_url": password_reset_url,
        }
        subject = render_to_string(
            "fundraisers/email/campaign_ready_subject.txt", context
        ).strip()
        body = render_to_string("fundraisers/email/campaign_ready.txt", context)

        send_runtime_mail(
            subject=subject,
            message=body,
            recipient_list=[manager.email],
            fail_silently=True,
        )

    @classmethod
    @transaction.atomic
    def provision_from_request(cls, *, request: FundraiserRequest, approver) -> FundraiserCampaign:
        """
        Staff approval: create or reuse an Organization + manager account,
        then create a DRAFT FundraiserCampaign and a default Team.
        """
        if not (approver.is_staff or approver.is_superuser or approver.has_any_role("staff", "admin")):
            raise PermissionDenied("Only staff can provision campaigns.")

        # Create or retrieve the manager user account
        manager, _ = User.objects.get_or_create(
            email=request.contact_email,
            defaults={
                "username": slugify(request.contact_email.split("@")[0])[:150] or "user",
                "first_name": request.contact_first_name,
                "last_name": request.contact_last_name,
            },
        )

        # Create or retrieve the organization
        org, _ = Organization.objects.get_or_create(
            name=request.organization_name,
            defaults={
                "org_type": request.org_type or OrganizationType.SCHOOL,
                "lead_status": LeadStatus.ACTIVE_FUNDRAISER,
                "manager": manager,
                "email": request.contact_email,
                "phone": request.contact_phone,
            },
        )

        # Build a unique campaign slug
        base_slug = slugify(request.organization_name)[:180]
        slug = base_slug
        counter = 1
        while FundraiserCampaign.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        from datetime import date, timedelta
        start = request.desired_start_date or date.today()
        campaign = FundraiserCampaign.objects.create(
            organization=org,
            campaign_name=f"{request.organization_name} Fundraiser",
            slug=slug,
            fundraising_purpose=request.fundraising_purpose,
            start_date=start,
            end_date=start + timedelta(days=30),
            goal_amount=request.goal_amount or Decimal("1000.00"),
            status=FundraiserCampaignStatus.ACTIVE,
            is_active=True,
            created_by=manager,
            approved_by=approver,
        )

        # Create the default team
        team_slug = f"{slug}-team"
        Team.objects.create(
            campaign=campaign,
            organization=org,
            name=f"{request.organization_name} Team",
            slug=team_slug,
        )

        # Link user and mark request approved
        request.user = manager
        request.status = "approved"
        request.save(update_fields=["user", "status", "updated_at"])

        return campaign

    @classmethod
    def campaign_progress_context(cls, *, campaign: FundraiserCampaign) -> dict:
        metrics = cls.dashboard_metrics(campaign=campaign)
        return {
            **metrics,
            "is_accepting_orders": campaign.is_accepting_orders(),
            "shop_url": f"/products/?campaign={campaign.slug}",
            "today": timezone.localdate(),
        }

    @classmethod
    def post_publish_check_issues(cls, *, campaign: FundraiserCampaign) -> list[str]:
        issues: list[str] = []
        today = timezone.localdate()
        run_days = (campaign.end_date - campaign.start_date).days
        if run_days > 60:
            issues.append("Long campaign duration (>60 days)")
        if campaign.start_date < today:
            issues.append("Start date is in the past")
        if campaign.goal_amount > Decimal("50000.00"):
            issues.append("High goal amount (> $50,000)")
        if not campaign.description.strip():
            issues.append("Missing campaign description")
        if not campaign.campaign_image:
            issues.append("Missing campaign image")
        if not campaign.campaign_banner:
            issues.append("Missing campaign banner")
        return issues
