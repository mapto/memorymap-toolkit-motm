from rest_framework import filters, viewsets

from .bulk_actions import BulkMixin
from ..models import (
    Concept,
    Event,
    Extraction,
    Interview,
    LocationPoint,
    LocationRegion,
    Person,
    Relationship,
    RelationshipType,
    Timespan,
    URL,
)
from ..serializers import (
    ConceptSerializer,
    EventSerializer,
    ExtractionSerializer,
    InterviewSerializer,
    LocationPointSerializer,
    LocationRegionSerializer,
    PersonSerializer,
    RelationshipSerializer,
    RelationshipTypeSerializer,
    TimespanSerializer,
    URLSerializer,
)


class PersonViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["given_name", "family_name", "identifier"]
    bulk_lookup_field = "identifier"


class LocationPointViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = LocationPoint.objects.all()
    serializer_class = LocationPointSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["current_name"]
    bulk_lookup_field = "current_name"


class LocationRegionViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = LocationRegion.objects.all()
    serializer_class = LocationRegionSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    bulk_lookup_field = "name"


class RelationshipTypeViewSet(viewsets.ModelViewSet):
    queryset = RelationshipType.objects.all()
    serializer_class = RelationshipTypeSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["translations__name"]


class RelationshipViewSet(viewsets.ModelViewSet):
    queryset = Relationship.objects.all()
    serializer_class = RelationshipSerializer


class InterviewViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = Interview.objects.all()
    serializer_class = InterviewSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["archive_id", "extracted_from__quote"]
    bulk_lookup_field = "archive_id"


class EventViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    bulk_lookup_field = "description"


class ExtractionViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = Extraction.objects.all()
    serializer_class = ExtractionSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["identifier", "quote"]
    bulk_lookup_field = "identifier"


class ConceptViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = Concept.objects.all()
    serializer_class = ConceptSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["translations__label"]
    bulk_lookup_field = "label"


class TimespanViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = Timespan.objects.all()
    serializer_class = TimespanSerializer
    bulk_lookup_field = "start"


class URLViewSet(BulkMixin, viewsets.ModelViewSet):
    queryset = URL.objects.all()
    serializer_class = URLSerializer
    bulk_lookup_field = "url"