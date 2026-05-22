from __future__ import annotations

from django.conf import settings

from .models import QRCode, ShareLink, ShareLinkType
from .qr import qr_data_uri, qr_png_bytes


class ShareLinkService:
    @staticmethod
    def build_public_url(token: str) -> str:
        base = getattr(settings, "SITE_BASE_URL", "http://localhost:8000").rstrip("/")
        return f"{base}/s/{token}/"

    @classmethod
    def get_or_create_campaign_link(cls, *, campaign, created_by=None) -> ShareLink:
        link, _ = ShareLink.objects.get_or_create(
            link_type=ShareLinkType.CAMPAIGN,
            campaign=campaign,
            defaults={"created_by": created_by},
        )
        return link

    @classmethod
    def get_or_create_team_link(cls, *, team, created_by=None) -> ShareLink:
        link, _ = ShareLink.objects.get_or_create(
            link_type=ShareLinkType.TEAM,
            team=team,
            defaults={"created_by": created_by},
        )
        return link

    @classmethod
    def get_or_create_seller_link(cls, *, store, created_by=None) -> ShareLink:
        link, _ = ShareLink.objects.get_or_create(
            link_type=ShareLinkType.SELLER,
            seller_store=store,
            defaults={"created_by": created_by},
        )
        return link

    @classmethod
    def qr_data_uri_for_link(cls, link: ShareLink) -> str:
        return qr_data_uri(cls.build_public_url(link.token))

    @classmethod
    def qr_png_for_link(cls, link: ShareLink) -> bytes:
        return qr_png_bytes(cls.build_public_url(link.token))

    @classmethod
    def ensure_qr_code_record(cls, *, link: ShareLink) -> QRCode:
        qr, _ = QRCode.objects.get_or_create(share_link=link)
        return qr

