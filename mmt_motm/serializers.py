from rest_framework import serializers

from .models import (
    URL,
    LocationRegion,
    LocationPoint,
    Person,
    RelationshipType,
    Relationship,
    Interview,
    Event,
    Extraction,
    Concept,
)


class URLSerializer(serializers.ModelSerializer):
    class Meta:
        model = URL
        fields = "__all__"


class LocationRegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationRegion
        fields = "__all__"


class LocationPointSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = LocationPoint
        fields = [
            "id", "current_name", "alternate_names", "postal_address",
            "description", "location", "wikidata_id", "geonames_id",
            "region", "urls", "latitude", "longitude",
        ]
        extra_kwargs = {"location": {"read_only": True}}

    def create(self, validated_data):
        lat = validated_data.pop("latitude", None)
        lon = validated_data.pop("longitude", None)
        from django.contrib.gis.geos import Point as GeoPoint
        if lat is not None and lon is not None:
            validated_data["location"] = GeoPoint(lon, lat)
        return super().create(validated_data)


class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = "__all__"


class RelationshipTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RelationshipType
        fields = "__all__"


class RelationshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Relationship
        fields = "__all__"


class InterviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interview
        fields = "__all__"


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = "__all__"


class ExtractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Extraction
        fields = "__all__"


class ConceptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Concept
        fields = "__all__"
