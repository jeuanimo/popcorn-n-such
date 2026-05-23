from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, UserRole
from fundraisers.models import FundraiserCampaign, FundraiserCampaignStatus
from organizations.models import Organization
from teams.models import Team

User = get_user_model()
TEST_LOGIN_SECRET = "test-secret-reports"


class ReportsAccessTests(TestCase):
    def setUp(self):
        self.staff_role, _ = Role.objects.get_or_create(key=UserRole.STAFF)
        self.org_manager_role, _ = Role.objects.get_or_create(key=UserRole.ORGANIZATION_MANAGER)
        self.team_captain_role, _ = Role.objects.get_or_create(key=UserRole.TEAM_CAPTAIN)

        self.staff = User.objects.create_user(username="staff_r", password=TEST_LOGIN_SECRET, is_staff=True)
        self.staff.roles.add(self.staff_role)

        self.manager = User.objects.create_user(username="mgr_r", password=TEST_LOGIN_SECRET)
        self.manager.roles.add(self.org_manager_role)

        self.other_manager = User.objects.create_user(username="mgr_other", password=TEST_LOGIN_SECRET)
        self.other_manager.roles.add(self.org_manager_role)

        self.org = Organization.objects.create(name="School PTO", manager=self.manager)
        self.other_org = Organization.objects.create(name="Other Org", manager=self.other_manager)

        self.campaign = FundraiserCampaign.objects.create(
            organization=self.org,
            campaign_name="Drive",
            slug="drive",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=5),
            goal_amount="1000.00",
            status=FundraiserCampaignStatus.ACTIVE,
            created_by=self.manager,
            is_active=True,
        )

        self.other_campaign = FundraiserCampaign.objects.create(
            organization=self.other_org,
            campaign_name="Other Drive",
            slug="other-drive",
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=5),
            goal_amount="1000.00",
            status=FundraiserCampaignStatus.ACTIVE,
            created_by=self.other_manager,
            is_active=True,
        )

        self.captain = User.objects.create_user(username="capt_r", password=TEST_LOGIN_SECRET)
        self.captain.roles.add(self.team_captain_role)
        self.team = Team.objects.create(
            organization=self.org,
            captain=self.captain,
            campaign=self.campaign,
            name="Team A",
            slug="team-a",
            invite_code="invite0000001",
            is_active=True,
            team_goal="500.00",
        )

    def test_staff_reports_dashboard_accessible(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse("reports:dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_non_staff_reports_dashboard_forbidden(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("reports:dashboard"))
        self.assertEqual(resp.status_code, 403)

    def test_org_manager_can_access_my_campaign_report(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("reports:my-fundraiser", args=[self.campaign.slug]))
        self.assertEqual(resp.status_code, 200)

    def test_org_manager_cannot_access_other_campaign_report(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("reports:my-fundraiser", args=[self.other_campaign.slug]))
        self.assertEqual(resp.status_code, 403)

    def test_team_captain_can_access_my_team_report(self):
        self.client.force_login(self.captain)
        resp = self.client.get(reverse("reports:my-team", args=[self.team.slug]))
        self.assertEqual(resp.status_code, 200)
