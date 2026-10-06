"""The stock history: the only code that writes a `StockMovement`.

Whoever moves a variant's stock calls `record` in the SAME transaction, after (or next to) the move, so a rolled-back order leaves no line
and a committed one always has its line. The movers are `orders.services` (a sale, an order put back, goods a customer sent back) and
`ProductVariant.save` (a hand-edit in the admin, or a new variant with stock). `bulk_create` and `queryset.update()` send no `save`: a
caller that moves stock that way records it itself, as `orders.services._shift_stock`'s callers do."""
from .models import StockMovement


def record(entries, kind, reference="", by=None):
    """Write one history line per entry. `entries` is `[(variant, change, stock_after, damaged_change)]`: `change` is the signed
    movement of the stock, `stock_after` what was left, `damaged_change` the units counted as damaged. `variant` needs its `product`,
    `color` and `size` loaded (the line copies the name), which `orders.services._lock_variants(..., with_details=True)` gives. An entry
    that moves nothing is skipped. One INSERT however many lines: placing an order must not cost a query per line."""
    lines = [
        StockMovement(
            variant=variant,
            sku=variant.sku,
            name=f"{variant.product.name} ({variant.label})",
            kind=kind,
            change=change,
            damaged_change=damaged_change,
            stock_after=stock_after,
            reference=reference,
            by=by,
        )
        for variant, change, stock_after, damaged_change in entries
        if change or damaged_change
    ]
    if lines:
        StockMovement.objects.bulk_create(lines)
