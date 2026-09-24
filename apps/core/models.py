from django.db import models

from .uploads import delete_file_on_commit


class FileCleanupModel(models.Model):
    """Abstract base for models with FileField/ImageField columns that must not leave orphans behind.

    A replaced or cleared file, and every file of a deleted row (also when it goes away through a cascade), is
    removed from storage after the transaction commits. The delete side is wired up in `CoreConfig.ready()`.
    """

    class Meta:
        abstract = True

    @classmethod
    def file_fields(cls):
        return [field for field in cls._meta.concrete_fields if isinstance(field, models.FileField)]

    def save(self, *args, **kwargs):
        fields = self.file_fields()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            fields = [field for field in fields if field.name in update_fields or field.attname in update_fields]
        before = {}
        if fields and not self._state.adding and self.pk is not None:
            row = type(self)._base_manager.filter(pk=self.pk).values(*[f.attname for f in fields]).first()
            before = row or {}

        super().save(*args, **kwargs)

        for field in fields:
            old_name = before.get(field.attname)
            if old_name and old_name != getattr(self, field.attname).name:
                delete_file_on_commit(field.storage, old_name)


def delete_files_of_deleted_row(sender, instance, **kwargs):
    if isinstance(instance, FileCleanupModel):
        for field in instance.file_fields():
            delete_file_on_commit(field.storage, getattr(instance, field.attname).name)
