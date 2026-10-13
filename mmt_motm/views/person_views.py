from django.db.models import Count, Q
from django.http import HttpResponsePermanentRedirect
from django.urls import reverse
from django.views.generic import DetailView, ListView

from ..models import Concept, Extraction, Person
from ..person_identity import deduplicate_people, get_person_representative


class PersonListView(ListView):
    model = Person
    template_name = "mmt_motm/person_list.html"
    context_object_name = "persons"

    def get_queryset(self):
        people = (
            Person.objects.select_related("birth_place", "death_place")
            .annotate(interview_count=Count("interviews_received", distinct=True))
            .order_by("family_name", "given_name", "pk")
        )
        return deduplicate_people(people)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for person in context["persons"]:
            person.top_concepts = list(
                Concept.objects.filter(relates_to_concept__people_mentioned=person)
                .annotate(
                    cnt=Count(
                        "relates_to_concept",
                        filter=Q(relates_to_concept__people_mentioned=person),
                    )
                )
                .order_by("-cnt")[:3]
            )
        return context


class PersonDetailView(DetailView):
    model = Person
    template_name = "mmt_motm/person_detail.html"
    context_object_name = "person"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        representative = get_person_representative(self.object)
        if representative.pk != self.object.pk:
            return HttpResponsePermanentRedirect(
                reverse("person_detail", kwargs={"pk": representative.pk})
            )
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

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
                "relates_to_concept",
                filter=Q(relates_to_concept__people_mentioned=person),
            )
        ).order_by("-mention_count")[:20]
        context["events"] = (
            person.events.select_related(
                "timespan", "start_location", "end_location"
            ).order_by("timespan__start")
        )
        lang_counts = (
            Extraction.objects.filter(people_mentioned=person)
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