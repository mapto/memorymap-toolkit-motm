"""Interview creation from metadati records.

Each ``Quelle N`` block of a metadati sheet describes one interview. The sheet
parser stores it as a dict with the keys ``type``, ``place``, ``date``,
``interviewer``, ``archive_id``, and ``url``. This module turns one such dict into
an Interview. The interviewer's name becomes a Person, and the URL is stored
through ``api_client.get_or_create_url``.

The Interview write is shared with the Belege importer. ``build_interview_payload``
normalizes the record, and ``upsert_interviews`` sends it, both from
``api_client``. The payload is keyed by archive ID, so rerunning an import updates
the existing Interview. ``importer.import_record`` calls ``create_interview`` once
for each source in the record.
"""

from __future__ import annotations

from api_client import build_interview_payload, get_or_create_url, upsert_interviews
from utils import is_empty
from metadati.values import parse_name
from metadati.people import get_or_create_person


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------


def create_interview(person_id, data):
    """Upsert the Interview for one source record and return its ID.

    ``person_id`` is the interviewee, and ``data`` is one source dict from the
    sheet parser. Person-specific parsing stays here, while archive-ID
    normalization and the Interview write are shared with the Belege importer.
    The steps run in this order: find or create the interviewer Person, create
    the URL, then upsert the Interview. The first two steps also run when the
    record has no archive ID, so such a record can still create an interviewer
    and a URL without an Interview.

    Returns None when the record has no usable archive ID. Raises RuntimeError
    with the API message when the upsert reports an error.
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
