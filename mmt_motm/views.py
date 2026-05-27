from django.views.generic import ListView, DetailView

from .models import Person


class PersonListView(ListView):
    model = Person
    template_name = "mmt_motm/person_list.html"
    context_object_name = "persons"
    ordering = ["family_name", "given_name"]


class PersonDetailView(DetailView):
    model = Person
    template_name = "mmt_motm/person_detail.html"
    context_object_name = "person"
