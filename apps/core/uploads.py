import re
import uuid

from django.db import transaction
from django.utils.deconstruct import deconstructible


@deconstructible
class RandomUploadTo:
    """`upload_to` that stores files as <prefix>/<random hex>.<ext>.

    The original filename (which can hold personal data or path tricks) is never kept. It is a class,
    not a closure, so migrations can serialise it: `ImageField(upload_to=RandomUploadTo("avatars"))`.
    """

    def __init__(self, prefix):
        self.prefix = prefix.strip("/")

    def __call__(self, instance, filename):
        match = re.search(r"\.([A-Za-z0-9]{1,5})$", filename or "")
        extension = f".{match.group(1).lower()}" if match else ""
        return f"{self.prefix}/{uuid.uuid4().hex}{extension}"


def delete_file_on_commit(storage, name):
    """Delete a stored file once the surrounding transaction has committed (so a rollback keeps it)."""
    if name:
        transaction.on_commit(lambda: storage.delete(name))
