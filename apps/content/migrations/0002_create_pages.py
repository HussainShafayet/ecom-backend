from django.db import migrations

PAGES = ["home", "newarrival", "flashsale", "best_selling", "feature", "category"]


def create_pages(apps, schema_editor):
    PageContent = apps.get_model("content", "PageContent")
    for page in PAGES:
        PageContent.objects.get_or_create(page=page)


class Migration(migrations.Migration):
    dependencies = [("content", "0001_initial")]

    # One row per page, so the admin already lists them. The API does not need the rows (a missing page is empty).
    operations = [migrations.RunPython(create_pages, migrations.RunPython.noop)]
