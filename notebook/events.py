import regex as re

# import re
from fuzzywuzzy import fuzz

from taxonomy import parse_mmd_taxonomy  # noqa: F401


def extract_events(row: str, events: list[str]) -> list[str]:
    collected = []
    line = row.strip()
    for e in events:
        if e.lower() in line.lower():
            collected += [e]
            line = re.sub(re.escape(e), "", line, flags=re.IGNORECASE).strip()
    if line:
        collected += [line]
    return collected


# ---------------------------------------------------------------------------
# Life journey classification via fuzzywuzzy
# ---------------------------------------------------------------------------

LIFECYCLE_CANDIDATES = {
    "alte_heimat": "alte Heimat",
    "auswanderung": "Auswanderung",
    "neue_heimat": "neue Heimat",
    "reise_zurueck": "Reise zurueck",
}
LIFECYCLE_THRESHOLD = 70


def classify_lifecycle(*texts):
    """Classify life journey from one or more text values using fuzzy matching.

    Checks each text in order, returns the first strong match (>=threshold).
    Returns one of: alte_heimat, auswanderung, neue_heimat, reise_zurueck, altro.

    >>> classify_lifecycle("Alte Heimat")
    'alte_heimat'
    >>> classify_lifecycle("Alte Heimat Geburt")
    'alte_heimat'
    >>> classify_lifecycle("alter heimant")
    'alte_heimat'
    >>> classify_lifecycle("Auswanderung")
    'auswanderung'
    >>> classify_lifecycle("Neue Heimat")
    'neue_heimat'
    >>> classify_lifecycle("Neue Heimat\\nEinwanderung")
    'neue_heimat'
    >>> classify_lifecycle("Reise zurück")
    'reise_zurueck'
    >>> classify_lifecycle("Reise zurueck")
    'reise_zurueck'
    >>> classify_lifecycle("Bar Mitzvah")
    'altro'
    >>> classify_lifecycle("Transport")
    'altro'
    >>> classify_lifecycle("")
    'altro'
    >>> classify_lifecycle(None)
    'altro'
    >>> classify_lifecycle("", "nan", "Auswanderung")
    'auswanderung'
    >>> classify_lifecycle("irrelevant", "Alte Heimat")
    'alte_heimat'
    """
    for text in texts:
        if not text or str(text).strip() in ("", "nan"):
            continue
        text = str(text).strip()
        best_key = "altro"
        best_score = 0
        for key, candidate in LIFECYCLE_CANDIDATES.items():
            score = fuzz.partial_ratio(candidate.lower(), text.lower())
            if score > best_score:
                best_score = score
                best_key = key
        if best_score >= LIFECYCLE_THRESHOLD:
            return best_key
    return "altro"


if __name__ == "__main__":
    event_taxonomy = parse_mmd_taxonomy("../model/tassonomia.mmd")
    events = sorted(set(event_taxonomy.keys()), key=lambda x: -len(x))
    print(event_taxonomy)
