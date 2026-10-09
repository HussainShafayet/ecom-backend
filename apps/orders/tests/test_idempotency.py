"""Placing an order is safe to repeat: the same `Idempotency-Key` answers with the order it already placed (a double tap, a retry after a lost
answer), also when two requests arrive at the same moment. The key counts for its customer only, a different order under the same key is a 409, and
a refused order does not use the key up."""
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.coupons.tests.helpers import make_coupon
from apps.orders.models import Order, OrderRequestKey, OrderStatusHistory
from apps.orders.tests.helpers import ORDERS, checkout_body, errors_of, line, signed_in, stock_of, stocked
from apps.orders.tests.test_concurrency import run_together

KEY = "5b0c1f9e-8d2a-4c63-9a77-0e1d2c3b4a59"


def place(client, key, *items, **overrides):
    headers = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}
    return client.post(ORDERS, checkout_body(*items, **overrides), format="json", **headers)


@pytest.mark.django_db
class TestRepeating:
    def test_the_same_key_again_answers_with_the_order_it_placed(self, api_client):
        product, variant = stocked("Mug", stock=10)

        first = place(api_client, KEY, line(product, variant, 2))
        second = place(api_client, KEY, line(product, variant, 2))

        assert (first.status_code, second.status_code) == (201, 200)
        assert second.json()["data"]["order_id"] == first.json()["data"]["order_id"]
        assert second.json()["message"] == "Order already placed."
        assert second.json()["data"]["total"] == first.json()["data"]["total"]
        assert Order.objects.count() == 1

    def test_nothing_happens_twice(self, api_client):
        product, variant = stocked("Mug", stock=10)
        coupon = make_coupon("TEN", discount_value="10.00")

        place(api_client, KEY, line(product, variant, 2), coupon_code="TEN")
        place(api_client, KEY, line(product, variant, 2), coupon_code="TEN")

        assert stock_of(variant) == 8  # two taken, not four
        coupon.refresh_from_db()
        assert coupon.times_used == 1
        order = Order.objects.get()
        assert OrderStatusHistory.objects.filter(order=order).count() == 1
        assert OrderRequestKey.objects.get().order == order

    def test_other_keys_and_no_key_place_other_orders(self, api_client):
        product, variant = stocked("Mug", stock=10)

        place(api_client, KEY, line(product, variant))
        place(api_client, "another-key-0001", line(product, variant))
        place(api_client, None, line(product, variant))
        place(api_client, None, line(product, variant))  # without a key it works as it always did: another order each time

        assert Order.objects.count() == 4
        assert OrderRequestKey.objects.count() == 2


@pytest.mark.django_db
class TestTheSameKeyForAnotherOrder:
    def test_is_a_409_and_places_nothing(self, api_client):
        product, variant = stocked("Mug", stock=10)
        first = place(api_client, KEY, line(product, variant, 2))

        second = place(api_client, KEY, line(product, variant, 3))  # the customer changed the order but kept the key

        assert first.status_code == 201
        assert second.status_code == 409
        body = second.json()
        assert body["success"] is False
        assert "different order" in body["errors"][0]
        assert Order.objects.count() == 1
        assert stock_of(variant) == 8  # the first order's two, nothing more

    def test_a_changed_address_is_another_order_too(self, api_client):
        product, variant = stocked("Mug", stock=10)
        place(api_client, KEY, line(product, variant), shipping_address="House 1")
        assert place(api_client, KEY, line(product, variant), shipping_address="House 2").status_code == 409

    def test_prices_the_client_sends_do_not_make_it_another_order(self, api_client):
        product, variant = stocked("Mug", stock=10)
        first = place(api_client, KEY, line(product, variant, 1, price=500))
        again = place(api_client, KEY, line(product, variant, 1, price=1), total_price="1.00")  # they are ignored by the server anyway
        assert (first.status_code, again.status_code) == (201, 200)


@pytest.mark.django_db
class TestWhoOwnsAKey:
    def test_another_guest_with_the_same_key_places_their_own_order(self, api_client):
        product, variant = stocked("Mug", stock=10)
        first = place(api_client, KEY, line(product, variant), phone_number="+8801711111111")
        other = place(api_client, KEY, line(product, variant), phone_number="+8801722222222")

        assert (first.status_code, other.status_code) == (201, 201)  # not a replay, and it did not read the first order
        assert other.json()["data"]["order_id"] != first.json()["data"]["order_id"]

    def test_a_signed_in_customer_gets_their_own_order_back_and_nobody_elses(self):
        product, variant = stocked("Mug", stock=10)
        _, mine = signed_in("+8801711111111")
        _, theirs = signed_in("+8801722222222")

        first = place(mine, KEY, line(product, variant))
        again = place(mine, KEY, line(product, variant))
        other = place(theirs, KEY, line(product, variant))

        assert (first.status_code, again.status_code, other.status_code) == (201, 200, 201)
        assert again.json()["data"]["order_id"] == first.json()["data"]["order_id"]
        assert other.json()["data"]["order_id"] != first.json()["data"]["order_id"]


@pytest.mark.django_db
class TestARefusedOrder:
    def test_does_not_use_the_key_up(self, api_client):
        product, variant = stocked("Mug", stock=1)

        refused = place(api_client, KEY, line(product, variant, 5))  # more than there is
        assert errors_of(refused)
        assert OrderRequestKey.objects.count() == 0

        placed = place(api_client, KEY, line(product, variant, 1))  # fixed by the customer: the same key works

        assert placed.status_code == 201
        assert Order.objects.count() == 1


@pytest.mark.django_db
class TestTheHeader:
    @pytest.mark.parametrize("key", ["", "short", "x" * 65, "has space in it", "semi;colon-key-01"])
    def test_a_malformed_key_is_a_400_and_places_nothing(self, api_client, key):
        product, variant = stocked("Mug", stock=10)

        response = place(api_client, key, line(product, variant))

        assert response.status_code == 400
        assert "Idempotency-Key" in errors_of(response)[0]
        assert Order.objects.count() == 0

    @pytest.mark.parametrize("key", ["12345678", "a" * 64, "a-b_c.d:e-1234", KEY])
    def test_a_plain_token_is_fine(self, api_client, key):
        product, variant = stocked("Mug", stock=10)
        assert place(api_client, key, line(product, variant)).status_code == 201

    @override_settings(CORS_ALLOWED_ORIGINS=["https://shop.example"])
    def test_the_storefront_may_send_it_across_origins(self):
        response = APIClient().options(
            ORDERS,
            HTTP_ORIGIN="https://shop.example",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,idempotency-key",
        )
        assert "idempotency-key" in response["Access-Control-Allow-Headers"].lower()


@pytest.mark.django_db(transaction=True)
class TestTwoRequestsAtOnce:
    def test_the_same_key_at_the_same_moment_places_one_order(self):
        product, variant = stocked("Mug", stock=10)
        body = checkout_body(line(product, variant, 2))

        def work(index):
            return APIClient().post(ORDERS, body, format="json", HTTP_IDEMPOTENCY_KEY=KEY)

        responses = run_together(4, work)

        assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
        assert len({response.json()["data"]["order_id"] for response in responses}) == 1
        assert Order.objects.count() == 1
        assert stock_of(variant) == 8
