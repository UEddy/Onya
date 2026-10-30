"""Explore us-gaap facts in the SEC companyfacts dump."""

import json

DEFAULT_PATH = "data/raw/snbr_companyfacts.json"


def load_facts(path="data/raw/snbr_companyfacts.json"):
    """Load the companyfacts JSON document."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_candidates(keywords):
    """Print every concept whose name or label contains any keyword.

    Searches ALL taxonomies (us-gaap, dei, company custom namespace).
    Match is case-insensitive substring. Prints namespace:concept, its
    label, and its unit(s).
    """
    data = load_facts()
    facts = data.get("facts", {})
    lowered = [k.lower() for k in keywords]
    for ns in sorted(facts):
        taxonomy = facts[ns]
        for concept in sorted(taxonomy):
            entry = taxonomy[concept]
            label = entry.get("label", "")
            haystack = f"{concept} {label}".lower()
            if any(k in haystack for k in lowered):
                units = sorted(entry.get("units", {}))
                print(f"{ns}:{concept}: {label} [{', '.join(units)}]")


def show(concept, start="2024-06-01"):
    """Print every fact for a concept with end date on or after start.

    Concept may be "namespace:Concept" (e.g. "us-gaap:NetIncomeLoss");
    a bare name defaults to us-gaap. Includes both duration facts
    (with a start date) and instant facts (without one), sorted by
    end date.
    """
    data = load_facts()
    facts = data.get("facts", {})
    if ":" in concept:
        ns, name = concept.split(":", 1)
    else:
        ns, name = "us-gaap", concept
    entry = facts.get(ns, {}).get(name)
    if entry is None:
        print(f"concept not found: {concept}")
        return
    rows = []
    for unit, unit_facts in entry.get("units", {}).items():
        for fact in unit_facts:
            end = fact.get("end", "")
            if end >= start:
                rows.append((end, fact.get("start", ""), unit, fact))
    rows.sort(key=lambda r: (r[0], r[1]))
    print(f"{ns}:{name}: {entry.get('label', '')}")
    for end, fact_start, unit, fact in rows:
        print(
            f"end={end} start={fact_start} val={fact.get('val')}"
            f" unit={unit} form={fact.get('form')} fp={fact.get('fp')}"
            f" fy={fact.get('fy')} filed={fact.get('filed')}"
        )


KEYWORDS = [
    "LinesOfCredit",
    "LineOfCredit",
    "Borrowing",
    "Revolving",
    "CreditFacility",
    "FinanceLease",
    "Debt",
]

SHOW_CONCEPTS = [
    "us-gaap:OperatingLeaseLiability",
    "us-gaap:LettersOfCreditOutstandingAmount",
    "us-gaap:OperatingLeaseCost",
    "us-gaap:InterestExpense",
    "us-gaap:InterestExpenseNonoperating",
    "us-gaap:NetIncomeLoss",
]


if __name__ == "__main__":
    list_candidates(KEYWORDS)
    for concept in SHOW_CONCEPTS:
        show(concept, start="2025-06-01")
