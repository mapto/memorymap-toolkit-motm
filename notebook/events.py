import regex as re
# import re


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


if __name__ == "__main__":
    event_taxonomy = parse_mmd_taxonomy("../model/tassonomia.mmd")
    events = sorted(set(event_taxonomy.keys()), key=lambda x: -len(x))
    print(event_taxonomy)
