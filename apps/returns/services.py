"""Return requests: the only code that opens one, moves one, receives its goods, or says whether (and what of) an order may be returned.

`request_return` runs in one transaction with the ORDER row locked, so two taps on Send can not both pass the "units left" check. A
request holds the units it names until it is rejected or cancelled (`state.HOLDING`).

`receive_goods` is where the inventory moves: under the request's row lock it records, per line, how many units came back fine and how many
damaged, puts the fine ones back on the shelf and counts the damaged ones (`orders.services.take_back_stock`, which locks the variants in
pk order like every other stock writer), and moves the request to `received`. It happens once: a received request can not be received again.

`change_status` / `staff_update` are the other places a status changes (never to `received`): both ask `state.py` first, under the
request's own row lock. The customer's cancel is `cancel_request`; the admin goes through `staff_update`, `change_status` and `receive_goods`.

Money is never moved here: the amounts are the figures the shop pays back by hand (see `models.py` for how they fit together).
"""
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from apps.core.money import ZERO, quantize_money
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatusHistory

from . import state
from .models import ReturnItem, ReturnRequest, ReturnSettings

NOT_TAKING = "The shop is not taking return requests right now."
NOT_DELIVERED = "Only a delivered order can be returned."
NOTHING_LEFT = "Everything in this order is already in a return request."
CANCEL_REFUSED = "Only a request the shop has not answered yet can be cancelled. Please contact us."
NOTHING_CAME_BACK = "Enter at least one unit that came back, or cancel the request."
DEFAULT_REJECTION = "Sorry, we can not take this back."


class InvalidTransition(APIException):
    """The request may not move from its status to the requested one (see `state.py`)."""

    status_code = 400
    default_code = "invalid_transition"

    def __init__(self, old, new):
        self.old, self.new = old, new
        super().__init__(f"A return request that is {_label(old)} can not become {_label(new)}.")


def _label(status):
    return ReturnRequest.Status(status).label.lower() if status in ReturnRequest.Status.values else str(status)


# --- what may be returned -----------------------------------------------------------------------------------
def delivered_at(order):
    """When the order was delivered (the newest history row that says so); the last change when it has none."""
    step = OrderStatusHistory.objects.filter(order=order, to_status=Order.Status.DELIVERED).order_by("-id").first()
    return step.created_at if step else order.updated_at


def return_until(order, policy=None):
    """The last day (inclusive, shop time) a return may be asked for."""
    policy = policy or ReturnSettings.current()
    return timezone.localdate(delivered_at(order)) + timedelta(days=policy.window_days)


def refusal(order, policy=None):
    """The sentence that says why this order can not be returned now, or None when it can."""
    policy = policy or ReturnSettings.current()
    if not policy.enabled:
        return NOT_TAKING
    if order.status != Order.Status.DELIVERED:
        return NOT_DELIVERED
    until = return_until(order, policy)
    if timezone.localdate() > until:
        return f"The time to return this order ended on {until:%d %b %Y}."
    return None


def returnable_units(order):
    """`{order_item_id: units still free to return}` for the lines that have some: what was bought, less what
    requests that are not rejected or cancelled already hold."""
    held = {
        row["order_item_id"]: row["units"]
        for row in ReturnItem.objects.filter(request__order=order, request__status__in=state.HOLDING)
        .values("order_item_id")
        .annotate(units=Sum("quantity"))
    }
    free = {item.pk: item.quantity - held.get(item.pk, 0) for item in order.items.all()}
    return {pk: units for pk, units in free.items() if units > 0}


# --- the money of a request -----------------------------------------------------------------------------------
def goods_value(order, lines):
    """What the shop owes for `lines` (`[(order_item, units)]`): their price, less the same share of the coupon's discount the order got (a
    coupon took, say, 10% off everything, so a returned line is worth 10% less). The delivery charge is not part of it."""
    goods = sum(item.unit_price * units for item, units in lines)
    if order.discount_amount and order.subtotal:
        goods = goods * (order.subtotal - order.discount_amount) / order.subtotal
    return quantize_money(goods)


def return_charge_for(order, reason, policy=None):
    """What the customer pays of the courier cost for sending goods back for this `reason`: the order's delivery charge, but nothing when the
    shop was at fault (damaged, wrong item, not as described) or when the policy does not charge for returns at all."""
    policy = policy or ReturnSettings.current()
    if not policy.charge_return_delivery or reason in ReturnRequest.FREE_REASONS:
        return ZERO
    return order.delivery_charge


def refund_after(goods, charge):
    """The goods less the return charge, never below nothing."""
    return max(quantize_money(goods - charge), ZERO)


# --- the customer asks, or changes their mind ------------------------------------------------------------------
def request_return(user, number, data):
    """Open a request for the lines in `data["items"]` (`[{item_id, quantity}]`) of the customer's own order. Raises a 400
    `ValidationError` with every problem found, having written nothing; a 404 for an order that is not theirs."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(user=user, number=number).first()  # two taps: one waits
        if order is None:
            raise NotFound("Order not found.")
        policy = ReturnSettings.current()
        problem = refusal(order, policy)
        if problem:
            raise ValidationError(problem)

        free = returnable_units(order)
        if not free:
            raise ValidationError(NOTHING_LEFT)
        order_items = {item.pk: item for item in order.items.all()}
        problems, lines = [], []
        for entry in data["items"]:
            item = order_items.get(entry["item_id"])
            if item is None:
                problems.append("One of those items is not in this order.")
                continue
            name = f"{item.product_name} ({item.variant_label})"
            left = free.get(item.pk, 0)
            if left == 0:
                problems.append(f"{name} is already in a return request.")
            elif entry["quantity"] > left:
                problems.append(f"Only {left} of {name} can still be returned.")
            else:
                lines.append((item, entry["quantity"]))
        if problems:
            raise ValidationError(list(dict.fromkeys(problems)))

        goods = goods_value(order, lines)
        charge = return_charge_for(order, data["reason"], policy)
        request = ReturnRequest.objects.create(
            order=order,
            reason=data["reason"],
            details=data.get("details", ""),
            goods_amount=goods,
            courier_cost=order.delivery_charge,
            return_charge=charge,
            refund_amount=refund_after(goods, charge),
        )
        ReturnItem.objects.bulk_create([ReturnItem(request=request, order_item=item, quantity=units) for item, units in lines])
    return request


def cancel_request(user, number, request_id):
    """The customer calls off their own request, while the shop has not answered it."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(user=user, number=number).first()
        request = order.return_requests.filter(pk=request_id).first() if order else None
        if request is None:
            raise NotFound("Return request not found.")
        if request.status != ReturnRequest.Status.REQUESTED:
            raise ValidationError(CANCEL_REFUSED)
        change_status(request, ReturnRequest.Status.CANCELLED)
    return request


# --- the shop answers ------------------------------------------------------------------------------------------
def change_status(request, new_status, response=None):
    """Move `request` to `new_status` if `state.py` allows it, else raise `InvalidTransition`. `response` (the shop's
    message to the customer) replaces the old one when given. Returns the request. Never to `received`: that is `receive_goods`."""
    return staff_update(request, status=new_status, response=response)


def staff_update(request, status=None, response=None, return_charge=None, refund_amount=None):
    """What the admin saves, under the request's row lock: a new status (through the flow, never `received`), the shop's message, the return
    charge and the amount paid back (both only until the request is rejected, completed or cancelled). A new charge moves the refund with it
    (goods less charge) unless the refund is given too. Anything left as None is not touched."""
    if status == ReturnRequest.Status.RECEIVED:
        raise ValueError("A request is received through receive_goods(), which also moves the stock.")
    with transaction.atomic():
        locked = ReturnRequest.objects.select_for_update().get(pk=request.pk)
        old = locked.status
        if status is not None and status != old:
            if not state.can_transition(old, status):
                raise InvalidTransition(old, status)
            locked.status = status
            if status == ReturnRequest.Status.COMPLETED:
                locked.completed_at = timezone.now()
        if response is not None:
            locked.response = response
        if old not in state.MONEY_LOCKED:
            if return_charge is not None:
                locked.return_charge = return_charge
                if refund_amount is None:
                    locked.refund_amount = refund_after(locked.goods_amount, return_charge)
            if refund_amount is not None:
                locked.refund_amount = refund_amount
        _save(locked)
    _sync(request, locked)
    return request


def receive_goods(request, lines, by=None):
    """The goods are back: record, per line of the request, how many units came back fine and how many damaged (`lines`:
    `[{"item_id": <ReturnItem pk>, "good": n, "damaged": n}]`; a line left out came back with nothing), put the fine units back on the
    shelf, count the damaged ones, and move the request to `received`. Under the request's row lock, once. Each variant gets a line in the stock
    history (`by` is the staff user who entered the numbers). Raises a 400 `ValidationError`
    naming every problem (nothing is written), `InvalidTransition` when the request is not `approved`.

    Returns `{"restocked": units, "damaged": units, "unplaced": [names]}`; `unplaced` are lines whose product variant was deleted from the
    catalog since the order, so there is no stock row to put their units back to (they are still recorded on the request)."""
    with transaction.atomic():
        locked = ReturnRequest.objects.select_for_update().get(pk=request.pk)
        if not state.can_transition(locked.status, ReturnRequest.Status.RECEIVED):
            raise InvalidTransition(locked.status, ReturnRequest.Status.RECEIVED)

        items = {item.pk: item for item in locked.items.select_related("order_item")}
        counted, problems = {}, []
        for entry in lines:
            item = items.get(entry["item_id"])
            if item is None:
                problems.append("One of those lines is not in this request.")
                continue
            good, damaged = int(entry.get("good") or 0), int(entry.get("damaged") or 0)
            name = f"{item.order_item.product_name} ({item.order_item.variant_label})"
            if good < 0 or damaged < 0:
                problems.append(f"{name}: a number of units can not be negative.")
            elif good + damaged > item.quantity:
                problems.append(f"{name}: {good + damaged} units can not come back, only {item.quantity} were asked for.")
            else:
                counted[item.pk] = (good, damaged)
        if not problems and not any(good + damaged for good, damaged in counted.values()):
            problems.append(NOTHING_CAME_BACK)
        if problems:
            raise ValidationError(list(dict.fromkeys(problems)))

        good_by_variant, damaged_by_variant, unplaced = defaultdict(int), defaultdict(int), []
        for pk, (good, damaged) in counted.items():
            item = items[pk]
            item.good_quantity, item.damaged_quantity = good, damaged
            item.save(update_fields=["good_quantity", "damaged_quantity"])
            variant_id = item.order_item.variant_id
            if variant_id is None:
                if good + damaged:
                    unplaced.append(item.order_item.product_name)
                continue
            good_by_variant[variant_id] += good
            damaged_by_variant[variant_id] += damaged
        vanished = order_services.take_back_stock(
            good_by_variant, damaged_by_variant, reference=f"Return #{locked.pk} of {locked.order.number}", by=by
        )
        unplaced += [items[pk].order_item.product_name for pk in items if items[pk].order_item.variant_id in vanished]

        locked.status = ReturnRequest.Status.RECEIVED
        locked.received_at = timezone.now()
        _save(locked)
    _sync(request, locked)
    return {
        "restocked": sum(good for good, _ in counted.values()),
        "damaged": sum(damaged for _, damaged in counted.values()),
        "unplaced": list(dict.fromkeys(unplaced)),
    }


def _save(locked):
    locked.save(
        update_fields=["status", "response", "return_charge", "refund_amount", "received_at", "completed_at", "updated_at"]
    )


def _sync(request, locked):
    """The caller's copy is up to date too."""
    for name in ("status", "response", "return_charge", "refund_amount", "received_at", "completed_at", "updated_at"):
        setattr(request, name, getattr(locked, name))
