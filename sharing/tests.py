from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from fundraisers.models import FundraiserCampaign, FundraiserCampaignStatus
from organizations.models import Organization
from sellers.models import SellerStore
from sharing.models import ShareLinkType
from sharing.services import ShareLinkService
from teams.models import Team

User = get_user_model()


class ShareLinkRedirectTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="mgr", password="pw")
        org = Organization.objects.create(name="Org", manager=self.manager)
        self.campaign = FundraiserCampaign.objects.create(
            organization=org,
            campaign_name="Drive",
            slug="drive",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=5),
            goal_amount="1000.00",
            status=FundraiserCampaignStatus.ACTIVE,
            created_by=self.manager,
            is_active=True,
        )
        self.captain = User.objects.create_user(username="capt", password="pw")
        self.team = Team.objects.create(
            organization=org,
            captain=self.captain,
            campaign=self.campaign,
            name="Team A",
            slug="team-a",
            is_active=True,
        )
        self.seller_user = User.objects.create_user(username="seller", password="pw")
        self.store = SellerStore.objects.create(
            seller=self.seller_user,
            team=self.team,
            campaign=self.campaign,
            slug="seller-store",
            display_name="Seller Store",
            seller_goal="100.00",
            is_active=True,
        )

    def test_seller_share_link_sets_secure_attribution(self):
        link = ShareLinkService.get_or_create_seller_link(store=self.store, created_by=self.seller_user)
        resp = self.client.get(f"/s/{link.token}/", follow=True)
        self.assertEqual(resp.status_code, 200)
        cart = resp.wsgi_request.session.get("cart_id")
        from cart.models import Cart

        c = Cart.objects.get(id=cart)
        self.assertIsNotNone(c.attribution)
        self.assertEqual(c.attribution.seller_store_id, self.store.id)
        self.assertEqual(c.attribution.campaign_id, self.campaign.id)
        self.assertEqual(c.attribution.team_ref_id, self.team.id)

