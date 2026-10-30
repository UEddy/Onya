"""SNBR credit-facility covenant tests.

Builds Consolidated EBITDA / EBITDAR and the Net Leverage and Interest
Coverage ratios for a quarterly reporting period from three inputs:

- ``data/extracted/snbr_covenants.reviewed.json`` (contract thresholds,
  EBITDA definition clauses, and add-back caps),
- ``src/ttm.py`` (XBRL trailing-twelve-month sums and instant balances,
  using its derived-value quarterly logic),
- ``data/extracted/snbr_release_<period_end>.json`` (company-reported TTM
  reconciliation and leverage tables), loaded when the file exists.

All component values are exact US dollars (release ``value_thousands``
figures are multiplied by 1000). When a release line is missing, fall back
to the XBRL value where one exists and note it; never invent a value.
The one exception is "Finance lease obligations": when the release for the
period has no leverage table, carry forward the most recent prior release
value for that line only. Clause (a)(ix) savings use the company-reported
amount when disclosed, otherwise report savings=0 and savings=cap
scenarios when the cap schedule covers the period. Run from the project
root::

    python src/covenant.py [period_end]
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
WARNING_ABS_THRESHOLD = 100_000
WARNING_PCT_THRESHOLD = 0.005
UNVERIFIABLE_LABEL = "unverifiable: requires agent approval"


def load_contract():
    """Load the reviewed covenant extraction (contract schedules)."""
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def load_release(period_end):
    """Load the company-reported release tables, or None when absent."""
    path = PROJECT_ROOT / "data" / "extracted" / f"snbr_release_{period_end}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def try_release_line(release, table, line):
    """Return a release line value in dollars, or None when missing."""
    if not release:
        return None
    for entry in release.get(table, []) or []:
        if entry.get("line") == line:
            val = entry.get("value_thousands")
            if val is None:
                return None
            return int(val * 1000)
    return None


def find_prior_finance_leases(period_end):
    """Return (value_dollars, prior_period_end) for Finance lease obligations.

    Searches data/extracted/snbr_release_*.json for earlier period_ends and
    returns the most recent prior release value, or None when no prior
    value exists.
    """
    extracted = PROJECT_ROOT / "data" / "extracted"
    best_date = None
    best_val = None
    for path in sorted(extracted.glob("snbr_release_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        file_date = data.get("period_end")
        if not file_date:
            stem = path.stem
            prefix = "snbr_release_"
            if stem.startswith(prefix):
                file_date = stem[len(prefix):]
        if not file_date or file_date >= period_end:
            continue
        val = try_release_line(data, "leverage_table_ttm",
                               "Finance lease obligations")
        if val is None:
            continue
        if best_date is None or file_date > best_date:
            best_date = file_date
            best_val = val
    if best_date is None:
        return None
    return best_val, best_date


def release_line(release, table, line):
    """Return a release line value in dollars, raising when missing."""
    val = try_release_line(release, table, line)
    if val is None:
        raise ValueError(f"release line not found: {table}[{line}]")
    return val


def find_proforma_in_release(release):
    """Find company-reported (a)(ix) savings in release tables.

    Returns (line, value_dollars) or None when not disclosed.
    """
    if not release:
        return None
    for table in ("adjusted_ebitda_ttm", "leverage_table_ttm"):
        for entry in release.get(table, []) or []:
            line = entry.get("line") or ""
            low = line.lower()
            if "saving" not in low and "pro forma" not in low:
                continue
            if "saving" not in low and "pro forma" in low:
                if "cost" not in low and "(a)(ix)" not in low and "a(ix)" not in low:
                    continue
            val = entry.get("value_thousands")
            if val is None:
                continue
            return line, int(val * 1000)
    return None


def resolve_period_end(argv=None):
    """Return period_end from argv, defaulting to PERIOD_END."""
    if argv is None:
        argv = sys.argv
    return argv[1] if len(argv) > 1 else PERIOD_END


def allowed_clause_refs(contract):
    """Return every clause_ref and applies_to_clauses value in the contract."""
    allowed = set()
    for definition in contract.get("definitions", []):
        for comp in definition.get("components", []):
            ref = comp.get("clause_ref")
            if ref:
                allowed.add(ref)
    for group in contract.get("cap_groups", []):
        for ref in group.get("applies_to_clauses", []):
            allowed.add(ref)
    return allowed


def definition_terms(contract):
    """Return every defined term in the contract."""
    return {d.get("term") for d in contract.get("definitions", []) if d.get("term")}


def is_valid_clause(clause, allowed_refs, terms):
    """Check a clause label against the reviewed contract."""
    if clause in allowed_refs:
        return True
    if clause.startswith("definition: "):
        return clause[len("definition: "):] in terms
    return False


def is_material_warning(direct, derived):
    """Flag only when diff exceeds $100k AND 0.5% of derived."""
    diff = abs(direct - derived)
    if diff <= WARNING_ABS_THRESHOLD:
        return False
    if derived == 0:
        return True
    return diff > WARNING_PCT_THRESHOLD * abs(derived)


def filter_data_quality_warnings(warnings):
    """Keep only material (direct, derived) mismatches."""
    return [w for w in warnings if is_material_warning(w[2], w[3])]


def ratio_verdicts(numerator, ebitda, ebitdar, interest,
                   lev_threshold, cov_threshold):
    """Compute leverage and coverage ratios, headroom, and pass/fail."""
    lev_ratio = numerator / ebitdar
    cov_ratio = ebitda / interest
    return {
        "net_leverage": {
            "ratio": lev_ratio,
            "headroom": lev_threshold - lev_ratio,
            "pass": lev_ratio <= lev_threshold,
        },
        "interest_coverage": {
            "ratio": cov_ratio,
            "headroom": cov_ratio - cov_threshold,
            "pass": cov_ratio >= cov_threshold,
        },
    }


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
    allowed_refs = allowed_clause_refs(contract)
    terms = definition_terms(contract)
    components = []

    def add(name, value, source, clause, note=""):
        if not is_valid_clause(clause, allowed_refs, terms):
            raise ValueError(
                f"invalid clause label {clause!r}; use a clause_ref from the "
                "reviewed contract or 'definition: <term>'"
            )
        components.append(
            {"name": name, "value": value, "source": source,
             "clause": clause, "note": note}
        )
        return value

    def missing_note(table, line):
        if release is None:
            return (f"no release file for {period_end}; "
                    f"release {table}[{line}] missing, used XBRL fallback")
        return f"release {table}[{line}] missing for {period_end}, used XBRL fallback"

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
    fin_val = try_release_line(release, "leverage_table_ttm", "Finance lease obligations")
    if fin_val is not None:
        finance_leases = add(
            "Finance lease obligations",
            fin_val,
            "release:Finance lease obligations", "(a)(i)",
            "Capitalized Lease Obligations are Indebtedness; company-reported",
        )
    else:
        leverage_missing = release is not None and not release.get("leverage_table_ttm")
        carried = find_prior_finance_leases(period_end) if leverage_missing else None
        if carried is not None:
            carried_val, carried_date = carried
            finance_leases = add(
                "Finance lease obligations",
                carried_val,
                f"estimate: carried forward from {carried_date}", "(a)(i)",
                "immaterial; not disclosed this period",
            )
        else:
            try:
                fin_xbrl = instant("us-gaap:CapitalLeaseObligations", period_end)
            except ValueError:
                raise ValueError(
                    f"release line missing for {period_end}: "
                    "leverage_table_ttm[Finance lease obligations] and no XBRL "
                    "fallback exists; refusing to invent a value"
                )
            finance_leases = add(
                "Finance lease obligations",
                fin_xbrl,
                "xbrl:us-gaap:CapitalLeaseObligations", "(a)(i)",
                missing_note("leverage_table_ttm", "Finance lease obligations")
                + ": us-gaap:CapitalLeaseObligations",
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
    da_val = try_release_line(release, "adjusted_ebitda_ttm", "Depreciation and amortization")
    if da_val is not None:
        try:
            da_xbrl = ttm("us-gaap:DepreciationDepletionAndAmortization", period_end)
            da_note = (
                "release value used; XBRL TTM "
                "us-gaap:DepreciationDepletionAndAmortization "
                f"= ${da_xbrl:,}; release minus XBRL = ${da_val - da_xbrl:,}"
            )
        except ValueError as exc:
            da_note = (
                "release value used; XBRL TTM "
                f"us-gaap:DepreciationDepletionAndAmortization unavailable ({exc})"
            )
        da_release = add(
            "Depreciation and amortization",
            da_val,
            "release:Depreciation and amortization", "(a)(iii)",
            da_note,
        )
    else:
        da_xbrl = ttm("us-gaap:DepreciationDepletionAndAmortization", period_end)
        da_release = add(
            "Depreciation and amortization",
            da_xbrl,
            "xbrl:us-gaap:DepreciationDepletionAndAmortization", "(a)(iii)",
            missing_note("adjusted_ebitda_ttm", "Depreciation and amortization")
            + ": us-gaap:DepreciationDepletionAndAmortization",
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
    other_val = try_release_line(release, "adjusted_ebitda_ttm", "Other non-recurring items")
    if other_val is None:
        raise ValueError(
            f"release line missing for {period_end}: "
            "adjusted_ebitda_ttm[Other non-recurring items] and no XBRL "
            "fallback exists; refusing to invent a value"
        )
    other_nonrec = add(
        "Other non-recurring items",
        other_val,
        "release:Other non-recurring items", "(a)(iv)",
        "subject to the (a)(iv)+(a)(viii) cap",
    )
    asset_val = try_release_line(release, "adjusted_ebitda_ttm", "Asset impairments")
    if asset_val is None:
        raise ValueError(
            f"release line missing for {period_end}: "
            "adjusted_ebitda_ttm[Asset impairments] and no XBRL "
            "fallback exists; refusing to invent a value"
        )
    asset_imp = add(
        "Asset impairments",
        asset_val,
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
        "contract:(a)(iv)+(a)(viii)", "definition: Consolidated EBITDA",
        dis_note,
    )

    ebitda_ex_proforma = (net_loss + tax + interest + da_release + stock_comp
                          + cash_restruct + impairments + other_nonrec + asset_imp
                          - disallowed)

    # -- Rent (EBITDAR) with XBRL fallback --
    rent_val = try_release_line(release, "leverage_table_ttm", "Consolidated rent expense")
    if rent_val is not None:
        try:
            rent_xbrl = ttm("us-gaap:OperatingLeaseCost", period_end)
            rent_note = (
                "release value used; XBRL TTM us-gaap:OperatingLeaseCost "
                f"= ${rent_xbrl:,}; release minus XBRL = ${rent_val - rent_xbrl:,}"
            )
        except ValueError as exc:
            rent_note = (
                f"XBRL TTM us-gaap:OperatingLeaseCost unavailable ({exc}); "
                "release value used"
            )
        rent = add(
            "Consolidated rent expense",
            rent_val,
            "release:Consolidated rent expense", "definition: Consolidated Rent Expense",
            rent_note,
        )
    else:
        rent_xbrl = ttm("us-gaap:OperatingLeaseCost", period_end)
        rent = add(
            "Consolidated rent expense",
            rent_xbrl,
            "xbrl:us-gaap:OperatingLeaseCost", "definition: Consolidated Rent Expense",
            missing_note("leverage_table_ttm", "Consolidated rent expense")
            + ": us-gaap:OperatingLeaseCost",
        )

    # -- (a)(ix) pro forma savings --
    ix_group = find_cap_group(contract, "(a)(ix)")
    if ix_group is None:
        raise ValueError("cap group for (a)(ix) not found")
    ix_cap, ix_note = schedule_lookup(ix_group["schedule"], period_end, "amount_usd")
    disclosed = find_proforma_in_release(release)

    # -- Covenant thresholds (shared by both scenarios) --
    lev = find_covenant(contract, "Net Leverage Ratio")
    assert lev["direction"] == "max"
    lev_threshold, lev_note = schedule_lookup(lev["thresholds"], period_end, "value")
    if lev_threshold is None:
        raise ValueError(f"no Net Leverage Ratio threshold for {period_end}: {lev_note}")
    cov = find_covenant(contract, "Interest Coverage Ratio")
    assert cov["direction"] == "min"
    cov_threshold, cov_note = schedule_lookup(cov["thresholds"], period_end, "value")
    if cov_threshold is None:
        raise ValueError(f"no Interest Coverage Ratio threshold for {period_end}: {cov_note}")

    proforma_scenarios = None
    if disclosed is not None:
        rep_line, reported = disclosed
        if ix_cap is not None and reported > ix_cap:
            proforma = ix_cap
            ix_detail = (
                f"company-reported ${reported:,} exceeds cap ${ix_cap:,} "
                f"({ix_note}); capped at ${ix_cap:,}"
            )
        elif ix_cap is not None:
            proforma = reported
            ix_detail = (
                f"company-reported pro forma savings ${reported:,} within cap "
                f"${ix_cap:,} ({ix_note})"
            )
        else:
            proforma = reported
            ix_detail = (
                f"company-reported pro forma savings ${reported:,}; {ix_note} "
                "(no cap schedule for this period)"
            )
        add("Pro forma cost savings", proforma, f"release:{rep_line}", "(a)(ix)", ix_detail)
        ebitda = ebitda_ex_proforma + proforma
        ebitdar = ebitda + rent
        verdicts = ratio_verdicts(numerator, ebitda, ebitdar, interest,
                                  lev_threshold, cov_threshold)
        lev_ratio = verdicts["net_leverage"]["ratio"]
        lev_headroom = verdicts["net_leverage"]["headroom"]
        cov_ratio = verdicts["interest_coverage"]["ratio"]
        cov_headroom = verdicts["interest_coverage"]["headroom"]
    elif ix_cap is None:
        proforma = 0
        add(
            "Pro forma cost savings",
            0,
            "contract:(a)(ix)", "(a)(ix)",
            f"cap not applicable to this period: {ix_note}; "
            "no pro forma savings included",
        )
        ebitda = ebitda_ex_proforma
        ebitdar = ebitda + rent
        verdicts = ratio_verdicts(numerator, ebitda, ebitdar, interest,
                                  lev_threshold, cov_threshold)
        lev_ratio = verdicts["net_leverage"]["ratio"]
        lev_headroom = verdicts["net_leverage"]["headroom"]
        cov_ratio = verdicts["interest_coverage"]["ratio"]
        cov_headroom = verdicts["interest_coverage"]["headroom"]
    else:
        add(
            "Pro forma cost savings",
            0,
            "contract:(a)(ix)", "(a)(ix)",
            f"schedule covers this period (cap ${ix_cap:,}, {ix_note}) but no "
            "company-reported pro forma savings amount is available; base "
            "includes zero; see proforma_scenarios for savings=cap; "
            f"{UNVERIFIABLE_LABEL}",
        )
        ebitda0 = ebitda_ex_proforma
        ebitdar0 = ebitda0 + rent
        ebitda_cap = ebitda0 + ix_cap
        ebitdar_cap = ebitdar0 + ix_cap
        ebitda = ebitda0
        ebitdar = ebitdar0
        proforma_scenarios = []
        for savings, sce_ebitda, sce_ebitdar in (
            (0, ebitda0, ebitdar0),
            (ix_cap, ebitda_cap, ebitdar_cap),
        ):
            v = ratio_verdicts(numerator, sce_ebitda, sce_ebitdar, interest,
                               lev_threshold, cov_threshold)
            lr = v["net_leverage"]["ratio"]
            lh = v["net_leverage"]["headroom"]
            cr = v["interest_coverage"]["ratio"]
            ch = v["interest_coverage"]["headroom"]
            proforma_scenarios.append({
                "savings": savings,
                "ebitda": sce_ebitda,
                "ebitdar": sce_ebitdar,
                "net_leverage": {
                    "ratio": lr,
                    "ratio_2dp": round(lr, 2),
                    "threshold": lev_threshold,
                    "headroom": lh,
                    "headroom_2dp": round(lh, 2),
                    "pass": lr <= lev_threshold,
                    "note": f"Net Leverage Ratio max {lev_threshold} ({lev_note})",
                },
                "interest_coverage": {
                    "ratio": cr,
                    "ratio_2dp": round(cr, 2),
                    "threshold": cov_threshold,
                    "headroom": ch,
                    "headroom_2dp": round(ch, 2),
                    "pass": cr >= cov_threshold,
                    "note": f"Interest Coverage Ratio min {cov_threshold} ({cov_note})",
                },
                "note": UNVERIFIABLE_LABEL,
            })
        lev_ratio = proforma_scenarios[0]["net_leverage"]["ratio"]
        lev_headroom = proforma_scenarios[0]["net_leverage"]["headroom"]
        cov_ratio = proforma_scenarios[0]["interest_coverage"]["ratio"]
        cov_headroom = proforma_scenarios[0]["interest_coverage"]["headroom"]

    warnings = [
        {"concept": c, "period_end": e, "direct": d, "derived": v}
        for c, e, d, v in filter_data_quality_warnings(DATA_QUALITY_WARNINGS)
    ]

    lev_suffix = ""
    cov_suffix = ""
    if proforma_scenarios is not None:
        lev_suffix = (f"; pro forma savings {UNVERIFIABLE_LABEL}; "
                      "see proforma_scenarios")
        cov_suffix = lev_suffix

    result = {
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
            "note": f"Net Leverage Ratio max {lev_threshold} ({lev_note}){lev_suffix}",
        },
        "interest_coverage": {
            "ratio": cov_ratio,
            "ratio_2dp": round(cov_ratio, 2),
            "threshold": cov_threshold,
            "headroom": cov_headroom,
            "headroom_2dp": round(cov_headroom, 2),
            "pass": cov_ratio >= cov_threshold,
            "note": f"Interest Coverage Ratio min {cov_threshold} ({cov_note}){cov_suffix}",
        },
    }
    if proforma_scenarios is not None:
        result["proforma_scenarios"] = proforma_scenarios
    return result


def _thousands(value):
    """Express an exact-dollar value in thousands (int when exact)."""
    return value // 1000 if value % 1000 == 0 else value / 1000


def print_result(result):
    """Print every component with source, then both covenant verdicts."""
    print(f"period_end {result['period_end']} (values in thousands)")
    for c in result["components"]:
        print(f"{c['name']:<44} {c['value'] / 1000:>12,.0f}"
              f"  {c['source']:<45} {c['clause']:<32} {c['note']}")
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
    scenarios = result.get("proforma_scenarios")
    if scenarios:
        print(f"pro forma savings scenarios ({UNVERIFIABLE_LABEL}):")
        for sc in scenarios:
            slev = sc["net_leverage"]
            scov = sc["interest_coverage"]
            print(f"  savings=${sc['savings']:,}: "
                  f"Net Leverage ratio={slev['ratio']:.2f} "
                  f"headroom={slev['headroom']:.2f} "
                  f"{'PASS' if slev['pass'] else 'FAIL'}; "
                  f"Interest Coverage ratio={scov['ratio']:.2f} "
                  f"headroom={scov['headroom']:.2f} "
                  f"{'PASS' if scov['pass'] else 'FAIL'}")


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
    result = compute(resolve_period_end())
    print_result(result)
    print(f"saved: {save_result(result)}")


if __name__ == "__main__":
    main()
