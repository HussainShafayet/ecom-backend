from rest_framework import serializers

from .models import Address

REQUIRED_BY_TYPE = {
    Address.ShippingType.INSIDE_DHAKA: ("area",),
    Address.ShippingType.OUTSIDE_DHAKA: ("division", "district", "thana"),
}
LOCATION_FIELDS = ("area", "division", "district", "thana")


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = ("id", "title", "shipping_type", "address", "area", "division", "district", "thana")
        read_only_fields = ("id",)
        extra_kwargs = {
            name: {"required": False, "allow_blank": True} for name in ("title", *LOCATION_FIELDS)
        }

    def validate(self, attrs):
        # PUT and PATCH are both partial, so check the combination of stored + incoming values.
        merged = {name: getattr(self.instance, name, "") for name in ("shipping_type", *LOCATION_FIELDS)}
        merged.update({name: attrs[name] for name in merged if name in attrs})

        needed = REQUIRED_BY_TYPE[merged["shipping_type"]]
        errors = {name: ["This field is required."] for name in needed if not merged[name].strip()}
        if errors:
            raise serializers.ValidationError(errors)

        # Fields that don't apply to this shipping type are cleared (the frontend can leave stale values).
        for name in LOCATION_FIELDS:
            if name not in needed:
                attrs[name] = ""
        return attrs
