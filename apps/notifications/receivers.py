from django.db import transaction


def on_order_placed(sender, order, **kwargs):
    from .services import notify_order_placed

    transaction.on_commit(lambda pk=order.pk: notify_order_placed(pk))


def on_order_status_changed(sender, order, new, **kwargs):
    from .services import notify_order_status_changed

    transaction.on_commit(lambda pk=order.pk, new_status=new: notify_order_status_changed(pk, new_status))
