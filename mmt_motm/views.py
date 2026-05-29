from django.db.models import Q, Count, Subquery, OuterRef
from django.http import JsonResponse
from django.views.generic import ListView, DetailView

from rest_framework import viewsets, filters

from .models import (
    Person, LocationPoint, LocationRegion,
    RelationshipType, Relationship, Interview, Event,
    Extraction, Concept, Timespan, URL,
)
from .serializers import (
    PersonSerializer, LocationPointSerializer, LocationRegionSerializer,
    RelationshipTypeSerializer, RelationshipSerializer,
    InterviewSerializer, InterviewDetailSerializer, EventSerializer,
    ExtractionSerializer, ConceptSerializer, TimespanSerializer,
    URLSerializer,
)


class PersonListView(ListView):
    model = Person
    template_name = "mmt_motm/person_list.html"
    context_object_name = "persons"

    def get_queryset(self):
        return Person.objects.annotate(
            interview_count=Count('interviews_received', distinct=True)
        ).order_by('family_name', 'given_name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for person in context['persons']:
            person.top_concepts = list(
                Concept.objects.filter(relates_to_concept__people_mentioned=person)
                .annotate(cnt=Count('relates_to_concept',
                                    filter=Q(relates_to_concept__people_mentioned=person)))
                .order_by('-cnt')[:3]
            )
        return context


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
        context["concepts"] = Concept.objects.filter(
            relates_to_concept__people_mentioned=person
        ).annotate(
            mention_count=Count(
                'relates_to_concept',
                filter=Q(relates_to_concept__people_mentioned=person),
            )
        ).order_by('-mention_count')[:20]
        context["events"] = (
            person.events.select_related(
                'timespan', 'start_location', 'end_location'
            ).annotate(
                dominant_icon=Subquery(
                    Concept.objects.filter(
                        events=OuterRef('pk')
                    ).exclude(icon='').values('icon').annotate(
                        cnt=Count('id')
                    ).order_by('-cnt').values('icon')[:1]
                )
            ).order_by('timespan__start')
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


class EventDetailView(DetailView):
    model = Event
    template_name = "mmt_motm/event_detail.html"
    context_object_name = "event"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        context["extractions"] = event.relates_to_event.prefetch_related('concepts').all()
        icons = event.concepts.exclude(icon='').values('icon').annotate(
            cnt=Count('id')).order_by('-cnt')
        context["dominant_icon"] = icons[0]['icon'] if icons else ''
        return context


class EventListView(ListView):
    model = Event
    template_name = "mmt_motm/event_list.html"
    context_object_name = "events"

    def get_queryset(self):
        return Event.objects.select_related(
            'timespan', 'start_location', 'end_location'
        ).order_by('timespan__start')


class LocationListView(ListView):
    model = LocationPoint
    template_name = "mmt_motm/location_list.html"
    context_object_name = "locations"

    def get_queryset(self):
        # Subquery: dominant icon from events departing this location
        dominant_icon = Concept.objects.filter(
            events__start_location=OuterRef('pk'),
            icon__gt=''
        ).values('icon').annotate(cnt=Count('id')).order_by('-cnt').values('icon')[:1]

        return LocationPoint.objects.select_related('region').annotate(
            event_count=Count('events_started', distinct=True) + Count('events_ended', distinct=True),
            dominant_icon=Subquery(dominant_icon)
        ).order_by('current_name')


class LocationDetailView(DetailView):
    model = LocationPoint
    template_name = "mmt_motm/location_detail.html"
    context_object_name = "location"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loc = self.object
        events = Event.objects.filter(
            Q(start_location=loc) | Q(end_location=loc)
        ).select_related(
            'timespan', 'start_location', 'end_location'
        ).annotate(
            dominant_icon=Subquery(
                Concept.objects.filter(
                    events=OuterRef('pk')
                ).exclude(icon='').values('icon').annotate(
                    cnt=Count('id')
                ).order_by('-cnt').values('icon')[:1]
            )
        ).order_by('timespan__start')
        context["events"] = events
        context["persons_born_here"] = loc.people_born_here.all()
        context["persons_died_here"] = loc.people_died_here.all()

        # Dominant concept icon from departing events
        dominant = Concept.objects.filter(
            events__start_location=loc, icon__gt=''
        ).values('icon').annotate(cnt=Count('id')).order_by('-cnt').first()
        context["dominant_icon"] = dominant['icon'] if dominant else ''

        return context


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


def concept_search(request):
    """Return matching concepts as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    concepts = Concept.objects.filter(
        label__icontains=query
    ).order_by("label")[:10]
    results = [
        {"id": c.pk, "label": c.label or "(no label)"}
        for c in concepts
    ]
    return JsonResponse(results, safe=False)


def event_search(request):
    """Return matching events as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    events = Event.objects.filter(
        Q(description__icontains=query)
        | Q(start_location__current_name__icontains=query)
        | Q(end_location__current_name__icontains=query)
    ).select_related('timespan', 'start_location', 'end_location'
    ).distinct().order_by('timespan__start')[:10]
    results = []
    for e in events:
        label = e.description[:40]
        if e.timespan:
            label = f"{e.timespan} — {label}"
        results.append({"id": e.pk, "label": label})
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


class TimespanViewSet(viewsets.ModelViewSet):
    queryset = Timespan.objects.all()
    serializer_class = TimespanSerializer


class URLViewSet(viewsets.ModelViewSet):
    queryset = URL.objects.all()
    serializer_class = URLSerializer


class ConceptListView(ListView):
    model = Concept
    template_name = "mmt_motm/concept_list.html"
    context_object_name = "concepts"

    def get_queryset(self):
        return Concept.objects.annotate(
            quote_count=Count('relates_to_concept')
        ).order_by('-quote_count')


class ConceptDetailView(DetailView):
    model = Concept
    template_name = "mmt_motm/concept_detail.html"
    context_object_name = "concept"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        concept = self.object
        quotes = concept.relates_to_concept.exclude(quote="")
        context["quotes"] = quotes
        context["persons"] = Person.objects.filter(
            relates_to_person__concepts=concept
        ).distinct()
        # Build ancestor path (excluding self)
        ancestors = []
        node = concept.parent
        while node:
            ancestors.append(node)
            node = node.parent
        ancestors.reverse()
        context["ancestors"] = ancestors
        return context


class ConceptTaxonomyView(ListView):
    model = Concept
    template_name = "mmt_motm/concept_taxonomy.html"
    context_object_name = "roots"

    def get_queryset(self):
        return Concept.objects.filter(
            parent__isnull=True
        ).prefetch_related("children").order_by("label")
