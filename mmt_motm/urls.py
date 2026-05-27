from django.urls import path

from . import views

urlpatterns = [
    path("persons/", views.PersonListView.as_view(), name="person_list"),
    path("persons/<int:pk>/", views.PersonDetailView.as_view(), name="person_detail"),
]
