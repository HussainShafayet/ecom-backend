from django.db import models


class DashboardReport(models.Model):
    """No data of its own — exists only so the admin has a Dashboard entry that opens the report directly (see
    DashboardReportAdmin.changelist_view), the same trick SiteSettings/NotificationSettings use for their one-row
    pages. managed=False: nothing is ever created, read, or given a database table."""

    class Meta:
        managed = False
        verbose_name = verbose_name_plural = "dashboard"
