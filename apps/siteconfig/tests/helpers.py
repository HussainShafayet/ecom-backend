from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image

from apps.siteconfig.models import FaqItem, SiteSettings, SocialLink, StaticPage, TrustBadge


def image_file(name="logo.png", size=(64, 64)):
    buffer = BytesIO()
    Image.new("RGB", size, "blue").save(buffer, "PNG")
    return ContentFile(buffer.getvalue(), name=name)


def make_settings(**fields):
    site = SiteSettings.load()
    for name, value in fields.items():
        setattr(site, name, value)
    site.save()
    return site


def make_link(platform="facebook", url="https://www.facebook.com/shop", **kwargs):
    return SocialLink.objects.create(site=SiteSettings.load(), platform=platform, url=url, **kwargs)


def make_badge(icon="delivery", title="Free delivery", **kwargs):
    return TrustBadge.objects.create(site=SiteSettings.load(), icon=icon, title=title, **kwargs)


def make_page(slug="about-us", title="About Us", body="<p>Hello</p>", **kwargs):
    return StaticPage.objects.create(slug=slug, title=title, body=body, **kwargs)


def make_faq(question="Do you deliver?", answer="Yes.", **kwargs):
    return FaqItem.objects.create(question=question, answer=answer, **kwargs)
