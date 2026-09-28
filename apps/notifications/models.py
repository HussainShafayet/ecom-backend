"""Which order events send the customer a message — one row, edited in the admin (Notifications > Notification
settings). Every event is on by default: a shop usually wants these; switch one off here to cut SMS cost."""
from django.db import models
from django.db.models import CheckConstraint, Q

SINGLETON_ID = 1


class NotificationSettings(models.Model):
    notify_on_placed = models.BooleanField(default=True, help_text="An order was placed.")
    notify_on_confirmed = models.BooleanField(default=True, help_text="Staff confirmed the order.")
    notify_on_shipped = models.BooleanField(default=True, help_text="The order was shipped.")
    notify_on_delivered = models.BooleanField(default=True, help_text="The order was delivered (e-mail only).")
    notify_on_cancelled = models.BooleanField(default=True, help_text="The order was cancelled.")
    notify_on_refunded = models.BooleanField(default=True, help_text="The order was refunded.")

    class Meta:
        verbose_name = verbose_name_plural = "notification settings"
        constraints = [CheckConstraint(condition=Q(id=SINGLETON_ID), name="notifications_one_settings_row")]

    def __str__(self):
        return "Notification settings"

    @classmethod
    def load(cls):
        """The row, created with the defaults (all on) if the shop has none yet (the admin uses this)."""
        return cls.objects.get_or_create(pk=SINGLETON_ID)[0]

    @classmethod
    def current(cls):
        """The row, or an unsaved one with the defaults: reading the settings never writes."""
        return cls.objects.filter(pk=SINGLETON_ID).first() or cls()

    def save(self, *args, **kwargs):
        self.pk = SINGLETON_ID
        super().save(*args, **kwargs)
