"""SNBR covenant cure analysis in dollars.

Reads a filed covenant result (``data/results/snbr_<period_end>.json``) and,
for the base result and each pro forma scenario if present, computes how
much debt must fall or EBITDA must rise to pass each covenant:

- Net Leverage (max): failing -> debt_reduction_needed =
  numerator - threshold x EBITDAR, ebitda_increase_needed =
  numerator / threshold - EBITDAR (EBITDA rise flows 1:1 into EBITDAR
  with rent flat). Passing -> debt_capacity and ebitda_cushion.
- Interest Coverage (min): failing -> ebitda_increase_needed =
  threshold x interest - EBITDA, interest_reduction_needed =
  interest - EBITDA / threshold. Passing -> ebitda_cushion and
  interest_cushion.

Equity cure is reported from the reviewed contract's "equity_cure"
field (present, section, max_uses, limits, how_applied, quote); contracts
without that field fall back to a text scan. It is never assumed.
Run from the project root::

    python src/cure.py [period_end]

Saves the analysis into the result JSON under ``"cure"``.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_PERIOD_END = "2026-04-04"
CONTRACT_PATH = PROJECT_ROOT / "data" / "extracted" / "snbr_covenants.reviewed.json"
EQUITY_CURE_NOT_FOUND = "equity cure: not found in extracted terms"


def resolve_period_end(argv=None):
    """Return period_end from argv, defaulting to DEFAULT_PERIOD_END."""
    if argv is None:
        argv = sys.argv
    return argv[1] if len(argv) > 1 else DEFAULT_PERIOD_END


def load_result(period_end):
    """Load data/results/snbr_<period_end>.json."""
    path = PROJECT_ROOT / "data" / "results" / f"snbr_{period_end}.json"
    if not path.exists():
        raise ValueError(f"result file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract():
    """Load the reviewed covenant extraction (contract schedules)."""
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def component_value(result, name):
    """Return (value, source) for a result component by name."""
    for c in result.get("components", []):
        if c.get("name") == name:
            return c["value"], c.get("source", "")
    raise ValueError(f"component not found in result file: {name}")


def equity_cure_from_field(contract):
    """Return the equity-cure report from the contract's equity_cure field.

    Returns None when the contract has no equity_cure object with a
    "present" flag (legacy contracts fall back to find_equity_cure).
    Otherwise "found" mirrors "present" and the section, max_uses,
    limits, how_applied, and quote come straight from the field.
    """
    field = contract.get("equity_cure")
    if not isinstance(field, dict) or "present" not in field:
        return None
    present = bool(field.get("present"))
    report = {
        "found": present,
        "present": present,
        "section": field.get("section"),
        "max_uses": field.get("max_uses"),
        "limits": field.get("limits"),
        "how_applied": field.get("how_applied"),
        "quote": field.get("quote"),
    }
    if present:
        report["note"] = "equity cure provision in reviewed extraction"
    else:
        report["note"] = EQUITY_CURE_NOT_FOUND
    return report


def find_equity_cure(contract):
    """Return equity-cure provisions found in the contract JSON.

    Legacy text scan for contracts without an equity_cure field: walks
    every string value; a hit must mention both "equity" and "cure"
    (case-insensitive). Returns a list of {"path", "text"} hits, or an
    empty list when the contract has no such provision.
    """
    hits = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, val in node.items():
                walk(val, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, val in enumerate(node):
                walk(val, f"{path}[{i}]")
        elif isinstance(node, str):
            low = node.lower()
            if "cure" in low and "equit" in low:
                hits.append({"path": path, "text": node})

    walk(contract, "")
    return hits


def cure_net_leverage(numerator, ebitdar, threshold, passed, refs):
    """Cure figures for Net Leverage (max threshold)."""
    inputs = {
        "numerator": {"value": numerator, "source": refs["numerator"]},
        "ebitdar": {"value": ebitdar, "source": refs["ebitdar"]},
        "threshold": {"value": threshold, "source": refs["threshold"]},
    }
    if not passed:
        debt_red = numerator - threshold * ebitdar
        ebitda_inc = numerator / threshold - ebitdar
        figures = {
            "debt_reduction_needed": {
                "value": debt_red,
                "formula": "numerator - threshold x EBITDAR",
                "detail": (f"${numerator:,} - {threshold} x "
                           f"${ebitdar:,} = ${debt_red:,.2f}"),
            },
            "ebitda_increase_needed": {
                "value": ebitda_inc,
                "formula": "numerator / threshold - EBITDAR",
                "detail": (f"${numerator:,} / {threshold} - "
                           f"${ebitdar:,} = ${ebitda_inc:,.2f}"),
                "note": ("EBITDA rise flows 1:1 into EBITDAR "
                         "with rent flat"),
            },
        }
        summary = (f"To pass Net Leverage at {threshold}x, debt must fall "
                   f"by ${_fmt(debt_red)} or EBITDA must rise by "
                   f"${_fmt(ebitda_inc)}.")
        status = "fail"
    else:
        capacity = threshold * ebitdar - numerator
        cushion = ebitdar - numerator / threshold
        figures = {
            "debt_capacity": {
                "value": capacity,
                "formula": "threshold x EBITDAR - numerator",
                "detail": (f"{threshold} x ${ebitdar:,} - "
                           f"${numerator:,} = ${capacity:,.2f}"),
            },
            "ebitda_cushion": {
                "value": cushion,
                "formula": "EBITDAR - numerator / threshold",
                "detail": (f"${ebitdar:,} - ${numerator:,} / "
                           f"{threshold} = ${cushion:,.2f}"),
                "note": ("EBITDA could fall by this much before "
                         "breaching, with rent flat"),
            },
        }
        summary = (f"Net Leverage passes at {threshold}x: ${_fmt(capacity)} "
                   f"of additional debt fits, or EBITDA could fall by "
                   f"${_fmt(cushion)} before breaching.")
        status = "pass"
    return {"status": status, "inputs": inputs, "figures": figures,
            "summary": summary}


def cure_interest_coverage(ebitda, interest, threshold, passed, refs):
    """Cure figures for Interest Coverage (min threshold)."""
    inputs = {
        "ebitda": {"value": ebitda, "source": refs["ebitda"]},
        "interest": {"value": interest, "source": refs["interest"]},
        "threshold": {"value": threshold, "source": refs["threshold"]},
    }
    if not passed:
        ebitda_inc = threshold * interest - ebitda
        int_red = interest - ebitda / threshold
        figures = {
            "ebitda_increase_needed": {
                "value": ebitda_inc,
                "formula": "threshold x interest - EBITDA",
                "detail": (f"{threshold} x ${interest:,} - "
                           f"${ebitda:,} = ${ebitda_inc:,.2f}"),
            },
            "interest_reduction_needed": {
                "value": int_red,
                "formula": "interest - EBITDA / threshold",
                "detail": (f"${interest:,} - ${ebitda:,} / "
                           f"{threshold} = ${int_red:,.2f}"),
            },
        }
        summary = (f"To pass Interest Coverage at {threshold}x, EBITDA must "
                   f"rise by ${_fmt(ebitda_inc)} or interest must fall by "
                   f"${_fmt(int_red)}.")
        status = "fail"
    else:
        ebitda_cush = ebitda - threshold * interest
        int_cush = ebitda / threshold - interest
        figures = {
            "ebitda_cushion": {
                "value": ebitda_cush,
                "formula": "EBITDA - threshold x interest",
                "detail": (f"${ebitda:,} - {threshold} x "
                           f"${interest:,} = ${ebitda_cush:,.2f}"),
            },
            "interest_cushion": {
                "value": int_cush,
                "formula": "EBITDA / threshold - interest",
                "detail": (f"${ebitda:,} / {threshold} - "
                           f"${interest:,} = ${int_cush:,.2f}"),
            },
        }
        summary = (f"Interest Coverage passes at {threshold}x: EBITDA "
                   f"exceeds the requirement by ${_fmt(ebitda_cush)}, or "
                   f"interest could rise by ${_fmt(int_cush)} before "
                   f"breaching.")
        status = "pass"
    return {"status": status, "inputs": inputs, "figures": figures,
            "summary": summary}


def cure_scenario(numerator, ebitda, ebitdar, interest, lev, cov,
                  refs, interest_source):
    """Cure analysis for one covenant result (base or one scenario)."""
    lev_threshold = lev.get("threshold")
    cov_threshold = cov.get("threshold")
    if lev_threshold is None or cov_threshold is None:
        raise ValueError("covenant threshold missing from result file")
    return {
        "net_leverage": cure_net_leverage(
            numerator, ebitdar, lev_threshold, bool(lev.get("pass")),
            {"numerator": refs["numerator"], "ebitdar": refs["ebitdar"],
             "threshold": refs["lev_threshold"]}),
        "interest_coverage": cure_interest_coverage(
            ebitda, interest, cov_threshold, bool(cov.get("pass")),
            {"ebitda": refs["ebitda"], "interest": interest_source,
             "threshold": refs["cov_threshold"]}),
    }


def compute(period_end):
    """Build the cure analysis for a filed result period."""
    result = load_result(period_end)
    contract = load_contract()
    interest, interest_src = component_value(result, "Interest expense")
    interest_source = (f"result:components[Interest expense] "
                       f"({interest_src})")
    numerator = result["numerator"]

    base = cure_scenario(
        numerator, result["ebitda"], result["ebitdar"], interest,
        result["net_leverage"], result["interest_coverage"],
        {"numerator": "result:numerator", "ebitda": "result:ebitda",
         "ebitdar": "result:ebitdar",
         "lev_threshold": "result:net_leverage.threshold",
         "cov_threshold": "result:interest_coverage.threshold"},
        interest_source)

    scenarios = []
    for i, sc in enumerate(result.get("proforma_scenarios") or []):
        prefix = f"result:proforma_scenarios[{i}]"
        scenarios.append({
            "savings": sc["savings"],
            **cure_scenario(
                numerator, sc["ebitda"], sc["ebitdar"], interest,
                sc["net_leverage"], sc["interest_coverage"],
                {"numerator": "result:numerator",
                 "ebitda": f"{prefix}.ebitda",
                 "ebitdar": f"{prefix}.ebitdar",
                 "lev_threshold": f"{prefix}.net_leverage.threshold",
                 "cov_threshold": f"{prefix}.interest_coverage.threshold"},
                interest_source),
        })

    equity_cure = equity_cure_from_field(contract)
    if equity_cure is None:
        hits = find_equity_cure(contract)
        if hits:
            equity_cure = {
                "found": True, "provisions": hits,
                "note": "equity cure provision(s) in extracted terms"}
        else:
            equity_cure = {"found": False, "note": EQUITY_CURE_NOT_FOUND}

    cure = {
        "period_end": period_end,
        "units": "USD",
        "interest": {"value": interest, "source": interest_source},
        "base": base,
        "equity_cure": equity_cure,
    }
    if scenarios:
        cure["proforma_scenarios"] = scenarios
    return cure


def _fmt(value):
    return f"{value:,.0f}"


def print_scenario(label, scenario):
    """Print one scenario's figures with formulas, inputs, and summaries."""
    print(f"{label}:")
    for key, title in (("net_leverage", "Net Leverage"),
                       ("interest_coverage", "Interest Coverage")):
        block = scenario[key]
        print(f"  {title} ({block['status'].upper()}):")
        for name, fig in block["figures"].items():
            print(f"    {name} = ${_fmt(fig['value'])}")
            print(f"      formula: {fig['formula']}")
            print(f"      {fig['detail']}")
            for iname, inp in block["inputs"].items():
                val = inp["value"]
                if iname == "threshold":
                    val_str = f"{val}x"
                elif isinstance(val, int):
                    val_str = f"${val:,}"
                elif isinstance(val, float):
                    val_str = f"${val:,.2f}"
                else:
                    val_str = str(val)
                print(f"      input {iname}={val_str} ({inp['source']})")
        print(f"  summary: {block['summary']}")


def print_result(cure):
    """Print the full cure analysis including the equity cure line."""
    print(f"cure analysis for period_end {cure['period_end']} (dollars)")
    iv = cure["interest"]
    print(f"interest=${iv['value']:,} ({iv['source']})")
    print_scenario("base", cure["base"])
    for sc in cure.get("proforma_scenarios") or []:
        print_scenario(f"pro forma savings=${sc['savings']:,}", sc)
    eq = cure["equity_cure"]
    if eq["found"]:
        if "provisions" in eq:
            for prov in eq["provisions"]:
                print(f"equity cure ({prov['path']}): {prov['text']}")
        else:
            print(f"equity cure present: section={eq.get('section') or 'n/a'} "
                  f"max_uses={eq.get('max_uses') or 'n/a'} "
                  f"limits={eq.get('limits') or 'n/a'} "
                  f"how_applied={eq.get('how_applied') or 'n/a'}")
            if eq.get("quote"):
                print(f"equity cure quote: {eq['quote']}")
    else:
        print(EQUITY_CURE_NOT_FOUND)


def save_result(period_end, cure):
    """Save the analysis into the result JSON under "cure"."""
    path = PROJECT_ROOT / "data" / "results" / f"snbr_{period_end}.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["cure"] = cure
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    period_end = resolve_period_end()
    cure = compute(period_end)
    print_result(cure)
    print(f"saved: {save_result(period_end, cure)}")


if __name__ == "__main__":
    main()
