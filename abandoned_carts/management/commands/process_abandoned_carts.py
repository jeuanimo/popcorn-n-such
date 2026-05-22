from django.core.management.base import BaseCommand
from django.utils import timezone

from abandoned_carts.services import AbandonedCartRecoveryService


class Command(BaseCommand):
    help = "Process abandoned carts and send reminder messages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Evaluate reminders without sending notifications or saving message records.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        counters = AbandonedCartRecoveryService.process_pending_events(now=now, dry_run=options["dry_run"])
        self.stdout.write(
            self.style.SUCCESS(
                "Abandoned cart processing complete: "
                f"events_created={counters['events_created']} "
                f"events_closed={counters['events_closed']} "
                f"email_sent={counters['email_sent']} "
                f"sms_sent={counters['sms_sent']} "
                f"messages_failed={counters['messages_failed']} "
                f"messages_skipped={counters['messages_skipped']} "
                f"recovered={counters['recovered']}"
            )
        )
