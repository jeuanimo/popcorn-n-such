from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, UserRole
from organizations.models import Organization

User = get_user_model()


class DashboardAccessControlTests(TestCase):
    def setUp(self):
        self.staff_role, _ = Role.objects.get_or_create(key=UserRole.STAFF)
        self.admin_role, _ = Role.objects.get_or_create(key=UserRole.ADMIN)
        self.org_manager_role, _ = Role.objects.get_or_create(key=UserRole.ORGANIZATION_MANAGER)

        self.staff = User.objects.create_user(username="staff_d", password="pw", is_staff=True)
        self.staff.roles.add(self.staff_role)

        self.admin = User.objects.create_user(username="admin_d", password="pw")
        self.admin.roles.add(self.admin_role)

        self.manager = User.objects.create_user(username="mgr_d", password="pw")
        self.manager.roles.add(self.org_manager_role)
        Organization.objects.create(name="Org", manager=self.manager)

        self.customer = User.objects.create_user(username="cust_d", password="pw")

    def test_owner_dashboard_requires_admin(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("dashboards:owner"))
        self.assertEqual(resp.status_code, 403)

        self.client.force_login(self.admin)
        resp2 = self.client.get(reverse("dashboards:owner"))
        self.assertEqual(resp2.status_code, 200)

    def test_fulfillment_dashboard_requires_staff(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("dashboards:fulfillment"))
        self.assertEqual(resp.status_code, 403)

        self.client.force_login(self.staff)
        resp2 = self.client.get(reverse("dashboards:fulfillment"))
        self.assertEqual(resp2.status_code, 200)

    def test_org_dashboard_requires_manager_or_staff(self):
        self.client.force_login(self.customer)
        resp = self.client.get(reverse("dashboards:organization"))
        self.assertEqual(resp.status_code, 403)

        self.client.force_login(self.manager)
        resp2 = self.client.get(reverse("dashboards:organization"))
        self.assertEqual(resp2.status_code, 200)

