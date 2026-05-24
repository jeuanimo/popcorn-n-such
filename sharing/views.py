from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View

from cart.services import CartService

from .models import ShareLink, ShareLinkType
from .services import ShareLinkService


class ShareLinkRedirectView(View):
    """
    Public entrypoint for share links.
    Tracks clicks and sets server-side cart attribution.
    """

    def get(self, request, token: str):
        link = get_object_or_404(ShareLink.objects.select_related("campaign", "team", "seller_store__campaign", "seller_store__team"), token=token)

        with transaction.atomic():
            ShareLink.objects.filter(id=link.id).update(click_count=F("click_count") + 1, last_clicked_at=timezone.now())
        # set attribution
        if link.seller_store_id:
            CartService.set_seller_store_attribution(request=request, store=link.seller_store)
            CartService.set_share_link(request=request, share_link=link)
        elif link.team_id:
            CartService.set_team_attribution(request=request, team=link.team)
            CartService.set_share_link(request=request, share_link=link)
        elif link.campaign_id:
            CartService.set_campaign_attribution(request=request, campaign=link.campaign)
            CartService.set_share_link(request=request, share_link=link)

        # Redirect to the appropriate public page based on link type
        if link.seller_store_id:
            return redirect("sellers:public-store", slug=link.seller_store.slug)
        elif link.team_id:
            return redirect("teams:public-detail", slug=link.team.slug)
        elif link.campaign_id:
            return redirect("fundraisers:public-campaign-detail", slug=link.campaign.slug)
        return redirect("products:list")


class ShareLinkQRCodeDownloadView(View):
    """
    Protected QR code download (PNG).
    """

    def get(self, request, token: str):
        link = get_object_or_404(ShareLink.objects.select_related("campaign__organization", "team__captain", "seller_store__seller"), token=token)

        # Role-based checks
        if link.link_type == ShareLinkType.SELLER:
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication required.")
            if not (request.user.is_staff or request.user.is_superuser or link.seller_store.seller_id == request.user.id):
                raise PermissionDenied("You can only download your own seller QR code.")
        elif link.link_type == ShareLinkType.TEAM:
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication required.")
            if not (request.user.is_staff or request.user.is_superuser or link.team.captain_id == request.user.id):
                raise PermissionDenied("You can only download your team QR code.")
        elif link.link_type == ShareLinkType.CAMPAIGN:
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication required.")
            if not (request.user.is_staff or request.user.is_superuser or link.campaign.organization.manager_id == request.user.id):
                raise PermissionDenied("You can only download your organization campaign QR code.")

        png = ShareLinkService.qr_png_for_link(link)
        resp = HttpResponse(png, content_type="image/png")
        resp["Content-Disposition"] = f'attachment; filename="qr_{token}.png"'
        return resp
