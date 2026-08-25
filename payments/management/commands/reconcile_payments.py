"""Resolve payment attempts whose outcome was never received."""

from django.core.management.base import BaseCommand

from payments.reconciliation import reconcile_pending


class Command(BaseCommand):
    help = (
        "Ask the payment processor about charges whose outcome is unknown "
        "(ambiguous). Read-only against the provider; never re-charges."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of ambiguous payments to check in this run.",
        )

    def handle(self, *args, **options):
        tally = reconcile_pending(limit=options["limit"])
        self.stdout.write(
            f"checked={tally['checked']} confirmed={tally['confirmed']} "
            f"failed={tally['failed']} still_unknown={tally['still_unknown']}"
        )
        if tally["confirmed"]:
            self.stdout.write(self.style.WARNING(
                f"{tally['confirmed']} ambiguous payment(s) WERE charged — "
                "check whether the matching orders exist."
            ))
        if tally["still_unknown"]:
            self.stdout.write(self.style.NOTICE(
                f"{tally['still_unknown']} still unresolved; they will be retried."
            ))
