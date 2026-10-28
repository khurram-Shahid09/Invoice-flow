"""Demo workspace for local development and the demo video (docs/14-deployment-ops.md).

Creates "Indus Retail (Pvt) Ltd" with one user per role and connects its ERP: the local Odoo
when ODOO_API_KEY is set (infra/odoo/seed.py writes it), otherwise the in-memory fake ERP
with the same data. Then syncs it. Safe to run again: users get their password and roles
reset, and the connection is updated.
"""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Membership, Organization, Role, User
from audit.service import record
from erp.models import ErpConnection
from erp.sync import sync_connection

ORG_NAME = "Indus Retail (Pvt) Ltd"
DEMO_USERS = [
    # email, name, roles, approval limit (PKR; None = no limit)
    ("clerk@indus-retail.test", "Ayesha Khan", [Role.CLERK], None),
    ("approver@indus-retail.test", "Sana Ali", [Role.APPROVER], Decimal("500000")),
    ("controller@indus-retail.test", "Bilal Ahmed", [Role.APPROVER, Role.CONTROLLER], None),
    ("admin@indus-retail.test", "Hamza Raza", [Role.ADMIN], None),
]


class Command(BaseCommand):
    help = "Create the demo workspace and one user per role (password: DEMO_PASSWORD)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the workspace's invoices first (fresh demo)",
        )

    def handle(self, *args, reset: bool = False, **options) -> None:
        password = settings.DEMO_PASSWORD
        if len(password) < 10:
            raise CommandError("Set DEMO_PASSWORD (10+ characters) in .env first.")

        with transaction.atomic():
            org, created = Organization.objects.get_or_create(name=ORG_NAME)
            if created:
                record("org.created", org=org, entity=org, actor="system:seed_demo")
            for email, name, roles, limit in DEMO_USERS:
                user = User.objects.filter(email=email).first() or User(email=email)
                user.name = name
                user.set_password(password)
                user.save()
                Membership.objects.update_or_create(
                    org=org, user=user, defaults={"roles": sorted(roles), "approval_limit": limit}
                )

        if reset:
            from invoices.models import Document

            deleted, _ = Document.objects.for_org(org).delete()  # invoices and pages go with them
            self.stdout.write(f"Reset: removed {deleted} documents, invoices and pages.")
        connection = self._connect_erp(org)
        run = sync_connection(connection, full=True)
        self.stdout.write(f"Workspace: {org.name} ({org.id})")
        detail = ", ".join(f"{k} {v}" for k, v in run.counts.items()) or run.error
        self.stdout.write(f"ERP: {connection.kind}, sync {run.status} ({detail})")
        for email, _, roles, _ in DEMO_USERS:
            self.stdout.write(f"  {email:32s} {', '.join(roles)}")
        self.stdout.write(self.style.SUCCESS("Password: the DEMO_PASSWORD value in .env"))

    @staticmethod
    def _connect_erp(org: Organization) -> ErpConnection:
        connection = ErpConnection.objects.filter(org=org).first() or ErpConnection(org=org)
        if settings.ODOO_API_KEY:
            connection.kind = ErpConnection.Kind.ODOO
            connection.url, connection.database = settings.ODOO_URL, settings.ODOO_DB
            connection.username = settings.ODOO_API_USER
            connection.set_secret(settings.ODOO_API_KEY)
        else:
            connection.kind = ErpConnection.Kind.FAKE
            connection.url = connection.database = connection.username = ""
            connection.secret_enc = ""
        connection.save()
        return connection
