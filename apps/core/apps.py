from django.apps import AppConfig
from django.db.models.signals import post_delete


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Core"

    def ready(self):
        from .models import delete_files_of_deleted_row

        # One receiver for every FileCleanupModel subclass (it filters by isinstance).
        post_delete.connect(delete_files_of_deleted_row, dispatch_uid="core.delete_files_of_deleted_row")
