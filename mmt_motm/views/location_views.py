from django.db.models import Count, OuterRef, Q, Subquery
from django.urls import reverse
from django.utils import translation
from django.views.generic import DetailView, ListView

from ..models import Concept, Event, LocationPoint
from ..person_identity import deduplicate_people
from .taxonomy import _build_concept_taxonomy_tree


class LocationListView(ListView):
    model = LocationPoint
    template_name = "mmt_motm/location_list.html"
    context_object_name = "locations"

    def get_queryset(self):
        # Subquery: dominant icon from events departing this location
        dominant_icon = Concept.objects.filter(
            events__start_location=OuterRef("pk"),
            icon__gt="",
        ).values("icon").annotate(cnt=Count("id")).order_by("-cnt").values("icon")[:1]

        # Word cloud: only places with at least two events
        return (
            LocationPoint.objects.select_related("region")
            .annotate(
                event_count=Count("events_started", distinct=True) + Count("events_ended", distinct=True),
                dominant_icon=Subquery(dominant_icon),
            )
            .filter(event_count__gte=2)
            .order_by("-event_count", "current_name")
        )


class LocationMapView(ListView):
    model = LocationPoint
    template_name = "mmt_motm/location_map.html"
    context_object_name = "locations"

    def get_queryset(self):
        dominant_icon = Concept.objects.filter(
            events__start_location=OuterRef("pk"),
            icon__gt="",
        ).values("icon").annotate(cnt=Count("id")).order_by("-cnt").values("icon")[:1]

        return LocationPoint.objects.annotate(
            event_count=Count("events_started", distinct=True) + Count("events_ended", distinct=True),
            dominant_icon=Subquery(dominant_icon),
        ).exclude(location__isnull=True).order_by("current_name")


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
            "timespan", "start_location", "end_location"
        ).prefetch_related("persons").annotate(
            dominant_icon=Subquery(
                Concept.objects.filter(
                    events=OuterRef("pk")
                ).exclude(icon="").values("icon").annotate(
                    cnt=Count("id")
                ).order_by("-cnt").values("icon")[:1]
            )
        ).order_by("timespan__start")
        context["events"] = list(events)
        for event in context["events"]:
            event.display_persons = deduplicate_people(
                event.persons.order_by("family_name", "given_name", "pk")
            )
        context["persons_born_here"] = deduplicate_people(
            loc.people_born_here.order_by("family_name", "given_name", "pk")
        )
        context["persons_died_here"] = deduplicate_people(
            loc.people_died_here.order_by("family_name", "given_name", "pk")
        )

        # Dominant concept icon from departing events
        dominant = Concept.objects.filter(
            events__start_location=loc, icon__gt=""
        ).values("icon").annotate(cnt=Count("id")).order_by("-cnt").first()
        context["dominant_icon"] = dominant["icon"] if dominant else ""

        # Breadcrumb: region hierarchy + concept hierarchy merged
        breadcrumb_items = []
        if loc.region:
            region_chain = []
            node = loc.region
            while node:
                region_chain.append(node)
                node = node.part_of
            region_chain.reverse()
            for region in region_chain:
                breadcrumb_items.append({"label": region.name, "url": None, "icon": "fa-globe"})
        if loc.concept:
            concept_chain = []
            node = loc.concept.parent
            while node:
                concept_chain.append(node)
                node = node.parent
            concept_chain.reverse()
            for concept in concept_chain:
                breadcrumb_items.append({
                    "label": concept.label,
                    "url": reverse("concept_detail", args=[concept.pk]),
                    "icon": concept.icon or None,
                })
        context["breadcrumb_items"] = breadcrumb_items

        return context


class LocationTaxonomyView(ListView):
    model = Concept
    template_name = "mmt_motm/location_taxonomy.html"
    context_object_name = "roots"

    def get_queryset(self):
        language_code = translation.get_language() or "en"
        _, go_root, matched_orphans = _build_concept_taxonomy_tree(
            language_code
        )
        self._location_unassigned_ids = matched_orphans
        return go_root.taxonomy_children if go_root else []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unassigned"] = LocationPoint.objects.filter(
            concept__isnull=True
        ).exclude(
            pk__in=getattr(self, "_location_unassigned_ids", set())
        ).order_by("current_name")
        return context