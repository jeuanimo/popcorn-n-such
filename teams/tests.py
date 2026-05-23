import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from fundraisers.models import FundraiserCampaign, FundraiserCampaignStatus
from orders.models import Order, OrderStatus
from organizations.models import Organization
from sellers.models import SellerLink

from .models import Team, TeamMembership, TeamMemberRole, TeamReminderLog
from .services import TeamService

User = get_user_model()
TEST_LOGIN_SECRET = "test-secret-teams"


def _create_user(username, **kwargs):
    return User.objects.create_user(username=username, password=TEST_LOGIN_SECRET, email=f"{username}@example.com", **kwargs)


def _create_org(manager):
    return Organization.objects.create(name=f"{manager.username}_org", manager=manager)


def _create_campaign(org, creator):
    today = timezone.now().date()
    return FundraiserCampaign.objects.create(
        organization=org,
        campaign_name="Test Campaign",
        slug=f"test-campaign-{org.pk}",
        start_date=today,
        end_date=today + datetime.timedelta(days=30),
        goal_amount="1000.00",
        status=FundraiserCampaignStatus.ACTIVE,
        is_active=True,
        created_by=creator,
        profit_percentage="30",
    )


def _create_team(org, captain, campaign=None):
    team = Team.objects.create(
        name="Alpha Team",
        slug=f"alpha-team-{captain.pk}",
        captain=captain,
        organization=org,
        campaign=campaign,
        team_goal="500.00",
        invite_code=f"invitecode{captain.pk:08d}",
        is_active=True,
    )
    # Ensure captain membership exists
    TeamMembership.objects.get_or_create(
        team=team,
        member=captain,
        defaults={"role": TeamMemberRole.CAPTAIN, "is_active": True},
    )
    return team


class TeamModelTest(TestCase):
    def setUp(self):
        self.manager = _create_user("manager1")
        self.org = _create_org(self.manager)
        self.captain = _create_user("captain1")
        self.campaign = _create_campaign(self.org, self.manager)
        self.team = _create_team(self.org, self.captain, self.campaign)

    def test_team_str(self):
        self.assertEqual(str(self.team), "Alpha Team")

    def test_team_membership_str(self):
        m = TeamMembership.objects.get(team=self.team, member=self.captain)
        self.assertIn("captain1", str(m))

    def test_unique_invite_code(self):
        with self.assertRaises(Exception):
            Team.objects.create(
                name="Beta Team",
                slug="beta-team",
                captain=self.captain,
                organization=self.org,
                invite_code=self.team.invite_code,
            )

    def test_unique_slug(self):
        with self.assertRaises(Exception):
            Team.objects.create(
                name="Dupe",
                slug=self.team.slug,
                captain=self.captain,
                organization=self.org,
                invite_code="uniquecode0001234",
            )

    def test_campaign_org_mismatch_raises_validation_error(self):
        other_manager = _create_user("manager2")
        other_org = _create_org(other_manager)
        team = Team(
            name="Mismatch Team",
            slug="mismatch-team",
            captain=self.captain,
            organization=other_org,
            campaign=self.campaign,  # campaign belongs to self.org, not other_org
        )
        with self.assertRaises(ValidationError):
            team.full_clean()


class TeamServiceJoinTest(TestCase):
    def setUp(self):
        self.manager = _create_user("mgr")
        self.org = _create_org(self.manager)
        self.captain = _create_user("capt")
        self.campaign = _create_campaign(self.org, self.manager)
        self.team = _create_team(self.org, self.captain, self.campaign)

    def test_join_valid_code(self):
        member = _create_user("newmember")
        membership = TeamService.join_team_by_code(user=member, invite_code=self.team.invite_code)
        self.assertEqual(membership.team, self.team)
        self.assertEqual(membership.role, TeamMemberRole.MEMBER)
        self.assertTrue(membership.is_active)

    def test_join_invalid_code_raises(self):
        member = _create_user("badmember")
        with self.assertRaises(ValidationError):
            TeamService.join_team_by_code(user=member, invite_code="invalidcode0000")

    def test_join_already_member_raises(self):
        member = _create_user("dup_member")
        TeamService.join_team_by_code(user=member, invite_code=self.team.invite_code)
        with self.assertRaises(ValidationError):
            TeamService.join_team_by_code(user=member, invite_code=self.team.invite_code)

    def test_join_inactive_team_raises(self):
        self.team.is_active = False
        self.team.save()
        member = _create_user("inactive_member")
        with self.assertRaises(ValidationError):
            TeamService.join_team_by_code(user=member, invite_code=self.team.invite_code)


class TeamServiceMetricsTest(TestCase):
    def setUp(self):
        self.manager = _create_user("mgr_metrics")
        self.org = _create_org(self.manager)
        self.captain = _create_user("capt_metrics")
        self.campaign = _create_campaign(self.org, self.manager)
        self.team = _create_team(self.org, self.captain, self.campaign)

    def test_metrics_empty_team(self):
        metrics = TeamService.dashboard_metrics(team=self.team)
        self.assertEqual(metrics["total_sales_cents"], 0)
        self.assertEqual(metrics["total_orders"], 0)
        self.assertEqual(metrics["goal_progress_percent"], 0)

    def test_metrics_with_orders(self):
        customer = _create_user("buyer")
        Order.objects.create(
            customer=customer,
            fundraiser_campaign=self.campaign,
            team=self.team,
            status=OrderStatus.PAID,
            subtotal_cents=5000,
            total_cents=5000,
        )
        metrics = TeamService.dashboard_metrics(team=self.team)
        self.assertEqual(metrics["total_sales_cents"], 5000)
        self.assertEqual(metrics["total_orders"], 1)
        # team_goal = 500 → goal_cents = 50000; 5000/50000 = 10%
        self.assertEqual(metrics["goal_progress_percent"], 10)

    def test_metrics_goal_progress_capped_at_100(self):
        customer = _create_user("buyer2")
        Order.objects.create(
            customer=customer,
            fundraiser_campaign=self.campaign,
            team=self.team,
            status=OrderStatus.PAID,
            total_cents=999999,
        )
        metrics = TeamService.dashboard_metrics(team=self.team)
        self.assertEqual(metrics["goal_progress_percent"], 100)


class TeamServiceReminderTest(TestCase):
    def setUp(self):
        self.manager = _create_user("mgr_rem")
        self.org = _create_org(self.manager)
        self.captain = _create_user("capt_rem")
        self.campaign = _create_campaign(self.org, self.manager)
        self.team = _create_team(self.org, self.captain, self.campaign)
        self.member = _create_user("member_rem")
        TeamMembership.objects.create(team=self.team, member=self.member, role=TeamMemberRole.MEMBER, is_active=True)

    def test_non_captain_cannot_send_reminder(self):
        other = _create_user("outsider")
        with self.assertRaises(PermissionDenied):
            TeamService.send_member_reminders(
                team=self.team, captain=other, subject="hey", message="pay up"
            )

    def test_reminder_logged(self):
        count = TeamService.send_member_reminders(
            team=self.team,
            captain=self.captain,
            subject="Reminder",
            message="Please sell more popcorn!",
        )
        self.assertEqual(count, 1)
        self.assertEqual(TeamReminderLog.objects.filter(team=self.team).count(), 1)


class TeamServiceMoveSellerTest(TestCase):
    def setUp(self):
        self.manager = _create_user("mgr_move")
        self.org = _create_org(self.manager)
        self.captain_a = _create_user("capt_a")
        self.captain_b = _create_user("capt_b")
        self.campaign = _create_campaign(self.org, self.manager)
        self.team_a = _create_team(self.org, self.captain_a, self.campaign)
        self.team_b = _create_team(self.org, self.captain_b, self.campaign)
        self.team_b.slug = f"beta-team-{self.captain_b.pk}"
        self.team_b.name = "Beta Team"
        self.team_b.save()
        self.seller_user = _create_user("seller_user")
        self.seller_link = SellerLink.objects.create(
            user=self.seller_user,
            title="Seller A",
            slug="seller-a",
            is_active=True,
        )
        self.campaign.sellers.add(self.seller_link)
        self.staff = _create_user("staff_user")
        self.staff.is_staff = True
        self.staff.save()

    def test_non_staff_cannot_move(self):
        with self.assertRaises(PermissionDenied):
            TeamService.move_seller(
                seller_link=self.seller_link,
                from_team=self.team_a,
                to_team=self.team_b,
                staff_user=self.captain_a,
            )

    def test_move_requires_same_campaign(self):
        other_campaign_team = Team.objects.create(
            name="Other Team",
            slug="other-team",
            captain=self.captain_b,
            organization=self.org,
            campaign=None,
            invite_code="otherinvite0001",
            is_active=True,
        )
        with self.assertRaises(ValidationError):
            TeamService.move_seller(
                seller_link=self.seller_link,
                from_team=self.team_a,
                to_team=other_campaign_team,
                staff_user=self.staff,
            )

    def test_move_seller_updates_draft_orders(self):
        from sellers.models import SellerStore

        customer = _create_user("buyer_move")
        store = SellerStore.objects.create(
            seller=self.seller_user,
            team=self.team_a,
            campaign=self.campaign,
            slug=f"store-{self.seller_user.username}",
            display_name="Seller A Store",
            seller_goal="0.00",
            is_active=True,
        )
        order = Order.objects.create(
            customer=customer,
            fundraiser_campaign=self.campaign,
            team=self.team_a,
            seller=store,
            status=OrderStatus.DRAFT,
            total_cents=2000,
        )
        TeamService.move_seller(
            seller_link=self.seller_link,
            from_team=self.team_a,
            to_team=self.team_b,
            staff_user=self.staff,
        )
        order.refresh_from_db()
        self.assertEqual(order.team, self.team_b)


class TeamDashboardViewTests(TestCase):
    def setUp(self):
        self.manager = _create_user("mgr_dash")
        self.org = _create_org(self.manager)
        self.captain = _create_user("capt_dash")
        self.campaign = _create_campaign(self.org, self.manager)
        self.team = _create_team(self.org, self.captain, self.campaign)
        self.member = _create_user("member_dash")
        TeamMembership.objects.create(
            team=self.team,
            member=self.member,
            role=TeamMemberRole.MEMBER,
            is_active=True,
        )

    def test_member_sees_fundraising_shop_link(self):
        self.client.login(username="member_dash", password=TEST_LOGIN_SECRET)
        response = self.client.get(reverse("teams:dashboard", args=[self.team.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fundraising Shop Link")
        self.assertContains(response, reverse("fundraisers:public-campaign-detail", args=[self.campaign.slug]))


class TeamViewSecurityTest(TestCase):
    def setUp(self):
        self.manager = _create_user("mgr_view")
        self.org = _create_org(self.manager)
        self.captain = _create_user("capt_view")
        self.campaign = _create_campaign(self.org, self.manager)
        self.team = _create_team(self.org, self.captain, self.campaign)
        self.outsider = _create_user("outsider_view")

    def test_dashboard_blocks_non_member(self):
        self.client.force_login(self.outsider)
        response = self.client.get(f"/teams/{self.team.slug}/dashboard/")
        self.assertEqual(response.status_code, 403)

    def test_dashboard_accessible_to_member(self):
        self.client.force_login(self.captain)
        response = self.client.get(f"/teams/{self.team.slug}/dashboard/")
        self.assertEqual(response.status_code, 200)

    def test_members_blocks_non_captain(self):
        member = _create_user("plain_member")
        TeamMembership.objects.create(team=self.team, member=member, role=TeamMemberRole.MEMBER, is_active=True)
        self.client.force_login(member)
        response = self.client.get(f"/teams/{self.team.slug}/members/")
        self.assertEqual(response.status_code, 403)

    def test_members_accessible_to_captain(self):
        self.client.force_login(self.captain)
        response = self.client.get(f"/teams/{self.team.slug}/members/")
        self.assertEqual(response.status_code, 200)

    def test_send_reminder_blocks_non_captain(self):
        member = _create_user("remind_member")
        TeamMembership.objects.create(team=self.team, member=member, role=TeamMemberRole.MEMBER, is_active=True)
        self.client.force_login(member)
        response = self.client.get(f"/teams/{self.team.slug}/remind/")
        self.assertEqual(response.status_code, 403)

    def test_staff_list_blocks_non_staff(self):
        self.client.force_login(self.outsider)
        response = self.client.get("/teams/staff/teams/")
        self.assertEqual(response.status_code, 403)

    def test_staff_list_accessible_to_staff(self):
        self.staff = _create_user("staff_view")
        self.staff.is_staff = True
        self.staff.save()
        self.client.force_login(self.staff)
        response = self.client.get("/teams/staff/teams/")
        self.assertEqual(response.status_code, 200)

    def test_public_team_page_no_login(self):
        response = self.client.get(f"/teams/{self.team.slug}/")
        self.assertEqual(response.status_code, 200)
