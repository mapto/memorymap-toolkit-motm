"""Compatibility exports for the app's feature-specific view modules.

URL routing and existing imports can continue to use ``mmt_motm.views`` while
the implementations live in smaller domain-focused modules.
"""

from .api_views import (
    ConceptViewSet,
    EventViewSet,
    ExtractionViewSet,
    InterviewViewSet,
    LocationPointViewSet,
    LocationRegionViewSet,
    PersonViewSet,
    RelationshipTypeViewSet,
    RelationshipViewSet,
    TimespanViewSet,
    URLViewSet,
)
from .bulk_actions import BulkMixin
from .concept_views import ConceptDetailView, ConceptListView, ConceptTaxonomyView
from .event_views import EventDetailView, EventListView, LifeJourneyHeatmapView
from .extraction_views import ExtractionDetailView, ExtractionListView
from .interview_views import (
    InterviewDetailView,
    InterviewListView,
    SourceCategoryHeatmapView,
)
from .location_views import (
    LocationDetailView,
    LocationListView,
    LocationMapView,
    LocationTaxonomyView,
)
from .person_views import PersonDetailView, PersonListView
from .search_views import (
    concept_search,
    event_search,
    extraction_search,
    global_search,
    interview_search,
    person_search,
)
from .taxonomy import (
    _build_concept_taxonomy_tree,
    _location_point_for_concept,
    _location_taxonomy_alias,
    _location_taxonomy_key,
    _location_taxonomy_match_excluded,
    _location_taxonomy_synonym_data,
    _match_location_to_go_concept,
)

__all__ = [
    "BulkMixin",
    "ConceptDetailView",
    "ConceptListView",
    "ConceptTaxonomyView",
    "ConceptViewSet",
    "EventDetailView",
    "EventListView",
    "EventViewSet",
    "ExtractionDetailView",
    "ExtractionListView",
    "ExtractionViewSet",
    "InterviewDetailView",
    "InterviewListView",
    "InterviewViewSet",
    "LifeJourneyHeatmapView",
    "LocationDetailView",
    "LocationListView",
    "LocationMapView",
    "LocationPointViewSet",
    "LocationRegionViewSet",
    "LocationTaxonomyView",
    "PersonDetailView",
    "PersonListView",
    "PersonViewSet",
    "RelationshipTypeViewSet",
    "RelationshipViewSet",
    "SourceCategoryHeatmapView",
    "TimespanViewSet",
    "URLViewSet",
    "concept_search",
    "event_search",
    "extraction_search",
    "global_search",
    "interview_search",
    "person_search",
    "_build_concept_taxonomy_tree",
    "_location_point_for_concept",
    "_location_taxonomy_alias",
    "_location_taxonomy_key",
    "_location_taxonomy_match_excluded",
    "_location_taxonomy_synonym_data",
    "_match_location_to_go_concept",
]
