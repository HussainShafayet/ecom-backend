"""What `/site/…` answers. Reading never writes: a shop that has not saved its settings yet answers with the defaults."""
from apps.core.utils import absolute_url

from .models import FaqItem, NewsletterSubscriber, SiteSettings, SocialLink, StaticPage


def footer_pages():
    """`{company: [{slug, title}], service: [...], legal: [...]}`: the published pages an admin put in the footer."""
    groups = {group: [] for group in StaticPage.FooterGroup.values if group}
    rows = StaticPage.objects.filter(is_published=True).exclude(footer_group="").values("slug", "title", "footer_group")
    for row in rows:
        groups[row["footer_group"]].append({"slug": row["slug"], "title": row["title"]})
    return groups


def site_payload(request=None):
    site = SiteSettings.current()
    links = SocialLink.objects.filter(site=site, is_active=True) if site.pk else SocialLink.objects.none()
    text = site.announcement_text.strip()
    announcement = (
        {"text": text, "link": site.announcement_link or None} if site.announcement_enabled and text else None
    )
    return {
        "name": site.site_name,
        "tagline": site.tagline,
        "logo": absolute_url(request, site.logo),
        "announcement": announcement,
        "contact": {
            "email": site.contact_email,
            "phone": site.contact_phone,
            "address": site.contact_address,
            "opening_hours": site.opening_hours,
            "map_url": site.map_embed_url,
        },
        "social_links": [{"platform": link.platform, "url": link.url} for link in links],
        "footer_pages": footer_pages(),
    }


def published_page(slug):
    """`{slug, title, body, updated_at}` of a published page, or None."""
    page = StaticPage.objects.filter(slug=slug, is_published=True).first()
    if page is None:
        return None
    return {"slug": page.slug, "title": page.title, "body": page.body, "updated_at": page.updated_at}


def faq_items():
    return [
        {"category": item.category or "General", "question": item.question, "answer": item.answer}
        for item in FaqItem.objects.filter(is_active=True)
    ]


def subscribe(email):
    """Add the address, or take an unsubscribed one back. Answers the same either way: the form must not tell a
    stranger whether an address is on the list."""
    subscriber, created = NewsletterSubscriber.objects.get_or_create(email=email.strip().lower())
    if not created and not subscriber.is_active:
        subscriber.is_active = True
        subscriber.save(update_fields=["is_active"])
    return subscriber
