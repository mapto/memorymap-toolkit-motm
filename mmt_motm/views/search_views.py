from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import translation

from memorymap_toolkit.catalogs import localized_concept_label, localized_event_description

from ..models import Concept, Event, Extraction, Interview, LocationPoint, Person


def person_search(request):
    """Return matching persons as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    persons = Person.objects.filter(
        Q(given_name__icontains=query) | Q(family_name__icontains=query)
    ).order_by("family_name", "given_name")[:10]
    results = [
        {"id": person.pk, "name": f"{person.family_name}, {person.given_name}"}
        for person in persons
    ]
    return JsonResponse(results, safe=False)


def extraction_search(request):
    """Return matching extractions as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    extractions = Extraction.objects.filter(
        Q(identifier__icontains=query) | Q(quote__icontains=query)
        | Q(concepts__translations__label__icontains=query)
    ).distinct().order_by("identifier")[:10]
    results = [
        {
            "id": extraction.pk,
            "label": extraction.identifier or "(no ID)",
            "quote": (extraction.quote[:60] + "…") if len(extraction.quote) > 60 else extraction.quote,
        }
        for extraction in extractions
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
        {"id": interview.pk, "label": interview.archive_id or "(no ID)"}
        for interview in interviews
    ]
    return JsonResponse(results, safe=False)


def concept_search(request):
    """Return matching concepts as JSON for the navbar search."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)
    concepts = Concept.objects.filter(
        translations__label__icontains=query
    ).order_by("translations__label")[:10]
    results = [
        {"id": concept.pk, "label": concept.label or "(no label)"}
        for concept in concepts
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
    ).select_related(
        "timespan", "start_location", "end_location"
    ).distinct().order_by("timespan__start")[:10]
    results = []
    for event in events:
        label = event.description[:40]
        if event.timespan:
            label = f"{event.timespan} — {label}"
        results.append({"id": event.pk, "label": label})
    return JsonResponse(results, safe=False)


def global_search(request):
    """Return localized map-search suggestions and their map filter metadata."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"concepts": [], "places": [], "people": [], "events": []})

    language_code = translation.get_language() or request.LANGUAGE_CODE or "en"
    query_folded = query.casefold()

    concept_results = []
    for concept in Concept.objects.all().order_by("id"):
        label = localized_concept_label(concept, language_code)
        if query_folded in label.casefold():
            concept_results.append({
                "id": concept.pk,
                "label": label,
                "url": reverse("concept_detail", args=[concept.pk]),
                "type": "concept",
            })
        if len(concept_results) == 10:
            break

    places = LocationPoint.objects.filter(
        Q(current_name__icontains=query) | Q(alternate_names__icontains=query)
    ).order_by("current_name")[:10]
    place_results = [
        {
            "id": place.pk,
            "label": place.current_name,
            "url": reverse("location_detail", args=[place.pk]),
            "type": "place",
        }
        for place in places
    ]

    people = Person.objects.filter(
        Q(given_name__icontains=query) | Q(family_name__icontains=query)
    ).order_by("family_name", "given_name")[:10]
    person_results = []
    for person in people:
        event_data = list(
            Event.objects.filter(
                persons=person,
                start_location__location__isnull=False,
                end_location__location__isnull=False,
            )
            .values("id", "start_location_id", "end_location_id")
        )
        person_results.append({
            "id": person.pk,
            "label": f"{person.family_name}, {person.given_name}",
            "url": reverse("person_detail", args=[person.pk]),
            "type": "person",
            "event_ids": [item["id"] for item in event_data],
            "location_ids": sorted({
                location_id
                for item in event_data
                for location_id in (item["start_location_id"], item["end_location_id"])
            }),
        })

    event_results = []
    events = Event.objects.select_related("timespan", "start_location", "end_location").order_by("id")
    for event in events:
        label = localized_event_description(event, language_code)
        if query_folded not in label.casefold():
            continue
        location_ids = [
            location_id for location_id in (event.start_location_id, event.end_location_id)
            if location_id is not None
        ]
        event_results.append({
            "id": event.pk,
            "label": label,
            "url": reverse("event_detail", args=[event.pk]),
            "type": "event",
            "location_ids": location_ids,
        })
        if len(event_results) == 10:
            break

    return JsonResponse({
        "concepts": concept_results,
        "places": place_results,
        "people": person_results,
        "events": event_results,
    })