from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    name = "apps.reviews"
    verbose_name = "Reviews"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .models import Review
        from .receivers import keep_product_rating_current

        post_save.connect(keep_product_rating_current, sender=Review, dispatch_uid="reviews.rating_on_save")
        post_delete.connect(keep_product_rating_current, sender=Review, dispatch_uid="reviews.rating_on_delete")
