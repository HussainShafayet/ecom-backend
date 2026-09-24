def on_order_placed(sender, order, **kwargs):
    from .services import open_payment

    open_payment(order)


def on_order_status_changed(sender, order, new, **kwargs):
    from .services import handle_order_status_changed

    handle_order_status_changed(order, new)
