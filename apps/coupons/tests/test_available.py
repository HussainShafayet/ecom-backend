"""`GET /coupons/available/`: the coupons suggested at checkout."""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.catalog.models import DiscountType
from apps.coupons.models import Coupon
from apps.coupons.services import MAX_OFFERS
from apps.coupons.tests.helpers import AVAILABLE, VALIDATE, make_coupon, make_offer

pytestmark = pytest.mark.django_db

DAY = timedelta(days=1)


def offers(client=None, **query):
    response = (client or APIClient()).get(AVAILABLE, query)
    assert response.status_code == 200, response.content
    return response.json()["data"]["offers"]


def codes(**query):
    return [offer["code"] for offer in offers(**query)]


def validate(code, subtotal, **extra):
    return APIClient().post(VALIDATE, {"code": code, "subtotal": subtotal, **extra}, format="json")


# --- what is listed ---------------------------------------------------------------------------------

def test_nothing_is_listed_when_the_shop_suggests_nothing():
    make_coupon(code="SECRET")
    response = APIClient().get(AVAILABLE)
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "OK", "data": {"offers": []}}


def test_only_a_coupon_the_staff_flagged_is_listed():
    make_coupon(code="SECRET", discount_value="90.00")  # works when typed, is never suggested
    make_offer(code="OPEN")
    assert codes() == ["OPEN"]


def test_an_offer_says_what_it_is():
    make_offer(
        code="SUMMER25", title="25% off your first order", discount_value="25.00", min_order_amount="500.00", max_discount_amount="200.00"
    )
    assert offers(subtotal="380.00") == [
        {
            "code": "SUMMER25",
            "public_title": "25% off your first order",
            "discount_type": "percentage",
            "discount_value": 25.0,
            "min_order_amount": 500.0,
            "max_discount_amount": 200.0,
            "eligible": False,
            "amount_short": 120.0,
        }
    ]


def test_no_minimum_and_no_cap_are_null():
    make_offer(min_order_amount=None, max_discount_amount=None)
    offer = offers(subtotal="10.00")[0]
    assert offer["min_order_amount"] is None and offer["max_discount_amount"] is None
    assert offer["eligible"] is True and offer["amount_short"] == 0


def test_a_zero_minimum_is_no_minimum():
    make_offer(min_order_amount="0.00")
    offer = offers()[0]
    assert offer["min_order_amount"] is None and offer["eligible"] is True


# --- eligible, and how much is missing --------------------------------------------------------------

def test_eligible_turns_on_at_the_minimum_to_the_paisa():
    make_offer(min_order_amount="500.00")
    short = offers(subtotal="499.99")[0]
    assert (short["eligible"], short["amount_short"]) == (False, 0.01)
    reached = offers(subtotal="500.00")[0]
    assert (reached["eligible"], reached["amount_short"]) == (True, 0)
    assert offers(subtotal="900.00")[0]["eligible"] is True


def test_a_missing_subtotal_is_an_empty_cart():
    make_offer(min_order_amount="500.00")
    offer = offers()[0]
    assert (offer["eligible"], offer["amount_short"]) == (False, 500.0)


@pytest.mark.parametrize("subtotal", ["-1", "abc", "1.005", "1e99999"])
def test_a_bad_subtotal_is_a_400(subtotal):
    response = APIClient().get(AVAILABLE, {"subtotal": subtotal})
    assert response.status_code == 400
    assert response.json()["success"] is False


# --- which coupons are "valid right now" ------------------------------------------------------------

def test_a_coupon_that_cannot_be_used_is_not_suggested():
    now = timezone.now()
    make_offer(code="OFF", is_active=False)
    make_offer(code="LATER", valid_from=now + DAY)
    make_offer(code="GONE", valid_until=now - DAY)
    make_offer(code="SPENT", max_redemptions=3, times_used=3)
    make_offer(code="OPEN", valid_from=now - DAY, valid_until=now + DAY, max_redemptions=3, times_used=2)
    assert codes() == ["OPEN"]


def test_what_is_not_suggested_is_what_validate_refuses_and_what_is_suggested_is_what_it_accepts():
    """One rule, two places: the list can not promise a coupon the preview then turns down."""
    now = timezone.now()
    refused = [
        make_offer(code="OFF", is_active=False),
        make_offer(code="LATER", valid_from=now + DAY),
        make_offer(code="GONE", valid_until=now - DAY),
        make_offer(code="SPENT", max_redemptions=1, times_used=1),
    ]
    accepted = [
        make_offer(code="OPEN"),
        make_offer(code="BIG", min_order_amount="2000.00"),
        make_offer(code="TIMED", valid_from=now - DAY, valid_until=now + DAY),
    ]
    listed = codes(subtotal="5000.00")
    for coupon in refused:
        assert coupon.code not in listed
        assert validate(coupon.code, "5000.00").status_code == 400
    for coupon in accepted:
        assert coupon.code in listed
        assert validate(coupon.code, "5000.00").status_code == 200


def test_a_coupon_short_of_its_minimum_is_still_listed_while_one_that_ran_out_is_not():
    make_offer(code="FAR", min_order_amount="10000.00")
    make_offer(code="SPENT", min_order_amount="10000.00", max_redemptions=1, times_used=1)
    assert codes(subtotal="100.00") == ["FAR"]


def test_a_per_customer_limit_does_not_hide_the_coupon_the_phone_is_not_known_yet():
    make_offer(code="ONCE", max_redemptions_per_customer=1)
    assert codes() == ["ONCE"]


def test_a_cancelled_orders_use_is_given_back_so_the_coupon_comes_back():
    coupon = make_offer(code="TWICE", max_redemptions=1, times_used=1)
    assert codes() == []
    Coupon.objects.filter(pk=coupon.pk).update(times_used=0)  # what release_coupon_usage does
    assert codes() == ["TWICE"]


# --- order and size ---------------------------------------------------------------------------------

def test_what_the_customer_can_use_comes_first_then_the_biggest_saving():
    make_offer(code="SMALL", discount_type=DiscountType.FIXED, discount_value="50.00")
    make_offer(code="BIG", discount_type=DiscountType.FIXED, discount_value="150.00")
    make_offer(code="FAR", discount_type=DiscountType.FIXED, discount_value="900.00", min_order_amount="5000.00")
    assert codes(subtotal="1000.00") == ["BIG", "SMALL", "FAR"]


def test_the_saving_counts_not_the_number():
    """50% capped at 50 saves less than a flat 100, although 50 is not less than 100 in the percentage's own terms."""
    make_offer(code="HALF", discount_value="50.00", max_discount_amount="50.00")
    make_offer(code="FLAT", discount_type=DiscountType.FIXED, discount_value="100.00")
    assert codes(subtotal="1000.00") == ["FLAT", "HALF"]


def test_one_out_of_reach_is_ranked_by_what_it_saves_once_reached():
    make_offer(code="SMALL", discount_type=DiscountType.FIXED, discount_value="50.00", min_order_amount="1000.00")
    make_offer(code="BIG", discount_type=DiscountType.FIXED, discount_value="300.00", min_order_amount="3000.00")
    assert codes(subtotal="100.00") == ["BIG", "SMALL"]


def test_equal_offers_keep_a_stable_order():
    for code in ("BBB", "CCC", "AAA"):
        make_offer(code=code)
    assert codes() == ["AAA", "BBB", "CCC"]


def test_at_most_five_are_shown():
    for number in range(MAX_OFFERS + 3):
        make_offer(code=f"OFFER{number}", discount_type=DiscountType.FIXED, discount_value=f"{10 + number}.00")
    shown = codes(subtotal="1000.00")
    assert len(shown) == MAX_OFFERS == 5
    assert shown[0] == "OFFER7"  # the biggest, not the first made


# --- access -----------------------------------------------------------------------------------------

def test_it_is_public_and_a_stale_token_is_not_a_401():
    make_offer()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    assert codes() == ["SUMMER25"]
    assert offers(client)[0]["code"] == "SUMMER25"


def test_it_answers_with_and_without_the_trailing_slash():
    make_offer()
    assert APIClient().get(AVAILABLE.rstrip("/")).status_code == 200


def test_it_only_reads():
    response = APIClient().post(AVAILABLE, {}, format="json")
    assert response.status_code == 405


def test_the_offers_rate_is_configured():
    number, seconds = ScopedRateThrottle().parse_rate(ScopedRateThrottle.THROTTLE_RATES["coupon_offers"])
    assert number > 0 and seconds > 0


def test_it_is_throttled_per_client(monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "coupon_offers", "1/min")
    client = APIClient()
    assert client.get(AVAILABLE).status_code == 200
    assert client.get(AVAILABLE).status_code == 429


def test_it_does_not_share_the_previews_allowance(monkeypatch):
    """Drawing the page must not use up the tries a customer has to type codes."""
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "coupon", "1/min")
    client = APIClient()
    client.post(VALIDATE, {"code": "NOSUCH", "subtotal": "1"}, format="json")
    assert client.get(AVAILABLE).status_code == 200


# --- the model --------------------------------------------------------------------------------------

def test_a_coupon_shown_at_checkout_needs_a_title():
    coupon = Coupon(code="UNTITLED", discount_type=DiscountType.PERCENTAGE, discount_value="10.00", show_at_checkout=True)
    with pytest.raises(ValidationError) as caught:
        coupon.full_clean()
    assert "Write the title customers will see" in str(caught.value)
    coupon.public_title = "10% off"
    coupon.full_clean()


def test_a_secret_coupon_needs_no_title():
    Coupon(code="QUIET", discount_type=DiscountType.PERCENTAGE, discount_value="10.00").full_clean()


def test_the_title_is_stored_trimmed():
    coupon = make_offer(title="  10% off  ")
    coupon.refresh_from_db()
    assert coupon.public_title == "10% off"


def test_the_database_refuses_a_shown_coupon_without_a_title():
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        make_coupon(code="UNTITLED", show_at_checkout=True)
