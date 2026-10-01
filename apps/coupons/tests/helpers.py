"""Shared by the coupons tests."""
from apps.catalog.models import DiscountType
from apps.coupons.models import Coupon

VALIDATE = "/api/v1/coupons/validate/"
AVAILABLE = "/api/v1/coupons/available/"


def make_coupon(code="SUMMER25", discount_type=DiscountType.PERCENTAGE, discount_value="25.00", **extra):
    return Coupon.objects.create(code=code, discount_type=discount_type, discount_value=discount_value, **extra)


def make_offer(code="SUMMER25", title="25% off your first order", **extra):
    """A coupon the shop suggests at checkout."""
    return make_coupon(code=code, show_at_checkout=True, public_title=title, **extra)
