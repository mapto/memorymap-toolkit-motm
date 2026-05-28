from django.db.models import Q
from django.http import JsonResponse
from django.views.generic import ListView, DetailView

from rest_framework import viewsets, filters

from .models import (
    Person, LocationPoint, LocationRegion,
    RelationshipType, Relationship, Interview, Event,
    Extraction, Concept,
)
from .serializers import (
    PersonSerializer, LocationPointSerializer, LocationRegionSerializer,
    RelationshipTypeSerializer, RelationshipSerializer,
    InterviewSerializer, InterviewDetailSerializer, EventSerializer,
    ExtractionSerializer, ConceptSerializer,
)


class PersonListView(ListView):
    model = Person
    template_name = "mmt_motm/person_list.html"
    context_object_name = "persons"
    ordering = ["family_name", "given_name"]


class PersonDetailView(DetailView):
    model = Person
    template_name = "mmt_motm/person_detail.html"
    context_object_name = "person"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        person = self.object
        context["interviews_as_interviewer"] = person.interviews_conducted.all()
        context["interviews_as_interviewee"] = person.interviews_received.all()
        context["random_quotes"] = (
            person.relates_to_person.exclude(quote="").order_by("?")[:3]
        )
        return context


class InterviewListView(ListView):
    model = Interview
    template_name = "mmt_motm/interview_list.html"
    context_object_name = "interviews"
    ordering = ["archive_id"]


class InterviewDetailView(DetailView):
    model = Interview
    template_name = "mmt_motm/interview_detail.html"
    context_object_name = "interview"


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


def extraction_search(request):
    """Return matching extractions as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    extractions = Extraction.objects.filter(
        Q(identifier__icontains=query) | Q(quote__icontains=query)
        | Q(concepts__label__icontains=query)
    ).distinct().order_by("identifier")[:10]
    results = [
        {"id": e.pk, "label": e.identifier or "(no ID)", "quote": (e.quote[:60] + "…") if len(e.quote) > 60 else e.quote}
        for e in extractions
    ]
    return JsonResponse(results, safe=False)


def interview_search(request):
    """Return matching interviews as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    interviews = Interview.objects.filter(
        Q(archive_id__icontains=query) | Q(extracted_from__quote__icontains=query)
    ).distinct().order_by("archive_id")[:10]
    results = [
        {"id": i.pk, "label": i.archive_id or "(no ID)"}
        for i in interviews
    ]
    return JsonResponse(results, safe=False)


# ---- DRF API ViewSets ----

class PersonViewSet(viewsets.ModelViewSet):
    queryset = Person.objects.all()
    serializer_class = PersonSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["given_name", "family_name", "identifier"]


class LocationPointViewSet(viewsets.ModelViewSet):
    queryset = LocationPoint.objects.all()
    serializer_class = LocationPointSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["current_name"]


class LocationRegionViewSet(viewsets.ModelViewSet):
    queryset = LocationRegion.objects.all()
    serializer_class = LocationRegionSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]


class RelationshipTypeViewSet(viewsets.ModelViewSet):
    queryset = RelationshipType.objects.all()
    serializer_class = RelationshipTypeSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]


class RelationshipViewSet(viewsets.ModelViewSet):
    queryset = Relationship.objects.all()
    serializer_class = RelationshipSerializer


class InterviewViewSet(viewsets.ModelViewSet):
    queryset = Interview.objects.all()
    serializer_class = InterviewSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["archive_id", "extracted_from__quote"]


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer


class ExtractionListView(ListView):
    model = Extraction
    template_name = "mmt_motm/extraction_list.html"
    context_object_name = "extractions"
    ordering = ["identifier"]


class ExtractionDetailView(DetailView):
    model = Extraction
    template_name = "mmt_motm/extraction_detail.html"
    context_object_name = "extraction"


class ExtractionViewSet(viewsets.ModelViewSet):
    queryset = Extraction.objects.all()
    serializer_class = ExtractionSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["identifier", "quote"]


class ConceptViewSet(viewsets.ModelViewSet):
    queryset = Concept.objects.all()
    serializer_class = ConceptSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["label"]
