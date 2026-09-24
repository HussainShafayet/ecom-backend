from django.db.models import Case, F, IntegerField, Prefetch, When
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .favourites import favourite_product_ids
from .filters import ProductQuerySerializer, apply_product_filters, parse_product_query
from .models import Category, Product, ProductVariant
from .queries import NEWEST_FIRST, order_products, visible_products, with_list_fields
from .serializers import CategoryListSerializer, ProductDetailSerializer, ProductListSerializer
from .shop_content import shop_content

# The shop is public. A valid Bearer token only personalises `is_favourite` (an expired one is still a 401, so
# the frontend refreshes it like everywhere else).
TAGS = ["catalog"]


class ProductListBase(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductListSerializer

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        self.favourite_ids = favourite_product_ids(self.request.user, [product.pk for product in page or ()])
        return page

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["favourite_ids"] = getattr(self, "favourite_ids", frozenset())
        return context


@extend_schema(tags=TAGS, summary="List products: filters, sorting, pagination", parameters=[ProductQuerySerializer])
class ProductListView(ProductListBase):
    def get_queryset(self):
        params = parse_product_query(self.request.query_params)
        queryset = apply_product_filters(with_list_fields(visible_products()), params)
        return order_products(queryset, params.get("ordering"))


class FlaggedProductListView(ProductListBase):
    """Products the admin marked with `flag`, newest first unless `ordering` says otherwise."""

    flag = None
    ordering = NEWEST_FIRST

    def get_queryset(self):
        return with_list_fields(visible_products().filter(**{self.flag: True})).order_by(*self.ordering)


@extend_schema(tags=TAGS, summary="New arrival products")
class NewArrivalProductsView(FlaggedProductListView):
    flag = "is_new_arrival"


@extend_schema(tags=TAGS, summary="Best selling products (most orders first)")
class BestSellingProductsView(FlaggedProductListView):
    flag = "is_best_selling"
    ordering = ("-total_orders", *NEWEST_FIRST)


@extend_schema(tags=TAGS, summary="Flash sale products")
class FlashSaleProductsView(FlaggedProductListView):
    flag = "is_flash_sale"


@extend_schema(tags=TAGS, summary="Featured products")
class FeaturedProductsView(FlaggedProductListView):
    flag = "is_featured"


@extend_schema(tags=TAGS, summary="One product with its colours, sizes and media (counts a view)")
class ProductDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        variants = ProductVariant.objects.filter(is_active=True).select_related("color", "size")
        categories = Category.objects.filter(is_active=True).order_by("name", "id")
        return with_list_fields(visible_products()).prefetch_related(
            Prefetch("variants", queryset=variants, to_attr="active_variants"),
            Prefetch("categories", queryset=categories, to_attr="visible_categories"),
            "media",
            "tags",
        )

    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        Product.objects.filter(pk=product.pk).update(total_views=F("total_views") + 1)
        product.total_views += 1
        context = {
            **self.get_serializer_context(),
            "favourite_ids": favourite_product_ids(request.user, [product.pk]),
        }
        return Response(self.get_serializer(product, context=context).data)


@extend_schema(
    tags=TAGS,
    summary="Product name suggestions for the search box",
    parameters=[OpenApiParameter("q", str, description="What the customer typed so far.")],
    responses={200: {"type": "array", "items": {"type": "string"}, "maxItems": 10}},
)
class SearchSuggestionsView(APIView):
    permission_classes = [AllowAny]
    LIMIT = 10

    def get(self, request):
        query = request.query_params.get("q", "").strip()[:100]
        if not query:
            return Response([])
        names = (
            visible_products()
            .filter(name__icontains=query)
            .annotate(starts=Case(When(name__istartswith=query, then=0), default=1, output_field=IntegerField()))
            .order_by("starts", "name")
            .values_list("name", flat=True)[: self.LIMIT * 3]  # room for products that share a name
        )
        return Response(list(dict.fromkeys(names))[: self.LIMIT])


class CategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CategoryListSerializer
    flag = None

    def get_queryset(self):
        queryset = Category.objects.filter(is_active=True)
        if self.flag:
            queryset = queryset.filter(**{self.flag: True})
        return queryset.order_by("name", "id")


@extend_schema(tags=TAGS, summary="All active categories")
class AllCategoriesView(CategoryListView):
    pass


@extend_schema(tags=TAGS, summary="Flash sale categories")
class FlashSaleCategoriesView(CategoryListView):
    flag = "is_flash_sale"


@extend_schema(tags=TAGS, summary="New arrival categories")
class NewArrivalCategoriesView(CategoryListView):
    flag = "is_new_arrival"


@extend_schema(tags=TAGS, summary="Best selling categories")
class BestSellingCategoriesView(CategoryListView):
    flag = "is_best_selling"


@extend_schema(tags=TAGS, summary="Featured categories")
class FeaturedCategoriesView(CategoryListView):
    flag = "is_featured"


class ShopContentSerializer(serializers.Serializer):
    """Only for the schema: the payload is built in `shop_content.shop_content`."""

    categories = serializers.ListField(child=serializers.DictField(), help_text="[{name, slug, children: [same shape]}]")
    brands = serializers.ListField(child=serializers.CharField())
    tags = serializers.ListField(child=serializers.CharField())
    colors = serializers.ListField(child=serializers.DictField(), help_text="[{name, hex_code}]")
    sizes = serializers.ListField(child=serializers.CharField())
    price_range = serializers.DictField(help_text="{min_range, max_range}: what customers pay, lowest and highest.")
    discounts = serializers.ListField(child=serializers.DictField(), help_text="[{discount_type, value}]")


@extend_schema(tags=TAGS, summary="Everything the shop sidebar can filter by", responses=ShopContentSerializer)
class ShopContentView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(shop_content())
