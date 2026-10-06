from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from rest_framework.exceptions import ValidationError as ApiValidationError

from . import services, state
from .models import ReturnItem, ReturnRequest, ReturnSettings

Status = ReturnRequest.Status
FINAL = (Status.REJECTED, Status.COMPLETED, Status.CANCELLED)


class ReturnRequestForm(forms.ModelForm):
    """What staff may edit on a request: its status (only to one the flow allows, `state.py`), their message to the customer, the return
    charge (0 waives it: the shop pays the courier) and the amount to pay back. Everything else is what the customer asked and stays."""

    class Meta:
        model = ReturnRequest
        fields = ("status", "response", "return_charge", "refund_amount")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "status" in self.fields:
            current = self.instance.status
            offered = {current, *state.allowed_next(current)}
            self.fields["status"].choices = [(v, label) for v, label in Status.choices if v in offered]


class ReturnItemForm(forms.ModelForm):
    """What came back of one line: units that are fine (back on the shelf) and units that are damaged (only counted)."""

    class Meta:
        model = ReturnItem
        fields = ("good_quantity", "damaged_quantity")

    def clean(self):
        data = super().clean()
        good, damaged = data.get("good_quantity") or 0, data.get("damaged_quantity") or 0
        if good + damaged > self.instance.quantity:
            raise forms.ValidationError(f"Only {self.instance.quantity} were asked for: {good} fine and {damaged} damaged is too many.")
        return data


class ReturnItemInline(admin.TabularInline):
    """The lines to come back. While the request is approved the two numbers are where staff enter what arrived (they are saved when the
    status is set to Received, by `services.receive_goods`, which also moves the stock); in every other state it only shows them."""

    model = ReturnItem
    form = ReturnItemForm
    fields = ("product", "variant", "quantity", "good_quantity", "damaged_quantity")
    readonly_fields = ("product", "variant", "quantity")
    extra = 0
    can_delete = False
    verbose_name_plural = "items to return (enter what came back, then set the status to Received)"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("order_item")

    @admin.display(description="Item")
    def product(self, item):
        return item.order_item.product_name

    @admin.display(description="Variant")
    def variant(self, item):
        return item.order_item.variant_label

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is not None and obj.status == Status.APPROVED and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    """Customers make the requests at the shop: staff can neither add nor delete one. They answer it: approve (and say how to send the goods
    back in the message), reject (and say why), receive the goods (enter how many came back fine and how many damaged: the fine ones go back
    on the shelf, the damaged ones are counted), and mark it completed once the money is paid back. The money itself is paid by hand; the order
    stays as it is (mark the whole order refunded in Orders > Orders if everything came back)."""

    form = ReturnRequestForm
    list_display = ("id", "order", "customer", "status", "reason", "goods_amount", "return_charge", "refund_amount", "created_at")
    list_filter = ("status", "reason", "created_at")
    list_select_related = ("order",)
    search_fields = ("order__number", "order__name", "order__phone_number")
    fieldsets = (
        (None, {"fields": ("order", "created_at", "reason", "details")}),
        (
            "Money",
            {
                "fields": ("goods_amount", "courier_cost", "return_charge", "refund_amount", "shop_cost"),
                "description": "Refund = goods less the return charge. The customer pays the charge unless the shop was at fault (damaged, "
                "wrong item, not as described) or you set it to 0; then the shop pays the courier out of its profit.",
            },
        ),
        ("Your answer", {"fields": ("status", "response")}),
        ("Dates", {"fields": ("received_at", "completed_at")}),
    )
    readonly_fields = ("order", "created_at", "reason", "details", "goods_amount", "courier_cost", "shop_cost", "received_at", "completed_at")
    inlines = (ReturnItemInline,)
    actions = ("approve", "reject", "receive_all_good", "complete")

    @admin.display(description="Customer")
    def customer(self, request):
        return f"{request.order.name} ({request.order.phone_number})"

    @admin.display(description="The shop pays the courier")
    def shop_cost(self, request):
        return request.shop_cost

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status in FINAL:  # nothing left to decide; the message may still be tidied
            readonly.append("status")
        if obj is not None and obj.status in state.MONEY_LOCKED:
            readonly += ["return_charge", "refund_amount"]
        return readonly

    def save_model(self, request, obj, form, change):
        cleaned = form.cleaned_data
        original = ReturnRequest.objects.get(pk=obj.pk)  # the form already changed `obj` in memory: put it back first
        for name in ("status", "response", "return_charge", "refund_amount"):
            setattr(obj, name, getattr(original, name))
        target = cleaned.get("status")
        # a figure the staff did not touch is not sent: a new charge then moves the refund with it
        charge = cleaned.get("return_charge") if "return_charge" in form.changed_data else None
        refund = cleaned.get("refund_amount") if "refund_amount" in form.changed_data else None
        try:
            services.staff_update(
                obj,
                status=None if target == Status.RECEIVED else target,  # receiving is save_related's job (it needs the numbers)
                response=cleaned.get("response"),
                return_charge=charge,
                refund_amount=refund,
            )
        except services.InvalidTransition as exc:  # somebody else answered it after this page was opened
            self.message_user(request, f"Return #{obj.pk}: {exc} Reload the page.", messages.ERROR)

    def save_related(self, request, form, formsets, change):
        obj = form.instance
        if form.cleaned_data.get("status") == Status.RECEIVED and obj.status == Status.APPROVED:
            lines = [
                {
                    "item_id": item_form.instance.pk,
                    "good": item_form.cleaned_data.get("good_quantity") or 0,
                    "damaged": item_form.cleaned_data.get("damaged_quantity") or 0,
                }
                for formset in formsets
                for item_form in formset.forms
            ]
            self._receive(request, obj, lines)
        elif any(item_form.has_changed() for formset in formsets for item_form in formset.forms):
            self.message_user(request, "The units that came back are saved only when the status is set to Received.", messages.WARNING)
        for formset in formsets:  # the numbers are saved by `receive_goods`, not by the formset; the admin's change log reads these three
            formset.new_objects, formset.changed_objects, formset.deleted_objects = [], [], []

    def _receive(self, request, obj, lines):
        try:
            result = services.receive_goods(obj, lines, by=request.user)
        except services.InvalidTransition as exc:
            self.message_user(request, f"Return #{obj.pk}: {exc} Reload the page.", messages.ERROR)
        except ApiValidationError as exc:
            for sentence in exc.detail:
                self.message_user(request, f"Return #{obj.pk}: {sentence}", messages.ERROR)
        else:
            self.message_user(
                request,
                f"Return #{obj.pk} received: {result['restocked']} unit(s) back on the shelf, {result['damaged']} damaged (counted, not added to the stock).",
                messages.SUCCESS,
            )
            if result["unplaced"]:
                self.message_user(
                    request,
                    f"Return #{obj.pk}: {', '.join(result['unplaced'])} is no longer in the catalog, so its units could not be added to any stock.",
                    messages.WARNING,
                )

    def _answer_all(self, request, queryset, new_status, response, done):
        changed, failures = 0, []
        for item in queryset.order_by("pk"):
            try:
                services.change_status(item, new_status, response=response if not item.response else None)
                changed += 1
            except services.InvalidTransition as exc:
                failures.append(f"Return #{item.pk}: {exc}")
        if changed:
            self.message_user(request, f"{changed} return request(s) {done}.", messages.SUCCESS)
        for failure in failures:
            self.message_user(request, failure, messages.ERROR)

    @admin.action(description="Approve (the goods may be sent back)", permissions=["change"])
    def approve(self, request, queryset):
        self._answer_all(request, queryset, Status.APPROVED, None, "approved")

    @admin.action(description="Reject", permissions=["change"])
    def reject(self, request, queryset):
        self._answer_all(request, queryset, Status.REJECTED, services.DEFAULT_REJECTION, "rejected")

    @admin.action(description="Goods received, all of it in good condition (puts it back on the shelf)", permissions=["change"])
    def receive_all_good(self, request, queryset):
        for item in queryset.order_by("pk"):
            lines = [{"item_id": line.pk, "good": line.quantity, "damaged": 0} for line in item.items.all()]
            self._receive(request, item, lines)

    @admin.action(description="Mark completed (money paid back)", permissions=["change"])
    def complete(self, request, queryset):
        self._answer_all(request, queryset, Status.COMPLETED, None, "marked completed")


@admin.register(ReturnSettings)
class ReturnSettingsAdmin(admin.ModelAdmin):
    """One row: the menu entry opens it directly (a list of one would only be a click in the way). Owner only."""

    def changelist_view(self, request, extra_context=None):
        return redirect(reverse("admin:returns_returnsettings_change", args=[ReturnSettings.load().pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
