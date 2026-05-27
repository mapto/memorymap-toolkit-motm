from django.db.models import Q
from django.http import JsonResponse
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


def person_search(request):
    """Return matching persons as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    persons = Person.objects.filter(
        Q(given_name__icontains=query) | Q(family_name__icontains=query)
    ).order_by("family_name", "given_name")[:10]
    results = [
        {"id": p.pk, "name": f"{p.family_name}, {p.given_name}"}
        for p in persons
    ]
    return JsonResponse(results, safe=False)
