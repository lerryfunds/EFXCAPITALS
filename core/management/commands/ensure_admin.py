from django.core.management.base import BaseCommand, CommandError
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
        existing_user = User.objects.filter(username=username).first()

        if not password and (
            existing_user is None or not existing_user.has_usable_password()
        ):
            raise CommandError(
                f'A password is required to create or repair admin "{username}". '
                "Set DJANGO_ADMIN_PASSWORD or pass --password."
            )

        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        if not user.is_staff or not user.is_superuser or not user.is_active:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True

        if password:
            user.set_password(password)

        user.save()
        self.stdout.write(
            self.style.SUCCESS(
                'Admin "%s" is ready%s.'
                % (username, " (password set)" if password else "")
            )
        )