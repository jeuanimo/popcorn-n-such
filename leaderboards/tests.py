from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, UserRole
from fundraisers.models import FundraiserCampaign
from orders.models import Order, OrderItem, OrderStatus
from organizations.models import Organization
from products.models import Product, ProductCategory, SKU
from sellers.models import SellerStore
from teams.models import Team, TeamMembership, TeamMemberRole

from .models import LeaderboardScope, LeaderboardSettings, LeaderboardSnapshot
from .services import LeaderboardService

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(username, role_key=None):
	u = User.objects.create_user(username=username, password="pw", email=f"{username}@t.com")
	if role_key:
		r, _ = Role.objects.get_or_create(key=role_key)
		u.roles.add(r)
	return u


def _org(name="Org"):
	mgr = _user(f"mgr_{name[:4]}")
	return Organization.objects.create(name=name, manager=mgr)


def _campaign(org, name="Camp", status="active"):
	today = date.today()
	admin = _user(f"ca_{name[:4]}")
	return FundraiserCampaign.objects.create(
		organization=org, campaign_name=name,
		slug=f"camp-{name.lower().replace(' ', '-')}-{org.pk}",
		start_date=today - timedelta(days=1), end_date=today + timedelta(days=30),
		goal_amount=Decimal("1000.00"), created_by=admin, is_active=True, status=status,
	)


def _team(org, captain, campaign=None, name="Team"):
	return Team.objects.create(
		organization=org, captain=captain, name=name,
		slug=f"team-{name.lower().replace(' ', '-')}-{captain.pk}",
		campaign=campaign, is_active=True, team_goal=Decimal("500.00"),
	)


def _store(seller, team=None, campaign=None, slug=None, goal=Decimal("200.00")):
	slug = slug or f"store-{seller.username}"
	return SellerStore.objects.create(
		seller=seller, team=team, campaign=campaign,
		slug=slug, display_name=f"{seller.username} Store",
		seller_goal=goal, is_active=True,
	)


def _category():
	cat, _ = ProductCategory.objects.get_or_create(key="popcorn", defaults={"name": "Popcorn"})
	return cat


def _sku():
	cat = _category()
	p, _ = Product.objects.get_or_create(
		slug="test-pop", defaults={"name": "Test Pop", "category": cat, "flavor": "plain"}
	)
	sku, _ = SKU.objects.get_or_create(
		sku_code="SKU-TEST",
		defaults={"product": p, "size": "small", "retail_price": Decimal("10.00"),
				  "cost_price": Decimal("5.00"), "inventory_quantity": 100},
	)
	return sku


def _order(customer, campaign=None, team=None, store=None, total=1000, status=OrderStatus.PAID):
	o = Order.objects.create(
		customer=customer, fundraiser_campaign=campaign, team=team,
		seller=store, status=status,
		total_cents=total, subtotal_cents=total,
	)
	return o


# ---------------------------------------------------------------------------
# Service: live queries
# ---------------------------------------------------------------------------

class TopSellersInCampaignTest(TestCase):
	def setUp(self):
		self.org = _org("SellersOrg")
		self.cap = _user("cap1")
		self.campaign = _campaign(self.org)
		self.team = _team(self.org, self.cap, self.campaign)
		self.s1 = _user("s1", UserRole.SELLER)
		self.s2 = _user("s2", UserRole.SELLER)
		self.store1 = _store(self.s1, self.team, self.campaign, slug="st1", goal=Decimal("100.00"))
		self.store2 = _store(self.s2, self.team, self.campaign, slug="st2", goal=Decimal("200.00"))
		customer = _user("buyer1")
		_order(customer, self.campaign, self.team, self.store1, total=5000)
		_order(customer, self.campaign, self.team, self.store2, total=2000)

	def test_ranked_by_sales(self):
		rows = LeaderboardService.top_sellers_in_campaign(self.campaign)
		self.assertEqual(rows[0]["seller_store_id"], self.store1.pk)
		self.assertEqual(rows[0]["rank"], 1)
		self.assertEqual(rows[1]["rank"], 2)

	def test_excludes_cancelled_orders(self):
		customer = _user("buyer2")
		_order(customer, self.campaign, self.team, self.store2, total=99999, status=OrderStatus.CANCELLED)
		rows = LeaderboardService.top_sellers_in_campaign(self.campaign)
		# store1 should still be on top
		self.assertEqual(rows[0]["seller_store_id"], self.store1.pk)

	def test_goal_progress_capped_at_100(self):
		# store1 goal = $100 (10_000 cents), paid = $50 → 50 %
		rows = LeaderboardService.top_sellers_in_campaign(self.campaign)
		store1_row = next(r for r in rows if r["seller_store_id"] == self.store1.pk)
		self.assertLessEqual(store1_row["goal_progress_percent"], 100)


class TopTeamsInCampaignTest(TestCase):
	def setUp(self):
		self.org = _org("TeamsOrg")
		self.cap_a = _user("cap_a")
		self.cap_b = _user("cap_b")
		self.campaign = _campaign(self.org)
		self.team_a = _team(self.org, self.cap_a, self.campaign, "Alpha")
		self.team_b = _team(self.org, self.cap_b, self.campaign, "Beta")
		customer = _user("buyer_t")
		_order(customer, self.campaign, self.team_a, total=8000)
		_order(customer, self.campaign, self.team_b, total=3000)

	def test_ranked_by_sales(self):
		rows = LeaderboardService.top_teams_in_campaign(self.campaign)
		self.assertEqual(rows[0]["team_id"], self.team_a.pk)

	def test_excludes_draft_orders(self):
		customer = _user("buyer_t2")
		_order(customer, self.campaign, self.team_b, total=99999, status=OrderStatus.DRAFT)
		rows = LeaderboardService.top_teams_in_campaign(self.campaign)
		self.assertEqual(rows[0]["team_id"], self.team_a.pk)


class TopSellersInTeamTest(TestCase):
	def setUp(self):
		self.org = _org("TeamSellOrg")
		self.cap = _user("cap_ts")
		self.campaign = _campaign(self.org)
		self.team = _team(self.org, self.cap, self.campaign)
		self.s1 = _user("ts1", UserRole.SELLER)
		self.s2 = _user("ts2", UserRole.SELLER)
		self.store1 = _store(self.s1, self.team, self.campaign, slug="tst1")
		self.store2 = _store(self.s2, self.team, self.campaign, slug="tst2")
		customer = _user("buyer_ts")
		_order(customer, self.campaign, self.team, self.store1, total=4000)
		_order(customer, self.campaign, self.team, self.store2, total=1500)

	def test_ranked_within_team(self):
		rows = LeaderboardService.top_sellers_in_team(self.team)
		self.assertEqual(rows[0]["seller_store_id"], self.store1.pk)

	def test_full_name_included(self):
		rows = LeaderboardService.top_sellers_in_team(self.team)
		self.assertIn("full_name", rows[0])


class TopCampaignsTest(TestCase):
	def setUp(self):
		self.org = _org("MultiCampOrg")
		self.cap = _user("cap_mc")
		self.c1 = _campaign(self.org, "Big Campaign")
		self.c2 = _campaign(self.org, "Small Campaign")
		customer = _user("buyer_mc")
		_order(customer, self.c1, total=20000)
		_order(customer, self.c2, total=5000)

	def test_ranked_all_campaigns(self):
		rows = LeaderboardService.top_campaigns()
		ids = [r["campaign_id"] for r in rows]
		self.assertIn(self.c1.pk, ids)
		# c1 must outrank c2
		self.assertLess(
			next(r["rank"] for r in rows if r["campaign_id"] == self.c1.pk),
			next(r["rank"] for r in rows if r["campaign_id"] == self.c2.pk),
		)


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------

class SnapshotRefreshTest(TestCase):
	def setUp(self):
		self.org = _org("SnapOrg")
		self.cap = _user("cap_sn")
		self.campaign = _campaign(self.org)
		self.team = _team(self.org, self.cap, self.campaign)
		self.s1 = _user("sn1", UserRole.SELLER)
		self.store1 = _store(self.s1, self.team, self.campaign, slug="snst1")
		customer = _user("buyer_sn")
		_order(customer, self.campaign, self.team, self.store1, total=3000)

	def test_refresh_campaign_creates_snapshots(self):
		LeaderboardService.refresh_campaign_snapshots(self.campaign)
		self.assertTrue(
			LeaderboardSnapshot.objects.filter(
				scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=self.campaign
			).exists()
		)

	def test_refresh_team_creates_snapshots(self):
		LeaderboardService.refresh_team_snapshots(self.team)
		self.assertTrue(
			LeaderboardSnapshot.objects.filter(
				scope=LeaderboardScope.TEAM_SELLERS, team=self.team
			).exists()
		)

	def test_refresh_replaces_stale_rows(self):
		LeaderboardService.refresh_campaign_snapshots(self.campaign)
		count_before = LeaderboardSnapshot.objects.filter(
			scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=self.campaign
		).count()
		# Add more data and refresh again
		s2 = _user("sn2", UserRole.SELLER)
		store2 = _store(s2, self.team, self.campaign, slug="snst2")
		customer2 = _user("buyer_sn2")
		_order(customer2, self.campaign, self.team, store2, total=9000)
		LeaderboardService.refresh_campaign_snapshots(self.campaign)
		count_after = LeaderboardSnapshot.objects.filter(
			scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=self.campaign
		).count()
		self.assertEqual(count_after, 2)
		# store2 should now be rank 1
		top = LeaderboardSnapshot.objects.filter(
			scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=self.campaign
		).order_by("rank").first()
		self.assertEqual(top.seller_store_id, store2.pk)


# ---------------------------------------------------------------------------
# Signal: snapshot auto-refresh on order save
# ---------------------------------------------------------------------------

class SignalSnapshotTest(TestCase):
	def setUp(self):
		self.org = _org("SigOrg")
		self.cap = _user("cap_sig")
		self.campaign = _campaign(self.org)
		self.team = _team(self.org, self.cap, self.campaign)
		self.s1 = _user("sig1", UserRole.SELLER)
		self.store1 = _store(self.s1, self.team, self.campaign, slug="sigst1")
		self.customer = _user("buyer_sig")

	def test_paid_order_triggers_snapshot(self):
		_order(self.customer, self.campaign, self.team, self.store1, total=1000, status=OrderStatus.PAID)
		self.assertTrue(
			LeaderboardSnapshot.objects.filter(
				scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=self.campaign
			).exists()
		)

	def test_draft_order_does_not_trigger_snapshot(self):
		_order(self.customer, self.campaign, self.team, self.store1, total=1000, status=OrderStatus.DRAFT)
		self.assertFalse(
			LeaderboardSnapshot.objects.filter(
				scope=LeaderboardScope.CAMPAIGN_SELLERS, campaign=self.campaign
			).exists()
		)


# ---------------------------------------------------------------------------
# Leaderboard settings
# ---------------------------------------------------------------------------

class LeaderboardSettingsTest(TestCase):
	def setUp(self):
		self.org = _org("SettOrg")
		self.campaign = _campaign(self.org)

	def test_default_settings_visible(self):
		lb = LeaderboardService.get_settings(self.campaign)
		self.assertTrue(lb.public_sellers_visible)
		self.assertTrue(lb.public_teams_visible)

	def test_can_hide_public_leaderboard(self):
		lb = LeaderboardService.get_settings(self.campaign)
		lb.public_sellers_visible = False
		lb.save()
		lb_fresh = LeaderboardSettings.objects.get(campaign=self.campaign)
		self.assertFalse(lb_fresh.public_sellers_visible)


# ---------------------------------------------------------------------------
# View security
# ---------------------------------------------------------------------------

class LeaderboardViewSecurityTest(TestCase):
	def setUp(self):
		self.org = _org("ViewSecOrg")
		self.campaign = _campaign(self.org, "ViewSecCamp")
		self.cap = _user("cap_vs")
		self.team = _team(self.org, self.cap, self.campaign, "ViewSecTeam")
		self.anon_client = self.client
		self.staff = _user("staff_vs")
		self.staff.is_staff = True
		self.staff.save()
		self.plain = _user("plain_vs")

	def test_public_campaign_leaderboard_no_login(self):
		url = reverse("leaderboards:campaign", kwargs={"campaign_slug": self.campaign.slug})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)

	def test_team_leaderboard_requires_login(self):
		url = reverse("leaderboards:team", kwargs={"team_slug": self.team.slug})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 302)

	def test_team_leaderboard_accessible_when_logged_in(self):
		self.client.force_login(self.plain)
		url = reverse("leaderboards:team", kwargs={"team_slug": self.team.slug})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)

	def test_all_campaigns_blocks_non_staff(self):
		self.client.force_login(self.plain)
		url = reverse("leaderboards:all-campaigns")
		response = self.client.get(url)
		self.assertEqual(response.status_code, 403)

	def test_all_campaigns_accessible_to_staff(self):
		self.client.force_login(self.staff)
		url = reverse("leaderboards:all-campaigns")
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)

	def test_settings_blocks_non_staff(self):
		self.client.force_login(self.plain)
		url = reverse("leaderboards:settings", kwargs={"campaign_slug": self.campaign.slug})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 403)

	def test_settings_accessible_to_staff(self):
		self.client.force_login(self.staff)
		url = reverse("leaderboards:settings", kwargs={"campaign_slug": self.campaign.slug})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)

	def test_hidden_leaderboard_not_shown_to_public(self):
		"""When public_sellers_visible=False, sellers table is hidden for anonymous users."""
		lb = LeaderboardService.get_settings(self.campaign)
		lb.public_sellers_visible = False
		lb.public_teams_visible = False
		lb.save()
		url = reverse("leaderboards:campaign", kwargs={"campaign_slug": self.campaign.slug})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, "Top Sellers")
		self.assertNotContains(response, "Top Teams")

	def test_hidden_leaderboard_still_shown_to_staff(self):
		lb = LeaderboardService.get_settings(self.campaign)
		lb.public_sellers_visible = False
		lb.public_teams_visible = False
		lb.save()
		self.client.force_login(self.staff)
		url = reverse("leaderboards:campaign", kwargs={"campaign_slug": self.campaign.slug})
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)
		# Staff bypass: the sections should be visible even if hidden from public
		self.assertContains(response, "Top Sellers")
