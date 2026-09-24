import uuid

from django.utils.text import slugify


def unique_slug(model, value, *, instance=None, field="slug", fallback="item"):
    """A URL-safe slug for `value` that no other row of `model` uses: `red-shirt`, `red-shirt-2`, ...

    Slugs are plain ASCII on purpose (they end up in `/products/detail/<slug>/`); a name that has no ASCII
    letters at all (e.g. only Bengali) falls back to `fallback` plus a random suffix. `instance` is the row
    being saved, so it never collides with itself.
    """
    max_length = model._meta.get_field(field).max_length
    base = slugify(value or "")[: max_length - 6].strip("-")
    if not base:
        base = f"{fallback}-{uuid.uuid4().hex[:6]}"

    others = model._default_manager.all()
    if instance is not None and instance.pk is not None:
        others = others.exclude(pk=instance.pk)

    candidate, counter = base, 1
    while others.filter(**{field: candidate}).exists():
        counter += 1
        suffix = f"-{counter}"
        candidate = f"{base[: max_length - len(suffix)]}{suffix}"
    return candidate
