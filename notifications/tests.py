from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notifications.center import NotificationCenterService
from notifications.models import Notification, NotificationType


User = get_user_model()


class NotificationCenterSecurityTests(TestCase):
    def setUp(self):
        self.u1 = User.objects.create_user(username="u1", password="pw", email="u1@example.com")
        self.u2 = User.objects.create_user(username="u2", password="pw", email="u2@example.com")
        NotificationCenterService.notify(
            user=self.u1,
            notification_type=NotificationType.DELIVERY_UPDATE,
            title="Test",
            message="Hello",
        )

    def test_user_can_only_see_own_inbox(self):
        self.client.force_login(self.u1)
        resp = self.client.get(reverse("notifications:inbox"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test")

        self.client.force_login(self.u2)
        resp2 = self.client.get(reverse("notifications:inbox"))
        self.assertEqual(resp2.status_code, 200)
        self.assertNotContains(resp2, "Test")

    def test_mark_read_blocks_other_users(self):
        n = Notification.objects.filter(user=self.u1).first()
        self.client.force_login(self.u2)
        resp = self.client.post(reverse("notifications:inbox-mark-read", args=[n.id]))
        self.assertEqual(resp.status_code, 404)

# Create your tests here.
