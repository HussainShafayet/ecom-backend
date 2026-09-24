from .models import Product


def sync_primary_category(product):
    """Keep `primary_category` consistent with `categories`: it is always one of them, and a product that has
    categories always has a primary one. Call it after the categories were saved (admin `save_related`, seed)."""
    if product.primary_category_id:
        product.categories.add(product.primary_category_id)
        return
    first = product.categories.order_by("name", "id").first()
    if first is not None:
        Product.objects.filter(pk=product.pk).update(primary_category=first)
        product.primary_category = first
