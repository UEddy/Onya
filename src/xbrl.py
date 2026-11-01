"""Explore us-gaap facts in SEC companyfacts dumps."""

import json

DEFAULT_PATH = "data/raw/snbr_companyfacts.json"

SNBR_CIK = "827187"

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

ALLOWED_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


def _cik_10(cik):
    """Normalize a CIK to 10-digit zero-padded form."""
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    if not digits:
        raise ValueError(f"Invalid CIK: {cik!r}")
    return digits.zfill(10)[-10:]


def companyfacts_filename(cik):
    """Cache filename for a CIK's companyfacts dump."""
    return f"companyfacts_{_cik_10(cik)}.json"


def ensure_companyfacts(cik):
    """Download a company's companyfacts dump (cached), return its path.

    SNBR's CIK maps to the existing data/raw/snbr_companyfacts.json so
    SNBR behavior is unchanged; every other CIK downloads via
    edgar.fetch to data/raw/companyfacts_<cik10>.json.
    """
    if _cik_10(cik) == _cik_10(SNBR_CIK):
        return DEFAULT_PATH
    from edgar import fetch  # lazy: edgar requires SEC_USER_AGENT at import

    return str(fetch(COMPANYFACTS_URL.format(cik10=_cik_10(cik)),
                     companyfacts_filename(cik)))


def load_facts(path=None, cik=None):
    """Load a companyfacts JSON document.

    With neither argument (or SNBR's CIK) loads
    data/raw/snbr_companyfacts.json, exactly as before. With another
    CIK, downloads that company's dump via edgar.fetch (cached as
    data/raw/companyfacts_<cik10>.json) and loads it. An explicit path
    always wins.
    """
    if path is None:
        path = ensure_companyfacts(cik) if cik is not None else DEFAULT_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_candidates(keywords, cik=None):
    """Print every concept whose name or label contains any keyword.

    Searches ALL taxonomies (us-gaap, dei, company custom namespace).
    Match is case-insensitive substring. Prints namespace:concept, its
    label, and its unit(s).
    """
    data = load_facts(cik=cik)
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


def show(concept, start="2024-06-01", cik=None):
    """Print every fact for a concept with end date on or after start.

    Concept may be "namespace:Concept" (e.g. "us-gaap:NetIncomeLoss");
    a bare name defaults to us-gaap. Includes both duration facts
    (with a start date) and instant facts (without one), sorted by
    end date.
    """
    data = load_facts(cik=cik)
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
            if fact.get("form") not in ALLOWED_FORMS:
                continue
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
    "Depreciation",
    "Amortization",
    "Impairment",
    "OperatingLeaseImpairment",
    "WriteOff",
]

SHOW_CONCEPTS = [
    "us-gaap:DepreciationDepletionAndAmortization",
    "us-gaap:ImpairmentOfLongLivedAssetsHeldForUse",
    "us-gaap:OperatingLeaseImpairmentLoss",
    "us-gaap:WriteOffOfDeferredDebtIssuanceCost",
    "us-gaap:Depreciation",
]


if __name__ == "__main__":
    list_candidates(KEYWORDS)
    for concept in SHOW_CONCEPTS:
        show(concept, start="2024-06-01")
