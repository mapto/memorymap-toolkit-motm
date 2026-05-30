import regex as re
# import re
from fuzzywuzzy import fuzz


def parse_mmd_taxonomy(path: str) -> dict[str, str]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.rstrip()
            if not s or s.strip().startswith("mindmap") or s.strip().startswith("root"):
                continue
            lines.append(s)

    def extract_label(node: str) -> str:
        m = re.search(r'\["(.+?)"\]', node)
        return m.group(1) if m else node.strip()

    indents = [len(lin) - len(lin.lstrip()) for lin in lines]
    top_indent = min(indents)  # indent level of top-level categories
    # children = {i for i in range(len(lines) - 1) if indents[i + 1] > indents[i]}

    stack = []
    mapping = {}

    for i, line in enumerate(lines):
        indent = indents[i]
        label = extract_label(line.strip())

        while stack and stack[-1][0] >= indent:
            stack.pop()

        stack.append((indent, label))

        # is_leaf = i not in children
        # if is_leaf:

        # find the top-level category by indent, not by stack position
        top_level = next(label for lvl, label in stack if lvl == top_indent)
        mapping[label] = top_level

    return mapping


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
