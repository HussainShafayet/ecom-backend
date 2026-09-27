from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.siteconfig import sample_content as sample
from apps.siteconfig.models import FaqItem, SiteSettings, SocialLink, StaticPage


class Command(BaseCommand):
    help = (
        "Fill in sample site settings (name, contact details, announcement, social links), the About / Privacy / Terms / "
        "Cookie pages and a FAQ. Anything the shop already has is left alone. Development only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even though DEBUG is off.")

    def handle(self, *args, force, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to add sample data while DEBUG is off. Pass --force if you really mean it.")
        with transaction.atomic():
            site, created = SiteSettings.objects.get_or_create(pk=1, defaults=sample.SITE)
            links = 0
            if created:  # a shop that already has settings keeps them (and its social links)
                for order, (platform, url) in enumerate(sample.SOCIAL_LINKS):
                    SocialLink.objects.create(site=site, platform=platform, url=url, order=order)
                    links += 1
            pages = sum(StaticPage.objects.get_or_create(slug=page["slug"], defaults=page)[1] for page in sample.PAGES)
            faqs = 0
            if not FaqItem.objects.exists():
                for order, (category, question, answer) in enumerate(sample.FAQ):
                    FaqItem.objects.create(category=category, question=question, answer=answer, order=order)
                    faqs += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Site seeded: settings {'created' if created else 'kept'}, {links} social link(s), "
                f"{pages} page(s), {faqs} FAQ item(s)."
            )
        )
