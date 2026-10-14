"""Print a taxonomy summary: python -m taxonomy."""

from __future__ import annotations

from taxonomy.loader import load_taxonomy


if __name__ == "__main__":
    tax = load_taxonomy()
    print(f"Categories: {len(tax.categories)}")
    for k, v in sorted(tax.categories.items()):
        print(f"  {k}: {v['label']} (icon={v['icon']})")
    print(f"Sub-categories: {len(tax.sub_categories)}")
    print(f"Concept-to-category mappings: {tax.concept_to_category}")
