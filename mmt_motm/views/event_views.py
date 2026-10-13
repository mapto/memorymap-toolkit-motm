import json

from django.db.models import Prefetch
from django.views.generic import DetailView, ListView

from ..models import Event, Interview, Person
from ..person_identity import deduplicate_people


class EventDetailView(DetailView):
    model = Event
    template_name = "mmt_motm/event_detail.html"
    context_object_name = "event"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        context["persons"] = deduplicate_people(
            event.persons.order_by("family_name", "given_name", "pk")
        )
        context["extractions"] = event.relates_to_event.prefetch_related("concepts").all()
        context["dominant_icon"] = event.lifecycle_icon
        return context


class EventListView(ListView):
    model = Event
    template_name = "mmt_motm/event_list.html"
    context_object_name = "events"

    def get_queryset(self):
        persons = Person.objects.order_by("family_name", "given_name", "pk")
        return (
            Event.objects.select_related("timespan", "start_location", "end_location")
            .prefetch_related(Prefetch("persons", queryset=persons))
            .order_by("timespan__start", "timespan__end", "pk")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = list(self.object_list)
        for event in events:
            event.display_persons = deduplicate_people(event.persons.all())
        context["events"] = events
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
                count = person_counts.get((pid, stage), 0)
                cells.append(count)
                row_total += count
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
            {
                "label": stage_labels[stage],
                "color": stage_colors[stage],
                "icon": Event.LIFECYCLE_CONFIG[stage]["icon"],
            }
            for stage in stages
        ]
        return context