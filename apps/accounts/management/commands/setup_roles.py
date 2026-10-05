"""The two staff Groups and what each may touch in the admin. Never add a permission here that a ModelAdmin already
blocks with has_add_permission/has_change_permission/has_delete_permission (Order/DeliveryCharge add+delete,
Payment add+change+delete, PageContent add+delete, ContactMessage add): the block is the belt, this file is the
suspenders, and a permission granted "just in case" would fail open instead of closed if the block is ever loosened."""
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# app_label -> {model_name: (action, ...)}
CATALOG_MANAGER = {
    "catalog": {
        "category": ("view", "add", "change", "delete"),
        "brand": ("view", "add", "change", "delete"),
        "tag": ("view", "add", "change", "delete"),
        "color": ("view", "add", "change", "delete"),
        "size": ("view", "add", "change", "delete"),
        "product": ("view", "add", "change", "delete"),
        "productvariant": ("view", "add", "change", "delete"),
        "productmedia": ("view", "add", "change", "delete"),
        "flashsale": ("view", "change"),  # the one window; add/delete stays blocked
    },
    "content": {
        "pagecontent": ("view", "change"),  # the six pages are fixed; add/delete stays blocked
        "contentitem": ("view", "add", "change", "delete"),  # the actual slides/banners
    },
    "siteconfig": {
        "staticpage": ("view", "add", "change", "delete"),
        "faqitem": ("view", "add", "change", "delete"),
    },
}

ORDER_MANAGER = {
    "orders": {
        "order": ("view", "change"),  # status only; add/delete stays blocked (audit trail)
        "orderitem": ("view",),  # read-only inline
        "orderstatushistory": ("view",),  # read-only inline
    },
    "returns": {
        "returnrequest": ("view", "change"),  # answer it; add/delete stays blocked (the customer makes it)
        "returnitem": ("view", "change"),  # the inline where they enter what came back (good / damaged); add/delete stay blocked
    },
    "payments": {"payment": ("view",)},  # a read-only ledger otherwise
    "reviews": {
        "review": ("view", "change", "delete"),  # change = approve/hide, delete = spam removal
        "reviewmedia": ("view", "delete"),  # remove a bad photo; fields are read-only
    },
    "siteconfig": {"contactmessage": ("view", "change")},  # mark handled; add stays blocked
    "accounts": {"user": ("view",)},  # "customer, read-only" — never change/add/delete from a Group
}

ROLES = {"Catalog Manager": CATALOG_MANAGER, "Order Manager": ORDER_MANAGER}


class Command(BaseCommand):
    help = (
        "Create or update the staff Groups (Catalog Manager, Order Manager) with the admin permissions each needs. "
        "Idempotent and safe to run in production: syncs every group's permissions to exactly what this file lists, "
        "so removing a grant here and rerunning removes it from the group too. Never assigns a user to a group "
        "(do that by hand: Admin > Users > a user's Permissions fieldset). The Owner role is is_superuser=True, "
        "never a Group."
    )

    def handle(self, *args, **options):
        summary = []
        with transaction.atomic():
            for role_name, apps_map in ROLES.items():
                group, _ = Group.objects.get_or_create(name=role_name)
                permissions = [
                    self._permission(app_label, model_name, action)
                    for app_label, models in apps_map.items()
                    for model_name, actions in models.items()
                    for action in actions
                ]
                group.permissions.set(permissions)
                summary.append(f"{role_name} ({len(permissions)} permission(s))")
        self.stdout.write(self.style.SUCCESS("Staff roles synced: " + ", ".join(summary)))

    @staticmethod
    def _permission(app_label, model_name, action):
        codename = f"{action}_{model_name}"
        try:
            return Permission.objects.get(content_type__app_label=app_label, codename=codename)
        except Permission.DoesNotExist as exc:
            raise CommandError(f"{app_label}.{codename} does not exist — run migrate first.") from exc
