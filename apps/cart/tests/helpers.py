from apps.accounts.tests.helpers import authed_client, verified_user
from apps.catalog.models import Color
from apps.catalog.tests.helpers import make_product, make_size, make_variant

CART = "/api/v1/accounts/cart/"


def stocked(name="Mug", stock=10, **product):
    """A product with no options: one variant with `stock` in stock. Returns (product, variant)."""
    item = make_product(name, **product)
    return item, make_variant(item, stock_quantity=stock)


def with_options(name="Shirt", stocks=(5, 5), **product):
    """A shirt in Red/S, Red/M ... one variant per entry of `stocks`. Returns (product, [variants])."""
    item = make_product(name, **product)
    red = Color.objects.get_or_create(name="Red", defaults={"hex_code": "#FF0000"})[0]
    variants = []
    for index, stock in enumerate(stocks):
        size = make_size(f"Size{index}-{name}", index + 1)
        variants.append(make_variant(item, color=red, size=size, stock_quantity=stock))
    return item, variants


def signed_in(phone="+8801712345678"):
    user = verified_user(phone)
    return user, authed_client(user)


def lines(user):
    """[(variant_id, quantity)] of the user's cart, oldest first."""
    from apps.cart.models import CartItem

    return list(CartItem.objects.filter(user=user).order_by("id").values_list("variant_id", "quantity"))
