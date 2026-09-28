"""Shared by the coupons tests."""
from apps.catalog.models import DiscountType
from apps.coupons.models import Coupon

VALIDATE = "/api/v1/coupons/validate/"


def make_coupon(code="SUMMER25", discount_type=DiscountType.PERCENTAGE, discount_value="25.00", **extra):
    return Coupon.objects.create(code=code, discount_type=discount_type, discount_value=discount_value, **extra)
