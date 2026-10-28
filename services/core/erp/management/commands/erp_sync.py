from django.core.management.base import BaseCommand, CommandError

from erp.models import ErpConnection
from erp.sync import sync_connection


class Command(BaseCommand):
    help = "Sync ERP master data now for one org (or all), e.g. after seeding Odoo."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--org", help="Organization id (default: every connected org)")
        parser.add_argument("--full", action="store_true", help="Re-read everything")

    def handle(self, *args, org: str | None, full: bool, **options) -> None:
        connections = ErpConnection.objects.select_related("org")
        if org:
            connections = connections.filter(org_id=org)
        if not connections.exists():
            raise CommandError("No ERP connection found. Run seed_demo or connect one in Settings.")
        for connection in connections:
            run = sync_connection(connection, full=full)
            counts = ", ".join(f"{k} {v}" for k, v in run.counts.items())
            line = f"{connection.org.name}: {run.status} ({counts or run.error})"
            self.stdout.write(
                self.style.SUCCESS(line) if run.status == "ok" else self.style.ERROR(line)
            )
