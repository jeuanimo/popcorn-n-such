from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, UserRole
from organizations.models import Organization
from orders.models import Order, OrderStatus
from sellers.models import SellerLink
from sellers.models import SellerStore
from teams.models import Team

from .models import FundraiserCampaign, FundraiserCampaignStatus
from .services import FundraiserCampaignService

User = get_user_model()
TEST_LOGIN_SECRET = "test-secret-fundraisers"


class FundraiserCampaignFeatureTests(TestCase):
	def setUp(self):
		self.org_manager_role, _ = Role.objects.get_or_create(key=UserRole.ORGANIZATION_MANAGER)
		self.staff_role, _ = Role.objects.get_or_create(key=UserRole.STAFF)

		self.manager = User.objects.create_user(username="manager", password=TEST_LOGIN_SECRET)
		self.manager.roles.add(self.org_manager_role)

		self.staff = User.objects.create_user(username="staff", password=TEST_LOGIN_SECRET, is_staff=True)
		self.staff.roles.add(self.staff_role)

		self.customer = User.objects.create_user(username="customer", password=TEST_LOGIN_SECRET)
		self.captain = User.objects.create_user(username="captain", password=TEST_LOGIN_SECRET)
		self.seller_user = User.objects.create_user(username="seller1", password=TEST_LOGIN_SECRET)

		self.organization = Organization.objects.create(name="School PTO", manager=self.manager)
		self.team = Team.objects.create(name="Team A", captain=self.captain, organization=self.organization)
		self.seller_link = SellerLink.objects.create(user=self.seller_user, title="Seller One", slug="seller-one", is_active=True)
		self.seller_store = SellerStore.objects.create(
			seller=self.seller_user,
			team=self.team,
			campaign=None,
			slug="seller-one-store",
			display_name="Seller One",
			seller_goal="200.00",
			is_active=True,
		)

		self.campaign = FundraiserCampaign.objects.create(
			organization=self.organization,
			campaign_name="Spring Popcorn Drive",
			slug="spring-popcorn-drive",
			description="Help our students fund activities.",
			fundraising_purpose="Band trip",
			start_date=timezone.localdate() - timedelta(days=1),
			end_date=timezone.localdate() + timedelta(days=10),
			goal_amount="2000.00",
			status=FundraiserCampaignStatus.ACTIVE,
			profit_percentage="35.00",
			created_by=self.manager,
			is_active=True,
		)
		self.campaign.teams.add(self.team)
		self.campaign.sellers.add(self.seller_link)
		self.seller_store.campaign = self.campaign
		self.seller_store.save(update_fields=["campaign", "updated_at"])

	def test_org_manager_can_create_campaign_request(self):
		self.client.login(username="manager", password=TEST_LOGIN_SECRET)
		response = self.client.post(
			reverse("fundraisers:manager-campaign-create"),
			{
				"organization": self.organization.id,
				"campaign_name": "Fall Drive",
				"slug": "fall-drive",
				"description": "Annual fundraiser",
				"fundraising_purpose": "New uniforms",
				"start_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
				"end_date": (timezone.localdate() + timedelta(days=30)).isoformat(),
				"goal_amount": "1500.00",
				"profit_percentage": "30.00",
				"public_campaign_link": "https://example.org/fall-drive",
				"is_active": True,
				"teams": [self.team.id],
				"sellers": [self.seller_link.id],
			},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		created = FundraiserCampaign.objects.get(slug="fall-drive")
		self.assertEqual(created.created_by, self.manager)
		self.assertEqual(created.status, FundraiserCampaignStatus.DRAFT)

	def test_staff_can_approve_campaign(self):
		self.campaign.status = FundraiserCampaignStatus.DRAFT
		self.campaign.save(update_fields=["status", "updated_at"])

		self.client.login(username="staff", password=TEST_LOGIN_SECRET)
		response = self.client.post(
			reverse("fundraisers:staff-campaign-approve", args=[self.campaign.slug]),
			{
				"status": FundraiserCampaignStatus.ACTIVE,
				"is_active": True,
				"start_date": self.campaign.start_date.isoformat(),
				"end_date": self.campaign.end_date.isoformat(),
				"profit_percentage": "35.00",
				"public_campaign_link": "https://example.org/spring-popcorn-drive",
			},
			follow=True,
		)
		self.assertEqual(response.status_code, 200)
		self.campaign.refresh_from_db()
		self.assertEqual(self.campaign.approved_by, self.staff)
		self.assertEqual(self.campaign.status, FundraiserCampaignStatus.ACTIVE)

	def test_public_campaign_page_shows_goal_progress_teams_and_shop_button(self):
		Order.objects.create(
			customer=self.customer,
			fundraiser_campaign=self.campaign,
			team=self.team,
			seller=self.seller_store,
			status=OrderStatus.PLACED,
			total_cents=50000,
		)

		response = self.client.get(reverse("fundraisers:public-campaign-detail", args=[self.campaign.slug]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, self.campaign.campaign_name)
		self.assertContains(response, "Shop to support this campaign")
		self.assertContains(response, self.team.name)

	def test_campaign_dashboard_metrics_top_entities_and_recent_orders(self):
		Order.objects.create(
			customer=self.customer,
			fundraiser_campaign=self.campaign,
			team=self.team,
			seller=self.seller_store,
			status=OrderStatus.PLACED,
			total_cents=15000,
		)
		Order.objects.create(
			customer=self.customer,
			fundraiser_campaign=self.campaign,
			team=self.team,
			seller=self.seller_store,
			status=OrderStatus.PAID,
			total_cents=25000,
		)

		self.client.login(username="manager", password=TEST_LOGIN_SECRET)
		response = self.client.get(reverse("fundraisers:campaign-dashboard", args=[self.campaign.slug]))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "400.00")
		self.assertContains(response, self.team.name)
		self.assertContains(response, self.seller_store.display_name)

	def test_only_active_campaigns_accept_attributed_orders_and_expired_campaigns_block(self):
		expired_campaign = FundraiserCampaign.objects.create(
			organization=self.organization,
			campaign_name="Expired Campaign",
			slug="expired-campaign",
			start_date=timezone.localdate() - timedelta(days=10),
			end_date=timezone.localdate() - timedelta(days=1),
			goal_amount="1000.00",
			status=FundraiserCampaignStatus.ACTIVE,
			created_by=self.manager,
			is_active=True,
		)

		order = Order(
			customer=self.customer,
			fundraiser_campaign=expired_campaign,
			status=OrderStatus.DRAFT,
			total_cents=1000,
		)
		with self.assertRaises(ValidationError):
			order.clean()

	def test_direct_store_orders_allowed_without_campaign(self):
		direct_order = Order(customer=self.customer, status=OrderStatus.DRAFT, total_cents=500)
		direct_order.clean()

	def test_campaign_service_rejects_inactive_campaign(self):
		self.campaign.is_active = False
		self.campaign.save(update_fields=["is_active", "updated_at"])
		with self.assertRaises(ValidationError):
			FundraiserCampaignService.validate_order_attribution(campaign=self.campaign)
