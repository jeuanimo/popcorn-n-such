from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def _default_token() -> str:
    return uuid.uuid4().hex


class ShareLinkType(models.TextChoices):
    CAMPAIGN = "campaign", "Campaign"
    TEAM = "team", "Team"
    SELLER = "seller", "Seller"


class ShareLink(models.Model):
    """
    Public share link with a non-guessable token.
    Does not expose private IDs in URLs.
    """

    token = models.CharField(max_length=40, unique=True, db_index=True, default=_default_token)
    link_type = models.CharField(max_length=20, choices=ShareLinkType.choices)

    campaign = models.ForeignKey(
        "fundraisers.FundraiserCampaign",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="share_links",
    )
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="share_links",
    )
    seller_store = models.ForeignKey(
        "sellers.SellerStore",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="share_links",
    )

    # Metrics
    click_count = models.PositiveIntegerField(default=0)
    conversion_count = models.PositiveIntegerField(default=0)
    last_clicked_at = models.DateTimeField(null=True, blank=True)
    last_converted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_share_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["link_type", "created_at"]),
        ]

    def __str__(self) -> str:
        target = self.campaign or self.team or self.seller_store
        return f"{self.link_type}:{self.token} -> {target}"

    def bump_click(self):
        self.click_count = self.click_count + 1
        self.last_clicked_at = timezone.now()
        self.save(update_fields=["click_count", "last_clicked_at"])

    def bump_conversion(self):
        self.conversion_count = self.conversion_count + 1
        self.last_converted_at = timezone.now()
        self.save(update_fields=["conversion_count", "last_converted_at"])


class QRCode(models.Model):
    """
    Stored QR code image for a ShareLink.
    """

    share_link = models.OneToOneField(ShareLink, on_delete=models.CASCADE, related_name="qr_code")
    image = models.ImageField(upload_to="sharing/qr/%Y/%m/%d/", blank=True)
    format = models.CharField(max_length=20, default="png")
    size = models.PositiveIntegerField(default=256)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"QR for {self.share_link.token}"

