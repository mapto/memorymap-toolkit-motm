from django.db.models import Count
from django.views.generic import DetailView, ListView

from ..models import Concept, Extraction, Interview


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
            {
                "code": lc["language"],
                "label": Extraction(language=lc["language"]).language_label,
                "count": lc["count"],
            }
            for lc in lang_counts
        ]
        return context


class SourceCategoryHeatmapView(ListView):
    model = Interview
    template_name = "mmt_motm/source_category_heatmap.html"
    context_object_name = "interviews"
    # Only concepts mentioned in at least this many interviews get a row
    min_interviews = 3

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        interviews = Interview.objects.select_related("interviewee").order_by(
            "interviewee__family_name", "interviewee__given_name", "archive_id"
        )

        # Build root-id lookup: concept_id → root concept id
        all_concepts = Concept.objects.values("id", "parent_id")
        parent_map = {c["id"]: c["parent_id"] for c in all_concepts}

        def find_root(cid):
            visited = set()
            while cid and cid not in visited:
                visited.add(cid)
                pid = parent_map.get(cid)
                if pid is None:
                    return cid
                cid = pid
            return cid

        # Count extractions per (interview_id, root_concept_id)
        extractions = (
            Extraction.objects.filter(interview__isnull=False)
            .values_list("interview_id", "concepts__id")
        )
        counts = {}  # (interview_id, root_id) → count
        for interview_id, concept_id in extractions:
            if concept_id is None:
                continue
            root_id = find_root(concept_id)
            key = (interview_id, root_id)
            counts[key] = counts.get(key, 0) + 1

        # Only show root concepts that occur in at least one interview.
        used_root_ids = {root_id for _, root_id in counts if root_id is not None}
        concepts = Concept.objects.filter(
            parent__isnull=True,
            id__in=used_root_ids,
        ).order_by("translations__label")

        max_count = max(counts.values()) if counts else 1

        # Build grid: one row per concept, one cell per interview
        grid = []
        for concept in concepts:
            row_total = sum(counts.get((iv.id, concept.id), 0) for iv in interviews)
            cells = []
            for interview in interviews:
                cells.append(counts.get((interview.id, concept.id), 0))
            # Skip concepts mentioned in fewer than min_interviews interviews
            if sum(1 for count in cells if count) < self.min_interviews:
                continue
            grid.append({"concept": concept, "cells": cells, "total": row_total})

        # Sort by total count, most frequent first
        grid.sort(key=lambda row: row["total"], reverse=True)

        context["concepts"] = concepts
        context["interviews"] = interviews
        context["grid"] = grid
        context["max_count"] = max_count
        return context