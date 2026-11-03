"""Recompute back-test leverage ratios from XBRL (honest partial).

For each company whose agreement was read (terms_<TICKER>.json status
"ok"), walks the saved extraction's definition of each maximum ratio,
maps each component to XBRL facts through ttm.py and xbrl.py, and
compares the result with the ratio the company disclosed. No model
calls: the definitions come from terms_<TICKER>_raw.txt.

A component XBRL cannot provide (company-specific add-backs, pro forma
items, cash netting limits, guarantees) is never guessed. It is listed
in "missing" and the result is "partial", however close the number
lands. Statuses:

    match     every component mapped and within 0.10x of disclosed
    partial   at least one component could not be mapped
    mismatch  every component mapped but more than 0.10x away

"recomputed" on a partial row uses only the mapped components, so it
is a reference point rather than a covenant calculation. It is null
when the ratio cannot be built at all: a secured debt subset, earnings
below zero before the missing add-backs, or no XBRL fact for a core
item (net income, interest, tax, depreciation and amortization, rent).

Saves data/backtest/recompute_<TICKER>.json. Runs locally, downloading
companyfacts into data/raw (not bundled). The answer key is never read.

Usage:
    python src/backtest_recompute.py [TICKER ...]
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttm  # noqa: E402
from edgar import get_cik  # noqa: E402
from score_disclosed import load_disclosed, name_tokens  # noqa: E402
from backtest_terms import (  # noqa: E402
    BACKTEST_DIR,
    SKIP_TICKERS,
    STATUS_OK,
    company_key,
    load_companies,
    pair_covenants,
    raw_terms_path,
    terms_path,
)

MATCH_TOLERANCE = 0.10
PERIOD_END_SLACK_DAYS = 10

STATUS_MATCH = "match"
STATUS_PARTIAL = "partial"
STATUS_MISMATCH = "mismatch"

# Flow concepts tried in order; the first with a four-quarter sum wins.
FLOW_CONCEPTS = {
    "net_income": ("us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"),
    "interest": ("us-gaap:InterestExpense",
                 "us-gaap:InterestExpenseNonoperating",
                 "us-gaap:InterestExpenseDebt",
                 "us-gaap:InterestAndDebtExpense",
                 "us-gaap:InterestIncomeExpenseNonoperatingNet",
                 "us-gaap:InterestIncomeExpenseNet"),
    "tax": ("us-gaap:IncomeTaxExpenseBenefit",),
    "depreciation_amortization": (
        "us-gaap:DepreciationDepletionAndAmortization",
        "us-gaap:DepreciationAmortizationAndAccretionNet",
        "us-gaap:DepreciationAndAmortization"),
    "share_based_comp": ("us-gaap:ShareBasedCompensation",),
    "restructuring": ("us-gaap:RestructuringCharges",
                      "us-gaap:RestructuringCosts"),
    "impairment": ("us-gaap:AssetImpairmentCharges",
                   "us-gaap:ImpairmentOfLongLivedAssetsHeldForUse"),
    "rent": ("us-gaap:OperatingLeaseCost",
             "us-gaap:OperatingLeaseExpense"),
}

# Net-of-income tags report expense as a negative, so use the magnitude.
NET_INTEREST_CONCEPTS = frozenset({
    "us-gaap:InterestIncomeExpenseNonoperatingNet",
    "us-gaap:InterestIncomeExpenseNet",
})

# Without one of these, the earnings figure would not mean EBITDA.
CORE_EARNINGS = frozenset({"net_income", "interest", "tax",
                           "depreciation_amortization", "rent"})

# Depreciation and amortization when no combined tag has four quarters.
DA_PARTS = ("us-gaap:Depreciation", "us-gaap:AmortizationOfIntangibleAssets")

# Debt strategies tried in order: (required concept, optional additions)
# summed at the period end. LineOfCredit is left out because revolver
# balances usually sit inside the long-term debt tags already.
DEBT_STRATEGIES = (
    ("us-gaap:LongTermDebt", ()),
    ("us-gaap:DebtLongtermAndShorttermCombinedAmount", ()),
    ("us-gaap:LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
     ()),
    ("us-gaap:LongTermDebtAndCapitalLeaseObligations",
     ("us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",)),
    ("us-gaap:LongTermDebtNoncurrent", ("us-gaap:LongTermDebtCurrent",)),
)

SHORT_TERM_DEBT = ("us-gaap:ShortTermBorrowings",)

FINANCE_LEASE_TOTAL = "us-gaap:FinanceLeaseLiability"
FINANCE_LEASE_PARTS = ("us-gaap:FinanceLeaseLiabilityNoncurrent",
                       "us-gaap:FinanceLeaseLiabilityCurrent")

CASH_CONCEPTS = (
    "us-gaap:CashAndCashEquivalentsAtCarryingValue",
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)

EARNINGS_TERM_RE = re.compile(
    r"ebitda|operating income|operating cash flow", re.IGNORECASE)
DEBT_TERM_RE = re.compile(r"indebtedness|\bdebt\b", re.IGNORECASE)
SECURED_RE = re.compile(r"\bsecured\b|\bsubordinated\b", re.IGNORECASE)

# Debt components XBRL has no consolidated fact for. Checked first, so
# "Guarantees of borrowed money" is not read as borrowed money.
DEBT_UNAVAILABLE_RE = re.compile(
    r"guarant|letter|\bl/?c\b|banker|swap|hedg|receivable|securitiz"
    r"|off-balance|conditional sale|deferred purchase|disqualified"
    r"|equity repurchase|partnership|\bjv\b|purchase money|compensation",
    re.IGNORECASE)
LEASE_RE = re.compile(r"(capital|finance|financing)\s+lease", re.IGNORECASE)
DEBT_RE = re.compile(
    r"borrowed money|\bbonds?\b|\bnotes?\b|debenture|funded"
    r"|indebtedness|\bdebt\b|principal", re.IGNORECASE)
CASH_RE = re.compile(r"\bcash\b", re.IGNORECASE)
CASH_LIMITED_RE = re.compile(
    r"freely|domestic|excess|qualified|adjustment|unencumbered"
    r"|marketable|permitted invest", re.IGNORECASE)
LIMIT_WORDS_RE = re.compile(
    r"\bcap(ped)?\b|\bexcess\b|\bup to\b|\blesser\b|\bsubject to\b"
    r"|\bmarketable\b|\bpermitted investments\b", re.IGNORECASE)
RENT_RE = re.compile(r"\brent(al)?\b", re.IGNORECASE)
RENT_MULTIPLE_RE = re.compile(r"[x×*]\s*(\d+(?:\.\d+)?)")

# Earnings components, first hit wins. None marks a component that
# looks mappable but is not: a tagged total would overstate it.
EARNINGS_RULES = (
    (re.compile(r"interest income|patronage|dividend", re.I), None),
    (re.compile(r"\bgains?\b|\blosses\b|\bcredits?\b|run.?rate|pro forma"
                r"|synerg|cost savings", re.I), None),
    (re.compile(r"non-?cash\s+(stock|share)|stock|share-?based", re.I),
     "share_based_comp"),
    (re.compile(r"non-?cash\s+restructuring|cash\s+restructuring", re.I),
     None),
    (re.compile(r"non-?cash\s+impairment", re.I), "impairment"),
    (re.compile(r"(deprecia|amortiz).*non-?cash", re.I),
     "depreciation_amortization"),
    (re.compile(r"non-?cash", re.I), None),
    (re.compile(r"net income|net earnings|net loss", re.I), "net_income"),
    (re.compile(r"\binterest\b", re.I), "interest"),
    (re.compile(r"\btax", re.I), "tax"),
    (re.compile(r"deprecia|amortiz", re.I), "depreciation_amortization"),
    (re.compile(r"restructuring", re.I), "restructuring"),
    (re.compile(r"impairment", re.I), "impairment"),
    (re.compile(r"\brent(al)?\b", re.I), "rent"),
)

# Wording that says the definition has more items than were itemized.
OPEN_ENDED_RE = re.compile(
    r"add-?backs?|adjustments?\b|deductions?\b|\bother\b|\bcertain\b"
    r"|\bincluding\b|\bexcluding\b|pro forma|\(a\)|\(i\)|\betc\b",
    re.IGNORECASE)


def _key(term):
    return " ".join(sorted(name_tokens(term)))


def definitions_by_term(parsed):
    """Extracted definitions keyed by normalized term."""
    found = {}
    for definition in parsed.get("definitions") or []:
        term = definition.get("term")
        summary = str(definition.get("formula_summary") or "")
        if term and not summary.lower().startswith("not defined"):
            found[_key(term)] = definition
    return found


def _child(label, definitions, seen):
    """The definition a component label refers to, if it has components."""
    cleaned = re.sub(r"\s*[x×*]\s*\d.*$", "", str(label or ""))
    definition = definitions.get(_key(cleaned))
    if definition is None or _key(cleaned) in seen:
        return None
    return definition if definition.get("components") else None


def classify_earnings(label):
    """Earnings slot for a component label, or None when unavailable."""
    for pattern, slot in EARNINGS_RULES:
        if pattern.search(str(label or "")):
            return slot
    return None


def _walk(definition, definitions, seen, side, plan):
    """Sort a definition's components into the plan, recursing by term."""
    term = definition.get("term") or "?"
    summary = str(definition.get("formula_summary") or "")
    if side == "earnings" and OPEN_ENDED_RE.search(summary):
        plan["missing"].append(
            f"{term}: other adjustments the definition names but the "
            "extraction did not itemize")
    if side == "debt" and LIMIT_WORDS_RE.search(summary):
        plan["limits"].append(term)
    for component in definition.get("components") or []:
        label = str(component.get("label") or "")
        component_side = side
        if side is None or side == "debt":
            if EARNINGS_TERM_RE.search(label):
                component_side = "earnings"
            elif side is None:
                component_side = "debt"
        child = _child(label, definitions, seen)
        if child is not None and (
                component_side == "debt" or EARNINGS_TERM_RE.search(label)):
            seen.add(_key(child.get("term")))
            _walk(child, definitions, seen, component_side, plan)
            continue
        if component_side == "earnings":
            _place_earnings(label, plan)
        else:
            _place_debt(label, plan)


def _place_earnings(label, plan):
    if EARNINGS_TERM_RE.search(label):
        plan["unbuilt_earnings"] = True
        plan["missing"].append(
            f"{label}: not built from XBRL, because its adjustments are "
            "company-specific")
        return
    slot = classify_earnings(label)
    if slot is None:
        plan["missing"].append(f"{label}: not available from XBRL")
        return
    plan["earnings"].add(slot)
    if slot == "depreciation_amortization" and re.search(
            r"non-?cash", label, re.IGNORECASE):
        plan["missing"].append(
            f"{label}: the other non-cash part is not available from XBRL")


def _place_debt(label, plan):
    if SECURED_RE.search(label):
        plan["secured_subset"] = True
        plan["missing"].append(
            f"{label}: XBRL does not split out the secured debt subset")
        return
    if DEBT_UNAVAILABLE_RE.search(label):
        plan["missing"].append(f"{label}: not available from XBRL")
        return
    if LEASE_RE.search(label):
        plan["finance_lease"] = True
        return
    if CASH_RE.search(label):
        plan["cash"] = True
        if CASH_LIMITED_RE.search(label):
            plan["missing"].append(
                f"{label}: netting limits are not available from XBRL, so "
                "balance sheet cash is used without them")
        return
    if RENT_RE.search(label):
        multiple = RENT_MULTIPLE_RE.search(label)
        plan["rent_multiple"] = float(multiple.group(1)) if multiple else 1.0
        return
    if DEBT_RE.search(label):
        plan["debt"] = True
        return
    plan["missing"].append(f"{label}: not available from XBRL")


def build_plan(metric_term, definitions):
    """What a ratio needs: XBRL slots plus the components it cannot have."""
    plan = {"debt": False, "cash": False, "finance_lease": False,
            "rent_multiple": None, "secured_subset": False,
            "unbuilt_earnings": False,
            "earnings": set(), "missing": [], "limits": []}
    definition = definitions.get(_key(metric_term))
    if definition is None or not definition.get("components"):
        plan["missing"].append(
            f"{metric_term}: ratio definition not extracted")
        return plan, False
    _walk(definition, definitions, {_key(metric_term)}, None, plan)
    if plan["earnings"]:
        # EBITDA is built from these whether or not the extraction
        # listed them; EBITDAR lists its rent explicitly.
        plan["earnings"] |= {"net_income", "interest", "tax",
                             "depreciation_amortization"}
    for term in plan["limits"]:
        plan["missing"].append(
            f"{term}: stated limits are not available from XBRL")
    plan["missing"] = list(dict.fromkeys(plan["missing"]))
    return plan, True


def resolve_period_end(period_end, cik):
    """XBRL quarter end at or near period_end (52/53-week filers)."""
    for concept in FLOW_CONCEPTS["net_income"]:
        try:
            quarters = ttm.quarterly(concept, cik=cik)
        except ValueError:
            continue
        if period_end in quarters:
            return period_end
        target = date.fromisoformat(period_end)
        slack = timedelta(days=PERIOD_END_SLACK_DAYS)
        near = sorted(
            (end for end in quarters
             if abs(date.fromisoformat(end) - target) <= slack),
            key=lambda end: abs(date.fromisoformat(end) - target))
        if near:
            return near[0]
    return period_end


def four_quarters(concept, period_end, cik):
    """Four-quarter sum: standalone quarters, else annual plus YTD."""
    try:
        return ttm.ttm(concept, period_end, cik=cik)
    except ValueError:
        return ttm.ttm_from_annual(concept, period_end, cik=cik)


def _first_flow(slot, period_end, cik, flow=four_quarters):
    """([concepts], value) for a slot, or ([], None)."""
    for concept in FLOW_CONCEPTS[slot]:
        try:
            value = flow(concept, period_end, cik)
        except ValueError:
            continue
        if concept in NET_INTEREST_CONCEPTS:
            value = abs(value)
        return [concept], value
    if slot == "depreciation_amortization":
        try:
            return list(DA_PARTS), sum(flow(c, period_end, cik)
                                       for c in DA_PARTS)
        except ValueError:
            pass
    return [], None


def _optional_sum(concepts, period_end, cik, instant):
    """Sum of whichever concepts are tagged: (used, total)."""
    used = []
    total = 0
    for concept in concepts:
        try:
            total += instant(concept, period_end, cik=cik)
        except ValueError:
            continue
        used.append(concept)
    return used, total


def debt_at(period_end, cik, instant=ttm.instant):
    """Balance sheet debt from the first strategy whose main tag exists."""
    for required, optional in DEBT_STRATEGIES:
        try:
            total = instant(required, period_end, cik=cik)
        except ValueError:
            continue
        used, extra = _optional_sum(
            (*optional, *SHORT_TERM_DEBT), period_end, cik, instant)
        return [required, *used], total + extra
    return [], None


def finance_leases_at(period_end, cik, instant=ttm.instant):
    """Finance lease balance: ([concepts], value) or ([], None)."""
    try:
        return ([FINANCE_LEASE_TOTAL],
                instant(FINANCE_LEASE_TOTAL, period_end, cik=cik))
    except ValueError:
        used, total = _optional_sum(
            FINANCE_LEASE_PARTS, period_end, cik, instant)
    return (used, total) if used else ([], None)


def _first_instant(concepts, period_end, cik, instant=ttm.instant):
    for concept in concepts:
        try:
            return concept, instant(concept, period_end, cik=cik)
        except ValueError:
            continue
    return None, None


def compute(plan, period_end, cik, flow=four_quarters, instant=ttm.instant):
    """Apply XBRL facts to a plan: (recomputed, components, missing)."""
    components = []
    missing = list(plan["missing"])

    def add(label, concepts, value):
        components.append({"component": label, "concepts": concepts,
                           "value": value})

    earnings = 0
    earnings_ok = bool(plan["earnings"]) and not plan["unbuilt_earnings"]
    for slot in sorted(plan["earnings"]):
        concepts, value = _first_flow(slot, period_end, cik, flow)
        if value is None:
            missing.append(f"{slot}: no XBRL fact for the four quarters "
                           f"ending {period_end}")
            if slot in CORE_EARNINGS:
                earnings_ok = False
            continue
        add(slot, concepts, value)
        earnings += value

    numerator = 0
    numerator_ok = plan["debt"] and not plan["secured_subset"]
    debt_has_leases = False
    if plan["debt"]:
        concepts, value = debt_at(period_end, cik, instant)
        debt_has_leases = any("CapitalLease" in c for c in concepts)
        if value is None:
            missing.append(f"debt: no XBRL balance at {period_end}")
            numerator_ok = False
        else:
            add("debt", concepts, value)
            numerator += value
    if plan["finance_lease"] and not debt_has_leases:
        concepts, value = finance_leases_at(period_end, cik, instant)
        if value is None:
            missing.append("finance leases: no XBRL balance at "
                           f"{period_end}")
        else:
            add("finance_leases", concepts, value)
            numerator += value
    if plan["cash"]:
        concept, value = _first_instant(
            CASH_CONCEPTS, period_end, cik, instant)
        if value is None:
            missing.append(f"cash: no XBRL balance at {period_end}")
        else:
            add("cash", [concept], -value)
            numerator -= value
    if plan["rent_multiple"] is not None:
        concepts, value = _first_flow("rent", period_end, cik, flow)
        if value is None:
            missing.append("rent: no XBRL fact for the four quarters "
                           f"ending {period_end}")
            numerator_ok = False
        else:
            scaled = value * plan["rent_multiple"]
            add(f"rent x {plan['rent_multiple']:g}", concepts, scaled)
            numerator += scaled

    if not numerator_ok or not earnings_ok or earnings <= 0:
        return None, components, missing
    return round(numerator / earnings, 2), components, missing


def plain_text(text):
    """Extracted labels with en and em dashes as plain hyphens."""
    return str(text).replace("\u2013", "-").replace("\u2014", "-")


def judge(recomputed, disclosed, missing):
    """(status, difference) under the module's status rules."""
    difference = None
    if recomputed is not None and disclosed is not None:
        difference = round(recomputed - disclosed, 2)
    if missing or recomputed is None or disclosed is None:
        return STATUS_PARTIAL, difference
    if abs(difference) <= MATCH_TOLERANCE:
        return STATUS_MATCH, difference
    return STATUS_MISMATCH, difference


def recompute_company(case, backtest_dir=BACKTEST_DIR):
    """The saved record for one company, or None when it has no agreement."""
    ticker = case["ticker"]
    json_path = terms_path(ticker, backtest_dir)
    raw_path = raw_terms_path(ticker, backtest_dir)
    if not json_path.exists() or not raw_path.exists():
        return None
    terms = json.loads(json_path.read_text(encoding="utf-8"))
    if terms.get("status") != STATUS_OK:
        return None
    parsed = json.JSONDecoder().raw_decode(
        raw_path.read_text(encoding="utf-8").strip())[0]
    disclosed = load_disclosed(ticker, backtest_dir) or {}
    pairs, _extras, _flags = pair_covenants(
        parsed.get("financial_covenants") or [],
        disclosed.get("covenants") or [])
    definitions = definitions_by_term(parsed)
    cik = get_cik(company_key(case))
    period_end = resolve_period_end(case["period_end"], cik)

    ratios = []
    for agreement_cov, disclosed_cov in pairs:
        if (agreement_cov or {}).get("direction") != "max":
            continue
        metric_term = (agreement_cov.get("metric_term")
                       or agreement_cov.get("name"))
        plan, _found = build_plan(metric_term, definitions)
        recomputed, components, missing = compute(plan, period_end, cik)
        disclosed_value = (disclosed_cov or {}).get("actual")
        if disclosed_value is None:
            missing.append("the company did not disclose this ratio")
        status, difference = judge(recomputed, disclosed_value, missing)
        ratios.append({
            "name": plain_text(agreement_cov.get("name")),
            "disclosed_name": plain_text((disclosed_cov or {}).get("name")),
            "recomputed": recomputed,
            "disclosed": disclosed_value,
            "difference": difference,
            "status": status,
            "missing": [plain_text(line)
                        for line in dict.fromkeys(missing)],
            "components": components,
        })
    record = {
        "ticker": ticker,
        "period_end": case["period_end"],
        "xbrl_period_end": period_end,
        "agreement_url": terms.get("agreement_url"),
        "ratios": ratios,
    }
    path = Path(backtest_dir) / f"recompute_{ticker}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main(argv=None, backtest_dir=BACKTEST_DIR):
    argv = sys.argv if argv is None else argv
    want = {a.upper() for a in argv[1:]}
    counts = {STATUS_MATCH: 0, STATUS_PARTIAL: 0, STATUS_MISMATCH: 0}
    records = []
    for case in load_companies():
        ticker = case["ticker"].upper()
        if ticker in SKIP_TICKERS or (want and ticker not in want):
            continue
        record = recompute_company(case, backtest_dir)
        if record is None:
            print(f"{ticker}: no agreement read, not recomputed")
            continue
        records.append(record)
        for ratio in record["ratios"]:
            counts[ratio["status"]] += 1
            print(f"{ticker} {ratio['name']}: recomputed "
                  f"{ratio['recomputed']} disclosed {ratio['disclosed']} "
                  f"diff {ratio['difference']} {ratio['status']} "
                  f"({len(ratio['missing'])} missing)")
    print(f"totals: {counts}")
    return records


if __name__ == "__main__":
    main()
