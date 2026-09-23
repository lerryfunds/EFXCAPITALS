from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
import os

User = get_user_model()


class Command(BaseCommand):
    help = "Ensure an admin superuser exists (reads DJANGO_ADMIN_* env vars)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="")
        parser.add_argument("--email", default="")
        parser.add_argument("--password", default="")

    @transaction.atomic
    def handle(self, *args, **options):
        username = options["username"] or os.environ.get("DJANGO_ADMIN_USERNAME", "admin")
        email = options["email"] or os.environ.get("DJANGO_ADMIN_EMAIL", "admin@efxcapitals.com")
        password = options["password"] or os.environ.get("DJANGO_ADMIN_PASSWORD", "")
        auto = bool(password)

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        if not user.is_staff or not user.is_superuser:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True

        if auto:
            user.set_password(password)
        elif not created and not user.has_usable_password():
            self.stderr.write(
                'Admin "%s" has no password. Re-run with --password or set DJANGO_ADMIN_PASSWORD.'
                % username
            )
            return

        user.save()
        self.stdout.write(
            self.style.SUCCESS(
                'Admin "%s" is ready%s.'
                % (username, " (password set)" if auto else "")
            )
        )