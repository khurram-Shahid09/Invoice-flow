"""Demo workspace for local development and the demo video (docs/14-deployment-ops.md).

Creates "Indus Retail (Pvt) Ltd" with one user per role. Safe to run again: existing users
keep their data and get their password and roles reset.
"""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Membership, Organization, Role, User
from audit.service import record

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

    def handle(self, *args, **options) -> None:
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

        self.stdout.write(f"Workspace: {org.name} ({org.id})")
        for email, _, roles, _ in DEMO_USERS:
            self.stdout.write(f"  {email:32s} {', '.join(roles)}")
        self.stdout.write(self.style.SUCCESS("Password: the DEMO_PASSWORD value in .env"))
