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

urlpatterns = [
    path("persons/", views.PersonListView.as_view(), name="person_list"),
    path("persons/<int:pk>/", views.PersonDetailView.as_view(), name="person_detail"),
    path("persons/search/", views.person_search, name="person_search"),
    path("api/", include(router.urls)),
]
