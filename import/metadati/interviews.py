"""Interview creation from metadati records."""

from __future__ import annotations

from api_client import build_interview_payload, get_or_create_url, upsert_interviews
from utils import is_empty
from metadati.values import parse_name
from metadati.people import get_or_create_person


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------


def create_interview(person_id, data):
    """Upsert an Interview from one metadata source record.

    Person-specific parsing stays here, while archive-ID normalization and the
    actual Interview write are shared with the Belege importer.
    """
    interviewer_id = None
    if not is_empty(data.get("interviewer")):
        given, family = parse_name(data["interviewer"])
        interviewer_id = get_or_create_person(
            {
                "given_name": given,
                "family_name": family,
            }
        )

    url_id = get_or_create_url(data.get("url")) if data.get("url") else None

    payload = build_interview_payload(
        data.get("archive_id"),
        interviewee=person_id,
        interviewer=interviewer_id,
        interview_type=data.get("type"),
        interview_date=data.get("date"),
        place=data.get("place"),
        urls=[url_id] if url_id else None,
    )
    if not payload:
        return None

    interview_ids, errors = upsert_interviews([payload])
    for error in errors:
        raise RuntimeError(error)
    return interview_ids.get(payload["archive_id"])
