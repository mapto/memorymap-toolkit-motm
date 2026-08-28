from rest_framework import serializers

from .models import (
    URL,
    Timespan,
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


class TimespanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Timespan
        fields = "__all__"


class URLSerializer(serializers.ModelSerializer):
    class Meta:
        model = URL
        fields = "__all__"


class LocationRegionSerializer(serializers.ModelSerializer):
    # description is a django-parler translated field on LocationRegion.
    description = serializers.CharField()

    class Meta:
        model = LocationRegion
        fields = "__all__"


class LocationPointSerializer(serializers.ModelSerializer):
    # description is a django-parler translated field on LocationPoint.
    description = serializers.CharField(required=False)
    latitude = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)

    class Meta:
        model = LocationPoint
        fields = [
            "id", "current_name", "alternate_names", "postal_address",
            "description", "location", "wikidata_id", "geonames_id",
            "region", "urls", "latitude", "longitude", "concept",
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
    # description is a django-parler translated field on Person.
    description = serializers.CharField()

    class Meta:
        model = Person
        fields = "__all__"


class RelationshipTypeSerializer(serializers.ModelSerializer):
    # name is a django-parler translated field on RelationshipType.
    name = serializers.CharField()

    class Meta:
        model = RelationshipType
        fields = "__all__"


class RelationshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Relationship
        fields = "__all__"


class ExtractionSerializer(serializers.ModelSerializer):
    # notes is a django-parler translated field on Extraction.
    notes = serializers.CharField()

    class Meta:
        model = Extraction
        fields = "__all__"


class InterviewSerializer(serializers.ModelSerializer):
    # description is a django-parler translated field on Interview.
    description = serializers.CharField()

    class Meta:
        model = Interview
        fields = "__all__"


class InterviewDetailSerializer(serializers.ModelSerializer):
    # description is a django-parler translated field on Interview.
    description = serializers.CharField()
    extracted_from = ExtractionSerializer(many=True, read_only=True)
    interviewee_display = serializers.CharField(source='interviewee', read_only=True)
    interviewer_display = serializers.CharField(source='interviewer', read_only=True)
    
    class Meta:
        model = Interview
        fields = [
            "id", "archive_id", "recording_id", "interview_type", "date", "place",
            "description", "urls", "interviewer", "interviewer_display", "interviewee",
            "interviewee_display", "extracted_from"
        ]


class EventSerializer(serializers.ModelSerializer):
    # description is a django-parler translated field on Event.
    description = serializers.CharField()

    class Meta:
        model = Event
        fields = "__all__"


class ConceptSerializer(serializers.ModelSerializer):
    # label is a django-parler translated field on Concept.
    label = serializers.CharField()

    class Meta:
        model = Concept
        fields = "__all__"
