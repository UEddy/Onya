"""SNBR credit-facility covenant tests.

Builds Consolidated EBITDA / EBITDAR and the Net Leverage and Interest
Coverage ratios for a quarterly reporting period from three inputs:

- ``data/extracted/snbr_covenants.reviewed.json`` (contract thresholds,
  EBITDA definition clauses, and add-back caps),
- ``src/ttm.py`` (XBRL trailing-twelve-month sums and instant balances,
  using its derived-value quarterly logic),
- ``data/extracted/snbr_release_<period_end>.json`` (company-reported TTM
  reconciliation and leverage tables).

All component values are exact US dollars (release ``value_thousands``
figures are multiplied by 1000). Run from the project root::

    python src/covenant.py
"""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ttm import DATA_QUALITY_WARNINGS, instant, ttm  # noqa: E402

CONTRACT_PATH = PROJECT_ROOT / "data" / "extracted" / "snbr_covenants.reviewed.json"
CASH_DEDUCTION_THRESHOLD = 40_000_000
PERIOD_END = "2025-09-27"


def load_contract():
    """Load the reviewed covenant extraction (contract schedules)."""
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def load_release(period_end):
    """Load the company-reported release tables for a period end."""
    path = PROJECT_ROOT / "data" / "extracted" / f"snbr_release_{period_end}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def release_line(release, table, line):
    """Return a release line value in dollars (value_thousands * 1000)."""
    for entry in release.get(table, []):
        if entry.get("line") == line:
            val = entry.get("value_thousands")
            if val is None:
                raise ValueError(f"release line has no dollar value: {table}[{line}]")
            return int(val * 1000)
    raise ValueError(f"release line not found: {table}[{line}]")


def find_cap_group(contract, *clauses):
    """Return the cap group whose applies_to_clauses covers all `clauses`.

    Matched by applies_to_clauses, never by id.
    """
    wanted = set(clauses)
    for group in contract.get("cap_groups", []):
        if wanted <= set(group.get("applies_to_clauses", [])):
            return group
    return None


def find_covenant(contract, name):
    """Return a financial covenant by name."""
    for cov in contract.get("financial_covenants", []):
        if cov.get("name") == name:
            return cov
    raise ValueError(f"covenant not found: {name}")


def schedule_lookup(entries, period_end, amount_key):
    """Resolve a schedule (thresholds or caps) for a period end.

    An exact period_end match wins; otherwise the latest applies_after
    entry strictly before period_end covers it. Returns (amount, note)
    where amount is None when the schedule does not cover the period.
    """
    for entry in entries:
        if entry.get("period_end") == period_end:
            return entry[amount_key], f"schedule entry for {period_end}"
    covering = [
        e
        for e in entries
        if e.get("period_end") is None
        and e.get("applies_after") is not None
        and e["applies_after"] < period_end
    ]
    if covering:
        best = max(covering, key=lambda e: e["applies_after"])
        return best[amount_key], f"applies_after {best['applies_after']} covers {period_end}"
    return None, (
        f"schedule has no entry for {period_end}"
        " and no applies_after entry covers it"
    )


def compute(period_end):
    """Build covenant components and test both covenants for period_end."""
    DATA_QUALITY_WARNINGS.clear()
    contract = load_contract()
    release = load_release(period_end)
    components = []

    def add(name, value, source, clause, note=""):
        components.append(
            {"name": name, "value": value, "source": source,
             "clause": clause, "note": note}
        )
        return value

    # -- Numerator: funded indebtedness + operating leases - excess cash --
    borrowings = add(
        "Borrowings under credit facility",
        instant("us-gaap:DebtCurrent", period_end),
        "xbrl:us-gaap:DebtCurrent", "(a)(i)",
        "Consolidated Funded Indebtedness component",
    )
    letters = add(
        "Outstanding letters of credit",
        instant("us-gaap:LettersOfCreditOutstandingAmount", period_end),
        "xbrl:us-gaap:LettersOfCreditOutstandingAmount", "(a)(i)",
        "Consolidated Funded Indebtedness component",
    )
    finance_leases = add(
        "Finance lease obligations",
        release_line(release, "leverage_table_ttm", "Finance lease obligations"),
        "release:Finance lease obligations", "(a)(i)",
        "Capitalized Lease Obligations are Indebtedness; company-reported",
    )
    op_lease_liab = add(
        "Operating lease liabilities",
        instant("us-gaap:OperatingLeaseLiability", period_end),
        "xbrl:us-gaap:OperatingLeaseLiability", "(a)(ii)",
        "ASC 842 operating lease liabilities",
    )
    cash = instant("us-gaap:CashAndCashEquivalentsAtCarryingValue", period_end)
    cash_excess = max(0, cash - CASH_DEDUCTION_THRESHOLD)
    add(
        "Unrestricted US cash in excess of $40,000,000",
        -cash_excess,
        "xbrl:us-gaap:CashAndCashEquivalentsAtCarryingValue", "(a)(iii)",
        f"cash and equivalents = ${cash:,}; excess over "
        f"${CASH_DEDUCTION_THRESHOLD:,} deducted"
        + ("" if cash_excess else "; no excess, deduction is zero"),
    )
    numerator = borrowings + letters + finance_leases + op_lease_liab - cash_excess

    # -- EBITDA --
    net_loss = add(
        "Net loss",
        ttm("us-gaap:NetIncomeLoss", period_end),
        "xbrl:us-gaap:NetIncomeLoss", "base",
        "Consolidated Net Earnings",
    )
    tax = add(
        "Income tax expense (benefit)",
        ttm("us-gaap:IncomeTaxExpenseBenefit", period_end),
        "xbrl:us-gaap:IncomeTaxExpenseBenefit", "(a)(ii)",
        "Consolidated Income Tax Expense",
    )
    interest = add(
        "Interest expense",
        ttm("us-gaap:InterestExpenseNonoperating", period_end),
        "xbrl:us-gaap:InterestExpenseNonoperating", "(a)(i)",
        "proxy for Consolidated Interest Expense (excludes imputed lease "
        "interest not separately tagged)",
    )
    da_release = release_line(release, "adjusted_ebitda_ttm", "Depreciation and amortization")
    da_xbrl = ttm("us-gaap:DepreciationDepletionAndAmortization", period_end)
    da_release = add(
        "Depreciation and amortization",
        da_release,
        "release:Depreciation and amortization", "(a)(iii)",
        f"release value used; XBRL TTM us-gaap:DepreciationDepletionAndAmortization "
        f"= ${da_xbrl:,}; release minus XBRL = ${da_release - da_xbrl:,}",
    )
    stock_comp = add(
        "Stock-based compensation",
        ttm("us-gaap:ShareBasedCompensation", period_end),
        "xbrl:us-gaap:ShareBasedCompensation", "(a)(v)",
        "non-cash stock-based compensation",
    )
    cash_restruct = add(
        "Cash restructuring expenses",
        ttm("us-gaap:RestructuringCosts", period_end),
        "xbrl:us-gaap:RestructuringCosts", "(a)(viii)",
        "subject to the (a)(iv)+(a)(viii) cap",
    )
    impairments = add(
        "Non-cash impairments",
        ttm("us-gaap:AssetImpairmentCharges", period_end),
        "xbrl:us-gaap:AssetImpairmentCharges", "(a)(vi)",
        "non-cash impairment expenses (ttm.py derived-value logic)",
    )
    other_nonrec = add(
        "Other non-recurring items",
        release_line(release, "adjusted_ebitda_ttm", "Other non-recurring items"),
        "release:Other non-recurring items", "(a)(iv)",
        "subject to the (a)(iv)+(a)(viii) cap",
    )
    asset_imp = add(
        "Asset impairments",
        release_line(release, "adjusted_ebitda_ttm", "Asset impairments"),
        "release:Asset impairments", "(a)(vi)",
        "company-reported asset impairments, separate line in the release "
        "reconciliation",
    )

    # -- (a)(iv)+(a)(viii) cap --
    cap_group = find_cap_group(contract, "(a)(iv)", "(a)(viii)")
    if cap_group is None:
        raise ValueError("cap group for (a)(iv)+(a)(viii) not found")
    cap, cap_note = schedule_lookup(cap_group["schedule"], period_end, "amount_usd")
    capped_sum = cash_restruct + other_nonrec
    if cap is None:
        disallowed = 0
        dis_note = f"cap not applicable to this period: {cap_note}; no disallowance"
    else:
        disallowed = max(0, capped_sum - cap)
        dis_note = (
            f"cash restructuring ${cash_restruct:,} + other non-recurring "
            f"${other_nonrec:,} = ${capped_sum:,} vs cap ${cap:,} ({cap_note}); "
            f"excess of ${disallowed:,} disallowed"
        )
    add(
        "Disallowed (a)(iv)+(a)(viii) excess over cap",
        -disallowed,
        "contract:(a)(iv)+(a)(viii)", "(a)(iv)+(a)(viii) cap",
        dis_note,
    )

    # -- (a)(ix) pro forma savings --
    ix_group = find_cap_group(contract, "(a)(ix)")
    if ix_group is None:
        raise ValueError("cap group for (a)(ix) not found")
    ix_cap, ix_note = schedule_lookup(ix_group["schedule"], period_end, "amount_usd")
    if ix_cap is None:
        ix_note = (
            f"cap not applicable to this period: {ix_note}; "
            "no pro forma savings included"
        )
    else:
        ix_note = (
            f"schedule covers this period (cap ${ix_cap:,}, {ix_note}) but no "
            "company-reported pro forma savings amount is available; included as zero"
        )
    proforma = add(
        "Pro forma cost savings",
        0,
        "contract:(a)(ix)", "(a)(ix)",
        ix_note,
    )

    ebitda = (net_loss + tax + interest + da_release + stock_comp
              + cash_restruct + impairments + other_nonrec + asset_imp
              - disallowed + proforma)

    # -- EBITDAR: EBITDA + rent --
    rent_release = release_line(release, "leverage_table_ttm", "Consolidated rent expense")
    try:
        rent_xbrl = ttm("us-gaap:OperatingLeaseCost", period_end)
        rent_note = (
            f"release value used; XBRL TTM us-gaap:OperatingLeaseCost "
            f"= ${rent_xbrl:,}; release minus XBRL = ${rent_release - rent_xbrl:,}"
        )
    except ValueError as exc:
        rent_note = f"XBRL TTM us-gaap:OperatingLeaseCost unavailable ({exc}); release value used"
    rent = add(
        "Consolidated rent expense",
        rent_release,
        "release:Consolidated rent expense", "EBITDAR (b)",
        rent_note,
    )
    ebitdar = ebitda + rent

    # -- Covenant tests --
    lev = find_covenant(contract, "Net Leverage Ratio")
    assert lev["direction"] == "max"
    lev_threshold, lev_note = schedule_lookup(lev["thresholds"], period_end, "value")
    if lev_threshold is None:
        raise ValueError(f"no Net Leverage Ratio threshold for {period_end}: {lev_note}")
    lev_ratio = numerator / ebitdar
    lev_headroom = lev_threshold - lev_ratio

    cov = find_covenant(contract, "Interest Coverage Ratio")
    assert cov["direction"] == "min"
    cov_threshold, cov_note = schedule_lookup(cov["thresholds"], period_end, "value")
    if cov_threshold is None:
        raise ValueError(f"no Interest Coverage Ratio threshold for {period_end}: {cov_note}")
    cov_ratio = ebitda / interest
    cov_headroom = cov_ratio - cov_threshold

    warnings = [
        {"concept": c, "period_end": e, "direct": d, "derived": v}
        for c, e, d, v in DATA_QUALITY_WARNINGS
    ]

    return {
        "period_end": period_end,
        "units": "USD",
        "components": components,
        "data_quality_warnings": warnings,
        "numerator": numerator,
        "numerator_thousands": _thousands(numerator),
        "ebitda": ebitda,
        "ebitda_thousands": _thousands(ebitda),
        "ebitdar": ebitdar,
        "ebitdar_thousands": _thousands(ebitdar),
        "disallowed": disallowed,
        "disallowed_thousands": _thousands(disallowed),
        "net_leverage": {
            "ratio": lev_ratio,
            "ratio_2dp": round(lev_ratio, 2),
            "threshold": lev_threshold,
            "headroom": lev_headroom,
            "headroom_2dp": round(lev_headroom, 2),
            "pass": lev_ratio <= lev_threshold,
            "note": f"Net Leverage Ratio max {lev_threshold} ({lev_note})",
        },
        "interest_coverage": {
            "ratio": cov_ratio,
            "ratio_2dp": round(cov_ratio, 2),
            "threshold": cov_threshold,
            "headroom": cov_headroom,
            "headroom_2dp": round(cov_headroom, 2),
            "pass": cov_ratio >= cov_threshold,
            "note": f"Interest Coverage Ratio min {cov_threshold} ({cov_note})",
        },
    }


def _thousands(value):
    """Express an exact-dollar value in thousands (int when exact)."""
    return value // 1000 if value % 1000 == 0 else value / 1000


def print_result(result):
    """Print every component with source, then both covenant verdicts."""
    print(f"period_end {result['period_end']} (values in thousands)")
    for c in result["components"]:
        print(f"{c['name']:<44} {c['value'] / 1000:>12,.0f}"
              f"  {c['source']:<45} {c['clause']:<22} {c['note']}")
    print(f"{'Numerator':<44} {result['numerator'] / 1000:>12,.0f}")
    print(f"{'EBITDA':<44} {result['ebitda'] / 1000:>12,.0f}")
    print(f"{'EBITDAR':<44} {result['ebitdar'] / 1000:>12,.0f}")
    if result["data_quality_warnings"]:
        print("data-quality warnings (direct vs derived differ; used derived):")
        for w in result["data_quality_warnings"]:
            print(f"{w['concept']} {w['period_end']}: "
                  f"direct={w['direct']} derived={w['derived']}")
    lev = result["net_leverage"]
    cov = result["interest_coverage"]
    print(f"Net Leverage Ratio: ratio={lev['ratio']:.2f} "
          f"threshold={lev['threshold']} headroom={lev['headroom']:.2f} "
          f"{'PASS' if lev['pass'] else 'FAIL'}")
    print(f"Interest Coverage Ratio: ratio={cov['ratio']:.2f} "
          f"threshold={cov['threshold']} headroom={cov['headroom']:.2f} "
          f"{'PASS' if cov['pass'] else 'FAIL'}")


def save_result(result):
    """Save the result to data/results/snbr_<period_end>.json."""
    path = PROJECT_ROOT / "data" / "results" / f"snbr_{result['period_end']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    if not Path("data/raw/snbr_companyfacts.json").exists() and (
            PROJECT_ROOT / "data/raw/snbr_companyfacts.json").exists():
        os.chdir(PROJECT_ROOT)
    result = compute(PERIOD_END)
    print_result(result)
    print(f"saved: {save_result(result)}")


if __name__ == "__main__":
    main()
