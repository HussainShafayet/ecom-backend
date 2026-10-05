"""Admin > Returns: staff answer the requests customers made, enter the goods that came back, and the owner sets the policy."""
import re
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.orders.tests.helpers import line, signed_in, stock_of, stocked
from apps.returns import services
from apps.returns.models import ReturnRequest, ReturnSettings

from .helpers import body, delivered_order, returns_url

pytestmark = pytest.mark.django_db

Status = ReturnRequest.Status


@pytest.fixture
def staff():
    return get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")


@pytest.fixture
def admin_client(staff):
    client = Client()
    client.force_login(staff)
    return client


@pytest.fixture
def variant_of_mug():
    return {}


@pytest.fixture
def request_row(variant_of_mug):
    """A request of 2 of the 3 mugs (500 each) for a size problem: goods 1000, charge 60, refund 940."""
    me, client = signed_in()
    mug, mug_v = stocked("Mug", stock=10, base_price="500.00")
    variant_of_mug["variant"] = mug_v
    order = delivered_order(me, line(mug, mug_v, 3), name="Karim Ali")
    client.post(returns_url(order), body(order, (0, 2), reason="size_fit", details="Too big"), format="json")
    return ReturnRequest.objects.get()


def change_url(request):
    return reverse("admin:returns_returnrequest_change", args=[request.pk])


def form_data(request, good=None, damaged=None, **fields):
    """What the browser posts: the answer fields, plus the inline of the lines (its management form, and the two numbers of each line)."""
    request.refresh_from_db()
    items = list(request.items.all())
    data = {
        "status": request.status,
        "response": request.response,
        "return_charge": str(request.return_charge),
        "refund_amount": str(request.refund_amount),
        "items-TOTAL_FORMS": str(len(items)),
        "items-INITIAL_FORMS": str(len(items)),
        "items-MIN_NUM_FORMS": "0",
        "items-MAX_NUM_FORMS": "0",
    }
    for index, item in enumerate(items):
        data[f"items-{index}-id"] = str(item.pk)
        data[f"items-{index}-request"] = str(request.pk)
        data[f"items-{index}-good_quantity"] = str(item.good_quantity if good is None else good)
        data[f"items-{index}-damaged_quantity"] = str(item.damaged_quantity if damaged is None else damaged)
    data.update(fields)
    return data


def offered(html):
    select = re.search(r'<select name="status".*?</select>', html, re.S).group(0)
    return re.findall(r'<option value="(\w+)"', select)


def messages_of(response):
    return [str(message) for message in response.context["messages"]]


def approve(request):
    services.change_status(request, Status.APPROVED)


# --- the list and the page ---------------------------------------------------------------------------------------
def test_the_list_shows_who_asked_for_what_and_the_money(admin_client, request_row):
    html = admin_client.get(reverse("admin:returns_returnrequest_changelist")).content.decode()
    for text in (request_row.order.number, "Karim Ali", "+8801712345678", "Requested", "size_fit"[:4], "1000.00", "60.00", "940.00"):
        assert text in html


def test_requests_are_found_by_order_number_name_and_phone(admin_client, request_row):
    url = reverse("admin:returns_returnrequest_changelist")
    for term in (request_row.order.number, "Karim", "01712345678"):
        assert request_row.order.number in admin_client.get(url, {"q": term}).content.decode()
    assert request_row.order.number not in admin_client.get(url, {"q": "nobody"}).content.decode()


def test_the_page_shows_what_was_asked_and_the_money_and_only_the_answer_can_be_edited(admin_client, request_row):
    html = admin_client.get(change_url(request_row)).content.decode()

    for text in ("Too big", "The size or fit is wrong", "Mug", request_row.order.number, "1000.00", "The shop pays the courier"):
        assert text in html
    editable = re.findall(r'<(?:input|select|textarea)[^>]*name="([^"]+)"', html)
    assert [name for name in editable if not name.startswith(("csrf", "_", "items-"))] == ["return_charge", "refund_amount", "status", "response"]


@pytest.mark.parametrize(
    "status, expected",
    [
        ("requested", ["requested", "approved", "rejected", "cancelled"]),
        ("approved", ["approved", "received", "cancelled"]),
        ("received", ["received", "completed"]),
    ],
)
def test_the_status_offers_the_current_one_and_the_allowed_next_ones(admin_client, request_row, status, expected):
    ReturnRequest.objects.filter(pk=request_row.pk).update(status=status)
    assert sorted(offered(admin_client.get(change_url(request_row)).content.decode())) == sorted(expected)


@pytest.mark.parametrize("status", ["rejected", "completed", "cancelled"])
def test_an_answered_request_has_a_fixed_status_and_fixed_money_but_its_message_can_still_be_tidied(admin_client, request_row, status):
    ReturnRequest.objects.filter(pk=request_row.pk).update(status=status)
    editable = re.findall(r'<(?:input|select|textarea)[^>]*name="([^"]+)"', admin_client.get(change_url(request_row)).content.decode())
    assert [name for name in editable if not name.startswith(("csrf", "_", "items-"))] == ["response"]


def test_the_lines_can_be_edited_only_while_the_request_is_approved(admin_client, request_row):
    def inline_fields():
        html = admin_client.get(change_url(request_row)).content.decode()
        return [name for name in re.findall(r'name="(items-\d+-[a-z_]+)"', html) if name.endswith(("good_quantity", "damaged_quantity"))]

    assert inline_fields() == []  # requested: they only show what was asked for
    approve(request_row)
    assert len(inline_fields()) == 2  # approved: the two numbers of the one line
    ReturnRequest.objects.filter(pk=request_row.pk).update(status="received")
    assert inline_fields() == []  # received: recorded, read only


# --- answering -------------------------------------------------------------------------------------------------
def test_approving_with_a_message_goes_through_the_service(admin_client, request_row):
    response = admin_client.post(change_url(request_row), form_data(request_row, status="approved", response="Send it to House 5."), follow=True)

    assert response.status_code == 200
    request_row.refresh_from_db()
    assert (request_row.status, request_row.response) == ("approved", "Send it to House 5.")


def test_waiving_the_charge_in_the_form_moves_the_refund_with_it(admin_client, request_row):
    admin_client.post(change_url(request_row), form_data(request_row, return_charge="0"), follow=True)

    request_row.refresh_from_db()
    assert (request_row.return_charge, request_row.refund_amount, request_row.shop_cost) == (0, 1000, 60)


def test_a_refund_typed_in_the_form_wins_over_the_charge(admin_client, request_row):
    admin_client.post(change_url(request_row), form_data(request_row, return_charge="0", refund_amount="700"), follow=True)

    request_row.refresh_from_db()
    assert (request_row.return_charge, request_row.refund_amount) == (0, 700)


def test_the_refund_alone_can_be_changed_and_the_charge_stays(admin_client, request_row):
    admin_client.post(change_url(request_row), form_data(request_row, refund_amount="800"), follow=True)

    request_row.refresh_from_db()
    assert (request_row.return_charge, request_row.refund_amount) == (60, 800)


def test_a_status_the_flow_does_not_allow_is_refused_in_the_form(admin_client, request_row):
    response = admin_client.post(change_url(request_row), form_data(request_row, status="completed"))
    assert response.status_code == 200  # the form is shown again with an error
    request_row.refresh_from_db()
    assert request_row.status == "requested"


def test_receiving_can_not_be_chosen_before_the_request_is_approved(admin_client, request_row):
    response = admin_client.post(change_url(request_row), form_data(request_row, status="received", good=2), follow=False)
    assert response.status_code == 200
    request_row.refresh_from_db()
    assert request_row.status == "requested"


def test_what_the_customer_asked_can_not_be_changed_by_posting_it(admin_client, request_row):
    admin_client.post(change_url(request_row), form_data(request_row, reason="damaged", details="Hacked", goods_amount="1", courier_cost="1", order="999"), follow=True)
    request_row.refresh_from_db()
    assert (request_row.reason, request_row.details, request_row.goods_amount, request_row.courier_cost) == ("size_fit", "Too big", 1000, 60)


def test_a_lost_race_shows_an_error_and_changes_nothing(admin_client, request_row, monkeypatch):
    def refuse(request, **kwargs):
        raise services.InvalidTransition("approved", "rejected")

    monkeypatch.setattr(services, "staff_update", refuse)
    response = admin_client.post(change_url(request_row), form_data(request_row, status="rejected"), follow=True)

    assert any("Reload the page." in message for message in messages_of(response))
    request_row.refresh_from_db()
    assert request_row.status == "requested"


def test_a_request_can_neither_be_added_nor_deleted(admin_client, request_row):
    assert admin_client.get(reverse("admin:returns_returnrequest_add")).status_code == 403
    assert admin_client.get(reverse("admin:returns_returnrequest_delete", args=[request_row.pk])).status_code == 403


# --- the goods come back -----------------------------------------------------------------------------------------
def test_entering_what_came_back_and_choosing_received_updates_the_stock(admin_client, request_row, variant_of_mug):
    approve(request_row)
    variant = variant_of_mug["variant"]
    before = stock_of(variant)

    response = admin_client.post(change_url(request_row), form_data(request_row, status="received", **{"good": 1, "damaged": 1}), follow=True)

    assert response.status_code == 200
    request_row.refresh_from_db()
    assert request_row.status == "received" and request_row.received_at is not None
    assert (stock_of(variant), variant.__class__.objects.get(pk=variant.pk).damaged_quantity) == (before + 1, 1)
    item = request_row.items.get()
    assert (item.good_quantity, item.damaged_quantity) == (1, 1)
    assert "Return #%d received: 1 unit(s) back on the shelf, 1 damaged (counted, not added to the stock)." % request_row.pk in messages_of(response)


def test_the_answer_fields_are_saved_together_with_the_receiving(admin_client, request_row):
    approve(request_row)

    admin_client.post(change_url(request_row), form_data(request_row, status="received", good=2, damaged=0, response="Thank you", return_charge="0"), follow=True)

    request_row.refresh_from_db()
    assert (request_row.status, request_row.response, request_row.return_charge, request_row.refund_amount) == ("received", "Thank you", 0, 1000)


def test_more_units_than_were_asked_for_is_a_form_error_and_nothing_moves(admin_client, request_row, variant_of_mug):
    approve(request_row)
    before = stock_of(variant_of_mug["variant"])

    response = admin_client.post(change_url(request_row), form_data(request_row, status="received", good=2, damaged=1))

    assert response.status_code == 200  # shown again
    assert "Only 2 were asked for" in response.content.decode()
    request_row.refresh_from_db()
    assert request_row.status == "approved"
    assert stock_of(variant_of_mug["variant"]) == before


def test_receiving_with_nothing_entered_says_so_and_keeps_the_request_approved(admin_client, request_row):
    approve(request_row)

    response = admin_client.post(change_url(request_row), form_data(request_row, status="received", good=0, damaged=0), follow=True)

    assert any(services.NOTHING_CAME_BACK in message for message in messages_of(response))
    request_row.refresh_from_db()
    assert request_row.status == "approved"


def test_numbers_typed_without_choosing_received_are_not_saved_and_the_page_says_so(admin_client, request_row, variant_of_mug):
    approve(request_row)
    before = stock_of(variant_of_mug["variant"])

    response = admin_client.post(change_url(request_row), form_data(request_row, good=2, damaged=0), follow=True)

    assert "The units that came back are saved only when the status is set to Received." in messages_of(response)
    request_row.refresh_from_db()
    assert (request_row.status, request_row.items.get().good_quantity) == ("approved", 0)
    assert stock_of(variant_of_mug["variant"]) == before


def test_a_received_request_is_completed_in_the_form_with_the_final_refund(admin_client, request_row):
    approve(request_row)
    admin_client.post(change_url(request_row), form_data(request_row, status="received", good=2, damaged=0), follow=True)

    admin_client.post(change_url(request_row), form_data(request_row, status="completed", refund_amount="900"), follow=True)

    request_row.refresh_from_db()
    assert (request_row.status, request_row.refund_amount) == ("completed", 900) and request_row.completed_at is not None


def test_the_stock_moves_once_even_if_the_page_is_sent_twice(admin_client, request_row, variant_of_mug):
    approve(request_row)
    data = form_data(request_row, status="received", good=2, damaged=0)
    admin_client.post(change_url(request_row), data, follow=True)
    after = stock_of(variant_of_mug["variant"])

    admin_client.post(change_url(request_row), data, follow=True)  # the same stale page again

    assert stock_of(variant_of_mug["variant"]) == after


# --- the actions -----------------------------------------------------------------------------------------------
def run_action(client, action, *requests):
    return client.post(
        reverse("admin:returns_returnrequest_changelist"),
        {"action": action, "_selected_action": [str(request.pk) for request in requests]},
        follow=True,
    )


def test_approve_receive_all_and_complete_move_the_requests_through_the_service(admin_client, request_row, variant_of_mug):
    before = stock_of(variant_of_mug["variant"])
    run_action(admin_client, "approve", request_row)
    request_row.refresh_from_db()
    assert (request_row.status, request_row.response) == ("approved", "")

    response = run_action(admin_client, "receive_all_good", request_row)
    request_row.refresh_from_db()
    assert request_row.status == "received"
    assert stock_of(variant_of_mug["variant"]) == before + 2  # both units back on the shelf
    assert any("2 unit(s) back on the shelf, 0 damaged" in message for message in messages_of(response))

    response = run_action(admin_client, "complete", request_row)
    request_row.refresh_from_db()
    assert request_row.status == "completed"
    assert "1 return request(s) marked completed." in messages_of(response)


def test_receive_all_good_refuses_a_request_that_is_not_approved_and_moves_no_stock(admin_client, request_row, variant_of_mug):
    before = stock_of(variant_of_mug["variant"])

    response = run_action(admin_client, "receive_all_good", request_row)

    assert any("can not become received" in message for message in messages_of(response))
    assert (ReturnRequest.objects.get().status, stock_of(variant_of_mug["variant"])) == ("requested", before)


def test_reject_gives_a_polite_answer_unless_the_staff_already_wrote_one(admin_client, request_row):
    run_action(admin_client, "reject", request_row)
    request_row.refresh_from_db()
    assert (request_row.status, request_row.response) == ("rejected", services.DEFAULT_REJECTION)

    ReturnRequest.objects.filter(pk=request_row.pk).update(status="requested", response="It was used.")
    run_action(admin_client, "reject", request_row)
    request_row.refresh_from_db()
    assert request_row.response == "It was used."


def test_an_action_reports_each_request_it_could_not_change_and_still_does_the_rest(admin_client, request_row):
    other = ReturnRequest.objects.create(
        order=request_row.order, reason="damaged", goods_amount=0, courier_cost=0, return_charge=0, refund_amount=0, status="completed"
    )

    response = run_action(admin_client, "approve", request_row, other)

    messages = messages_of(response)
    assert "1 return request(s) approved." in messages
    assert any(f"Return #{other.pk}: A return request that is completed can not become approved." in message for message in messages)


# --- the policy and who may do what -----------------------------------------------------------------------------
def test_the_settings_menu_entry_opens_the_one_row(admin_client):
    response = admin_client.get(reverse("admin:returns_returnsettings_changelist"))
    assert response.status_code == 302 and response["Location"] == reverse("admin:returns_returnsettings_change", args=[1])


def test_the_owner_edits_the_window_the_return_charge_and_the_switch(admin_client):
    ReturnSettings.load()
    url = reverse("admin:returns_returnsettings_change", args=[1])
    admin_client.post(url, {"enabled": "on", "charge_return_delivery": "on", "window_days": "14"}, follow=True)
    policy = ReturnSettings.current()
    assert (policy.window_days, policy.enabled, policy.charge_return_delivery) == (14, True, True)

    admin_client.post(url, {"window_days": "14"}, follow=True)
    policy = ReturnSettings.current()
    assert (policy.enabled, policy.charge_return_delivery) == (False, False)


def test_the_window_has_sensible_bounds(admin_client):
    ReturnSettings.load()
    for bad in ("0", "91"):
        admin_client.post(reverse("admin:returns_returnsettings_change", args=[1]), {"enabled": "on", "window_days": bad})
        assert ReturnSettings.current().window_days == 7


def test_an_order_manager_answers_requests_and_enters_the_goods_but_never_changes_the_policy(request_row, variant_of_mug):
    call_command("setup_roles")
    manager = get_user_model().objects.create_user("+8801711111111", password="s3cret-Pass!", name="Manager", is_staff=True)
    manager.groups.add(Group.objects.get(name="Order Manager"))
    client = Client()
    client.force_login(manager)
    before = stock_of(variant_of_mug["variant"])

    assert client.get(change_url(request_row)).status_code == 200
    assert client.post(change_url(request_row), form_data(request_row, status="approved"), follow=True).status_code == 200
    request_row.refresh_from_db()
    assert request_row.status == "approved"

    client.post(change_url(request_row), form_data(request_row, status="received", good=2, damaged=0), follow=True)
    request_row.refresh_from_db()
    assert request_row.status == "received"
    assert stock_of(variant_of_mug["variant"]) == before + 2
    assert client.get(reverse("admin:returns_returnrequest_add")).status_code == 403
    assert client.get(reverse("admin:returns_returnsettings_change", args=[1])).status_code == 403
