from django.db.models import Count
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation
from django.views.generic import DetailView, ListView

from ..models import Concept, Person
from ..person_identity import deduplicate_people
from .taxonomy import (
    _build_concept_taxonomy_tree,
    _location_point_for_concept,
    _person_for_concept,
)


class ConceptListView(ListView):
    model = Concept
    template_name = "mmt_motm/concept_list.html"
    context_object_name = "concepts"

    def get_queryset(self):
        # Word cloud: only concepts linked to at least two quotes
        return (
            Concept.objects.annotate(quote_count=Count("relates_to_concept"))
            .filter(quote_count__gte=2)
            .order_by("-quote_count")
        )


class ConceptDetailView(DetailView):
    model = Concept
    template_name = "mmt_motm/concept_detail.html"
    context_object_name = "concept"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        person = _person_for_concept(self.object)
        if person:
            return redirect("person_detail", pk=person.pk)
        location = _location_point_for_concept(self.object)
        if location:
            return redirect("location_detail", pk=location.pk)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        concept = self.object
        quotes = concept.relates_to_concept.exclude(quote="")
        context["quotes"] = quotes.prefetch_related("concepts")
        context["persons"] = deduplicate_people(Person.objects.filter(
            relates_to_person__concepts=concept
        ).distinct().order_by("family_name", "given_name", "pk"))
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
        language_code = translation.get_language() or "en"
        roots, _, _ = _build_concept_taxonomy_tree(language_code)
        return roots