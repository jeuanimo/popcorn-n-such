from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from fundraisers.models import FundraiserCampaign, FundraiserCampaignStatus
from security_audit.models import AuditAction
from security_audit.utils import log_audit_event


@transaction.atomic
def convert_lead_to_campaign(*, organization, actor, request=None) -> FundraiserCampaign:
    if not (actor and (actor.is_staff or actor.is_superuser or getattr(actor, "has_any_role", lambda *args: False)("staff", "admin"))):
        raise PermissionDenied("Only staff/admin can convert leads to campaigns.")

    today = timezone.localdate()
    slug = slugify(f"{organization.name}-{uuid.uuid4().hex[:8]}")

    campaign = FundraiserCampaign.objects.create(
        organization=organization,
        campaign_name=f"{organization.name} Fundraiser",
        slug=slug,
        description="",
        fundraising_purpose="",
        start_date=today,
        end_date=today + timedelta(days=30),
        goal_amount=Decimal("0.00"),
        status=FundraiserCampaignStatus.DRAFT,
        profit_percentage=Decimal("30.00"),
        created_by=actor,
        approved_by=None,
        is_active=True,
    )

    log_audit_event(
        action=AuditAction.ADMIN_ACTION,
        message="Organization converted to fundraiser campaign",
        actor=actor,
        request=request,
        target=campaign,
        metadata={"organization_id": organization.id},
    )
    return campaign
