from rest_framework import serializers


class ProductRefSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
