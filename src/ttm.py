"""Standalone quarters, trailing-twelve-month sums, and instant balances.

Reads facts via ``xbrl.load_facts`` and turns the year-to-date durations in
the SEC companyfacts dump into per-quarter economics for a 52/53-week filer.
"""

from datetime import date, timedelta

from xbrl import load_facts

PERIOD_END = "2025-09-27"

# Company-reported values for reconciliation (exact dollars).
REPORTED = {
    "borrowings": 579_500_000,
    "letters_of_credit": 8_847_000,
    "operating_lease_liabilities": 361_029_000,
    "rent": 106_490_000,
}

TTM_CONCEPTS = [
    ("rent", "us-gaap:OperatingLeaseCost"),
    ("net_income", "us-gaap:NetIncomeLoss"),
    ("interest_expense", "us-gaap:InterestExpenseNonoperating"),
    ("income_tax", "us-gaap:IncomeTaxExpenseBenefit"),
    ("depreciation_amortization", "us-gaap:DepreciationDepletionAndAmortization"),
    ("share_based_comp", "us-gaap:ShareBasedCompensation"),
    ("restructuring", "us-gaap:RestructuringCosts"),
    ("impairments", "us-gaap:AssetImpairmentCharges"),
]

# Longest possible standalone quarter in days (14 weeks: 53-week-year Q4).
QUARTER_DAYS = 100

# (concept, quarter end, direct value, derived value) where a direct 3-month
# fact and a cumulative-minus-prior-cumulative value both exist but differ.
DATA_QUALITY_WARNINGS = []


def _split_concept(concept):
    """Split "namespace:Concept"; a bare name defaults to us-gaap."""
    if ":" in concept:
        return concept.split(":", 1)
    return "us-gaap", concept


def _entry(concept):
    ns, name = _split_concept(concept)
    data = load_facts()
    entry = data.get("facts", {}).get(ns, {}).get(name)
    if entry is None:
        raise ValueError(f"concept not found: {concept}")
    return entry


def _dedup(facts):
    """Deduplicate facts repeated across filings, keeping the latest filed."""
    best = {}
    for fact in facts:
        key = (fact.get("end"), fact.get("start"))
        if key not in best or fact.get("filed", "") >= best[key].get("filed", ""):
            best[key] = fact
    return best


def quarterly(concept):
    """Derive standalone quarter values from duration facts.

    Returns {quarter-end date: standalone value}. A fact whose start is the
    day after the previous quarter end is a 3-month fact and is used
    directly; otherwise the quarter is the year-to-date (or full-year) value
    at that end minus the same-start cumulative value at the previous end
    (Q2 = 6M YTD minus Q1, Q4 = FY minus 9M YTD, ...). When both a direct
    3-month fact and a derived cumulative-minus-prior-cumulative value
    exist and differ, the derived value is used and a data-quality warning
    is recorded in DATA_QUALITY_WARNINGS. Quarters are matched
    by end date, so 52/53-week shifts need no special handling. Ends that
    cannot be isolated to a single quarter are skipped.
    """
    entry = _entry(concept)
    durations = [
        fact
        for unit_facts in entry.get("units", {}).values()
        for fact in unit_facts
        if "start" in fact and "end" in fact
    ]
    by_end = {}
    for (end, start), fact in _dedup(durations).items():
        by_end.setdefault(end, {})[start] = fact["val"]
    ends = sorted(by_end)
    out = {}
    for i, end in enumerate(ends):
        starts = by_end[end]
        prior = ends[i - 1] if i else None
        if prior is None:
            latest = max(starts)
            days = (date.fromisoformat(end) - date.fromisoformat(latest)).days
            if days <= QUARTER_DAYS:
                out[end] = starts[latest]
            continue
        qstart = (date.fromisoformat(prior) + timedelta(days=1)).isoformat()
        if qstart in starts:
            direct = starts[qstart]
            common_direct = sorted(set(starts) & set(by_end[prior]), reverse=True)
            if common_direct:
                derived = starts[common_direct[0]] - by_end[prior][common_direct[0]]
                if derived != direct:
                    DATA_QUALITY_WARNINGS.append((concept, end, direct, derived))
                    out[end] = derived
                    continue
            out[end] = direct
            continue
        common = sorted(set(starts) & set(by_end[prior]), reverse=True)
        if not common:
            continue
        ytd_start = common[0]
        out[end] = starts[ytd_start] - by_end[prior][ytd_start]
    return out


def ttm(concept, period_end):
    """Sum the four standalone quarters ending at period_end."""
    quarters = quarterly(concept)
    ends = sorted(quarters)
    if period_end not in quarters:
        raise ValueError(f"no quarterly value for {concept} ending {period_end}")
    idx = ends.index(period_end)
    if idx < 3:
        raise ValueError(
            f"only {idx + 1} quarters available for {concept}"
            f" up to {period_end}, need 4"
        )
    window = ends[idx - 3 : idx + 1]
    for earlier, later in zip(window, window[1:]):
        gap = (date.fromisoformat(later) - date.fromisoformat(earlier)).days
        if not 70 <= gap <= 120:
            raise ValueError(
                f"missing quarter for {concept}: gap from {earlier} to {later}"
            )
    return sum(quarters[end] for end in window)


def instant(concept, period_end):
    """Balance at period_end (latest filed when repeated across filings)."""
    entry = _entry(concept)
    candidates = [
        fact
        for unit_facts in entry.get("units", {}).values()
        for fact in unit_facts
        if fact.get("end") == period_end and "start" not in fact
    ]
    if not candidates:
        raise ValueError(f"no instant fact for {concept} at {period_end}")
    return max(candidates, key=lambda fact: fact.get("filed", ""))["val"]


def _thousands(value):
    return f"{round(value / 1000):,}"


def main():
    DATA_QUALITY_WARNINGS.clear()
    # The revolver balance was tagged us-gaap:LinesOfCreditCurrent only through
    # 2022-12-31; since then the same balance is tagged us-gaap:DebtCurrent.
    rows = [
        ("borrowings", instant("us-gaap:DebtCurrent", PERIOD_END),
         REPORTED["borrowings"]),
        ("letters_of_credit",
         instant("us-gaap:LettersOfCreditOutstandingAmount", PERIOD_END),
         REPORTED["letters_of_credit"]),
        ("operating_lease_liabilities",
         instant("us-gaap:OperatingLeaseLiability", PERIOD_END),
         REPORTED["operating_lease_liabilities"]),
        ("cash",
         instant("us-gaap:CashAndCashEquivalentsAtCarryingValue", PERIOD_END),
         None),
    ]
    for label, concept in TTM_CONCEPTS:
        rows.append((f"{label} (ttm)", ttm(concept, PERIOD_END),
                     REPORTED.get(label)))
    print(f"period_end {PERIOD_END} (values in thousands)")
    print(f"{'item':<30} {'computed':>12} {'reported':>12} {'diff':>12}")
    for label, computed, reported in rows:
        if reported is None:
            print(f"{label:<30} {_thousands(computed):>12}"
                  f" {'-':>12} {'-':>12}")
        else:
            print(f"{label:<30} {_thousands(computed):>12}"
                  f" {_thousands(reported):>12}"
                  f" {_thousands(computed - reported):>12}")
    if DATA_QUALITY_WARNINGS:
        print("data-quality warnings (direct vs derived differ; used derived):")
        for warn_concept, warn_end, direct, derived in DATA_QUALITY_WARNINGS:
            print(f"{warn_concept} {warn_end}: direct={direct} derived={derived}")


if __name__ == "__main__":
    main()
