from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse

from . import services
from .models import DashboardReport


@admin.register(DashboardReport)
class DashboardReportAdmin(admin.ModelAdmin):
    """No rows to list: the menu entry opens the report page directly, like SiteSettings/NotificationSettings do
    for their one-row pages. Owner-only: nothing here is granted to either staff Group in setup_roles.py, so only
    a superuser (who bypasses every permission check) can see or open it — the same "documented by omission"
    convention SiteSettings/NotificationSettings already rely on, via the default has_view/module_permission."""

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
        period = request.GET.get("period", "month")
        context = {
            **self.admin_site.each_context(request),
            "title": "Dashboard",
            **services.dashboard_context(period, settings.LOW_STOCK_THRESHOLD),
        }
        return TemplateResponse(request, "admin/dashboard/dashboard.html", context)
