import json

from django.db.models import Q, Count, Subquery, OuterRef
from django.http import JsonResponse
from django.urls import reverse
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
    InterviewSerializer, EventSerializer,
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
            ).order_by('timespan__start')
        )
        lang_counts = (
            Extraction.objects.filter(people_mentioned=person)
            .exclude(language="")
            .values("language")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        context["language_summary"] = [
            {"code": lc["language"], "label": Extraction(language=lc["language"]).language_label, "count": lc["count"]}
            for lc in lang_counts
        ]
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        interview = self.object
        lang_counts = (
            interview.extracted_from
            .exclude(language="")
            .values("language")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        context["language_summary"] = [
            {"code": lc["language"], "label": Extraction(language=lc["language"]).language_label, "count": lc["count"]}
            for lc in lang_counts
        ]
        return context


class EventDetailView(DetailView):
    model = Event
    template_name = "mmt_motm/event_detail.html"
    context_object_name = "event"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        context["extractions"] = event.relates_to_event.prefetch_related('concepts').all()
        context["dominant_icon"] = event.lifecycle_icon
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


class LocationMapView(ListView):
    model = LocationPoint
    template_name = "mmt_motm/location_map.html"
    context_object_name = "locations"

    def get_queryset(self):
        dominant_icon = Concept.objects.filter(
            events__start_location=OuterRef('pk'),
            icon__gt=''
        ).values('icon').annotate(cnt=Count('id')).order_by('-cnt').values('icon')[:1]

        return LocationPoint.objects.annotate(
            event_count=Count('events_started', distinct=True) + Count('events_ended', distinct=True),
            dominant_icon=Subquery(dominant_icon)
        ).exclude(location__isnull=True).order_by('current_name')


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

        # Breadcrumb: region hierarchy + concept hierarchy merged
        breadcrumb_items = []
        if loc.region:
            region_chain = []
            node = loc.region
            while node:
                region_chain.append(node)
                node = node.part_of
            region_chain.reverse()
            for r in region_chain:
                breadcrumb_items.append({"label": r.name, "url": None, "icon": "fa-globe"})
        if loc.concept:
            concept_chain = []
            node = loc.concept.parent
            while node:
                concept_chain.append(node)
                node = node.parent
            concept_chain.reverse()
            for c in concept_chain:
                breadcrumb_items.append({
                    "label": c.label,
                    "url": reverse("concept_detail", args=[c.pk]),
                    "icon": c.icon or None,
                })
        context["breadcrumb_items"] = breadcrumb_items

        return context


class LocationTaxonomyView(ListView):
    model = LocationRegion
    template_name = "mmt_motm/location_taxonomy.html"
    context_object_name = "regions"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Build region tree: root regions with subregions and points
        def build_tree(region):
            node = {
                "region": region,
                "points": list(region.points.order_by("current_name")),
                "children": [build_tree(sub) for sub in region.subregions.order_by("name")],
            }
            return node

        roots = LocationRegion.objects.filter(part_of__isnull=True).order_by("name")
        region_tree = [build_tree(r) for r in roots]

        # Locations not belonging to any region
        unassigned = LocationPoint.objects.filter(
            region__isnull=True
        ).order_by("current_name")

        context["region_tree"] = region_tree
        context["unassigned"] = unassigned
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


class SourceCategoryHeatmapView(ListView):
    model = Interview
    template_name = "mmt_motm/source_category_heatmap.html"
    context_object_name = "interviews"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Root concept categories (no parent)
        categories = Concept.objects.filter(parent__isnull=True).order_by('label')
        interviews = Interview.objects.order_by('archive_id')

        # Build root-id lookup: concept_id → root category id
        all_concepts = Concept.objects.values('id', 'parent_id')
        parent_map = {c['id']: c['parent_id'] for c in all_concepts}

        def find_root(cid):
            visited = set()
            while cid and cid not in visited:
                visited.add(cid)
                pid = parent_map.get(cid)
                if pid is None:
                    return cid
                cid = pid
            return cid

        # Count extractions per (interview_id, root_category_id)
        extractions = (
            Extraction.objects.filter(interview__isnull=False)
            .values_list('interview_id', 'concepts__id')
        )
        counts = {}  # (interview_id, root_id) → count
        for interview_id, concept_id in extractions:
            if concept_id is None:
                continue
            root_id = find_root(concept_id)
            key = (interview_id, root_id)
            counts[key] = counts.get(key, 0) + 1

        max_count = max(counts.values()) if counts else 1

        # Build grid: one row per category, one cell per interview
        grid = []
        for cat in categories:
            row_total = sum(counts.get((iv.id, cat.id), 0) for iv in interviews)
            cells = []
            for interview in interviews:
                cells.append(counts.get((interview.id, cat.id), 0))
            grid.append({"category": cat, "cells": cells, "total": row_total})

        # Sort by total count, most frequent first
        grid.sort(key=lambda row: row["total"], reverse=True)

        context["categories"] = categories
        context["interviews"] = interviews
        context["grid"] = grid
        context["max_count"] = max_count
        return context


class LifeJourneyHeatmapView(ListView):
    model = Event
    template_name = "mmt_motm/life_journey_heatmap.html"
    context_object_name = "events"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stages = list(Event.LIFECYCLE_CONFIG.keys())
        stage_labels = {k: v["label"] for k, v in Event.LIFECYCLE_CONFIG.items()}
        stage_colors = {k: v["color"] for k, v in Event.LIFECYCLE_CONFIG.items()}

        interviews = Interview.objects.filter(
            interviewee__isnull=False
        ).select_related("interviewee").order_by("archive_id")

        # Count events per (person_id, lifecycle) via the Event.persons M2M
        event_qs = Event.objects.values_list("persons__id", "lifecycle")
        person_counts = {}
        for person_id, lifecycle in event_qs:
            if person_id is None:
                continue
            key = (person_id, lifecycle or Event.LIFECYCLE_DEFAULT)
            person_counts[key] = person_counts.get(key, 0) + 1

        max_count = max(person_counts.values()) if person_counts else 1

        # Build grid: one row per interview, using interviewee's event counts
        grid = []
        for interview in interviews:
            pid = interview.interviewee_id
            cells = []
            row_total = 0
            for stage in stages:
                c = person_counts.get((pid, stage), 0)
                cells.append(c)
                row_total += c
            if row_total > 0:
                grid.append({"interview": interview, "cells": cells, "total": row_total})

        grid.sort(key=lambda row: row["total"], reverse=True)

        context["stages"] = stages
        context["stage_labels"] = stage_labels
        context["stage_colors"] = stage_colors
        context["grid"] = grid
        context["max_count"] = max_count
        context["stages_json"] = json.dumps(stages)
        context["stage_colors_json"] = json.dumps(stage_colors)
        context["stage_headers"] = [
            {"label": stage_labels[s], "color": stage_colors[s], "icon": Event.LIFECYCLE_CONFIG[s]["icon"]} for s in stages
        ]
        return context


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
        context["quotes"] = quotes.prefetch_related("concepts")
        context["persons"] = Person.objects.filter(
            relates_to_person__concepts=concept
        ).distinct()
        # Build ancestor breadcrumb (excluding self)
        breadcrumb_items = []
        node = concept.parent
        while node:
            breadcrumb_items.append({
                "label": node.label,
                "url": reverse("concept_detail", args=[node.pk]),
                "icon": node.icon or None,
            })
            node = node.parent
        breadcrumb_items.reverse()
        context["breadcrumb_items"] = breadcrumb_items
        return context


class ConceptTaxonomyView(ListView):
    model = Concept
    template_name = "mmt_motm/concept_taxonomy.html"
    context_object_name = "roots"

    def get_queryset(self):
        return Concept.objects.filter(
            parent__isnull=True
        ).prefetch_related("children").order_by("label")
