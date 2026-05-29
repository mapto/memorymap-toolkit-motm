from django.urls import path, include

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"persons", views.PersonViewSet, basename="api-person")
router.register(r"locations", views.LocationPointViewSet, basename="api-location")
router.register(r"regions", views.LocationRegionViewSet, basename="api-region")
router.register(r"relationship-types", views.RelationshipTypeViewSet, basename="api-relationshiptype")
router.register(r"relationships", views.RelationshipViewSet, basename="api-relationship")
router.register(r"interviews", views.InterviewViewSet, basename="api-interview")
router.register(r"events", views.EventViewSet, basename="api-event")
router.register(r"extractions", views.ExtractionViewSet, basename="api-extraction")
router.register(r"concepts", views.ConceptViewSet, basename="api-concept")
router.register(r"timespans", views.TimespanViewSet, basename="api-timespan")
router.register(r"urls", views.URLViewSet, basename="api-url")

urlpatterns = [
    path("persons/", views.PersonListView.as_view(), name="person_list"),
    path("persons/<int:pk>/", views.PersonDetailView.as_view(), name="person_detail"),
    path("persons/search/", views.person_search, name="person_search"),
    path("interviews/", views.InterviewListView.as_view(), name="interview_list"),
    path("interviews/<int:pk>/", views.InterviewDetailView.as_view(), name="interview_detail"),
    path("interviews/search/", views.interview_search, name="interview_search"),
    path("extractions/", views.ExtractionListView.as_view(), name="extraction_list"),
    path("extractions/<int:pk>/", views.ExtractionDetailView.as_view(), name="extraction_detail"),
    path("extractions/search/", views.extraction_search, name="extraction_search"),
    path("concepts/", views.ConceptListView.as_view(), name="concept_list"),
    path("concepts/taxonomy/", views.ConceptTaxonomyView.as_view(), name="concept_taxonomy"),
    path("concepts/<int:pk>/", views.ConceptDetailView.as_view(), name="concept_detail"),
    path("concepts/search/", views.concept_search, name="concept_search"),
    path("events/", views.EventListView.as_view(), name="event_list"),
    path("events/<int:pk>/", views.EventDetailView.as_view(), name="event_detail"),
    path("events/search/", views.event_search, name="event_search"),
    path("locations/", views.LocationListView.as_view(), name="location_list"),
    path("locations/map/", views.LocationMapView.as_view(), name="location_map"),
    path("locations/<int:pk>/", views.LocationDetailView.as_view(), name="location_detail"),
    path("api/", include(router.urls)),
]
