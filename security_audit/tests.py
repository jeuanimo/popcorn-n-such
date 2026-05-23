from django.contrib.auth import get_user_model
from django.test import TestCase

from security_audit.models import AuditAction, AuditLog
from security_audit.utils import log_audit_event

User = get_user_model()
TEST_LOGIN_SECRET = "test-secret-audit"


class AuditLogTests(TestCase):
    def test_log_audit_event_creates_row(self):
        u = User.objects.create_user(username="auditor", password=TEST_LOGIN_SECRET)
        event = log_audit_event(action=AuditAction.SECURITY_EVENT, message="Test event", actor=u, metadata={"x": 1})
        self.assertTrue(AuditLog.objects.filter(id=event.id).exists())
        self.assertEqual(event.action, AuditAction.SECURITY_EVENT)
        self.assertEqual(event.metadata.get("x"), 1)
