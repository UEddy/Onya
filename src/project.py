"""SNBR covenant projection to the next Net Leverage test.

Baseline "no operating change" from a base period result:

- hold numerator, rent, and Onya pre-pro-forma capped EBITDA flat,
- pro forma savings = min(disclosed amount at base, new (a)(ix) cap),
- project the Net Leverage ratio on Onya-strict and company bases,
- cushion = EBITDAR - numerator / next threshold (dollars),
- trend from company-reported Adjusted EBITDA (TTM, before covenant caps),
- quarters_of_cushion = cushion / |avg_decline|, risk HIGH/MEDIUM/LOW,
- backtest like-for-like: the actual scenario with the same pro forma
  savings as projected, plus the actual without savings.

Run from the project root::

    python src/project.py [base_period_end]

Saves ``data/results/snbr_projection_<base>.json``.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import covenant  # noqa: E402

DEFAULT_BASE = "2026-01-03"
RISK_RULE = "HIGH if quarters_of_cushion < 2, MEDIUM if < 4, else LOW"
TREND_LABEL = "company-reported Adjusted EBITDA (TTM, before covenant caps)"


def resolve_base(argv=None):
    """Return base period_end from argv, defaulting to DEFAULT_BASE."""
    if argv is None:
        argv = sys.argv
    return argv[1] if len(argv) > 1 else DEFAULT_BASE


def load_base_result(base):
    """Load data/results/snbr_<base>.json."""
    path = PROJECT_ROOT / "data" / "results" / f"snbr_{base}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract():
    """Load the reviewed covenant extraction."""
    path = PROJECT_ROOT / "data" / "extracted" / "snbr_covenants.reviewed.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_release(period_end):
    """Load data/extracted/snbr_release_<period_end>.json, or None."""
    path = PROJECT_ROOT / "data" / "extracted" / f"snbr_release_{period_end}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_next_test(contract, base):
    """Return (period_end, threshold, note) for the next Net Leverage test.

    The next dated Net Leverage threshold period strictly after base.
    """
    lev = covenant.find_covenant(contract, "Net Leverage Ratio")
    dated = [
        e for e in lev.get("thresholds", [])
        if e.get("period_end") is not None and e["period_end"] > base
    ]
    if not dated:
        raise ValueError(f"no Net Leverage threshold period after {base}")
    nxt = min(dated, key=lambda e: e["period_end"])
    return nxt["period_end"], nxt["value"], f"schedule entry for {nxt['period_end']}"


def get_next_caps(contract, next_test):
    """Return (a)(ix) and (a)(iv)+(a)(viii) caps at next_test.

    Cap groups are matched by applies_to_clauses, never by id.
    Returns dict with cap amounts (None when uncovered) and notes.
    """
    ix_group = covenant.find_cap_group(contract, "(a)(ix)")
    if ix_group is None:
        raise ValueError("cap group for (a)(ix) not found")
    iv_group = covenant.find_cap_group(contract, "(a)(iv)", "(a)(viii)")
    if iv_group is None:
        raise ValueError("cap group for (a)(iv)+(a)(viii) not found")
    ix_cap, ix_note = covenant.schedule_lookup(
        ix_group["schedule"], next_test, "amount_usd")
    iv_cap, iv_note = covenant.schedule_lookup(
        iv_group["schedule"], next_test, "amount_usd")
    return {
        "ix_cap": ix_cap,
        "ix_note": ix_note,
        "iv_viii_cap": iv_cap,
        "iv_viii_note": iv_note,
    }


def component_value(result, name, default=None):
    """Return a component value by name, or default when missing."""
    for c in result.get("components", []):
        if c.get("name") == name:
            return c["value"]
    if default is not None:
        return default
    raise ValueError(f"component not found: {name}")


def disclosed_proforma_at_base(base, base_result):
    """Return (disclosed_dollars, source) for (a)(ix) savings at base."""
    release = load_release(base)
    found = covenant.find_proforma_in_release(release) if release else None
    if found is not None:
        line, value = found
        return value, f"release:{line}"
    comp_val = component_value(base_result, "Pro forma cost savings", default=0)
    if comp_val and comp_val > 0:
        return comp_val, "result:Pro forma cost savings (release undisclosed)"
    return 0, "none disclosed (0)"


def projected_proforma(disclosed, ix_cap):
    """Return min(disclosed, new cap); uncapped disclosed when cap is None."""
    if ix_cap is None:
        return disclosed
    return min(disclosed, ix_cap)


def baseline_inputs(base, base_result):
    """Return flat baseline inputs held from the base period."""
    numerator = base_result["numerator"]
    rent = component_value(base_result, "Consolidated rent expense")
    proforma_comp = component_value(
        base_result, "Pro forma cost savings", default=0)
    ebitda = base_result["ebitda"]
    rec = base_result.get("reconciliation")
    if rec is not None:
        onya_pre = rec["onya_ebitda"]
        company_pre = rec["company_ebitda"]
        company_source = "result:reconciliation"
    else:
        onya_pre = ebitda - (proforma_comp or 0)
        release = load_release(base)
        cov = (covenant.find_covenant_ebitda_in_release(release)
               if release else None)
        if cov is not None:
            company_pre = cov[1]
            company_source = f"release:{cov[0]}"
        else:
            company_pre = onya_pre
            company_source = "fallback:onya_pre (no company EBITDA disclosed)"
    disclosed, disclosed_source = disclosed_proforma_at_base(base, base_result)
    return {
        "numerator": numerator,
        "rent": rent,
        "onya_pre_proforma": onya_pre,
        "company_pre_proforma": company_pre,
        "company_source": company_source,
        "disclosed_proforma": disclosed,
        "disclosed_source": disclosed_source,
    }


def project_ratios(numerator, rent, onya_pre, company_pre, proforma,
                   threshold):
    """Project Net Leverage ratios on Onya-strict and company bases."""
    onya_ebitda = onya_pre + proforma
    onya_ebitdar = onya_ebitda + rent
    company_ebitda = company_pre + proforma
    company_ebitdar = company_ebitda + rent
    onya_ratio = onya_ebitdar and numerator / onya_ebitdar
    company_ratio = company_ebitdar and numerator / company_ebitdar
    return {
        "onya": {
            "ebitda": onya_ebitda,
            "ebitdar": onya_ebitdar,
            "ratio": onya_ratio,
            "ratio_2dp": round(onya_ratio, 2),
            "threshold": threshold,
            "pass": onya_ratio <= threshold,
        },
        "company": {
            "ebitda": company_ebitda,
            "ebitdar": company_ebitdar,
            "ratio": company_ratio,
            "ratio_2dp": round(company_ratio, 2),
            "threshold": threshold,
            "pass": company_ratio <= threshold,
        },
    }


def cushions(projections, numerator, threshold):
    """Return EBITDAR cushions in dollars for both bases."""
    required = numerator / threshold
    return {
        "required_ebitdar": required,
        "onya": projections["onya"]["ebitdar"] - required,
        "company": projections["company"]["ebitdar"] - required,
    }


def load_trend(base):
    """Read company-reported Adjusted EBITDA (TTM) for each period <= base.

    Uses adjusted_ebitda_ttm[Adjusted EBITDA] (value_thousands * 1000),
    before covenant caps. Returns the series label, the series,
    quarter-over-quarter changes, and avg_decline, the mean of the
    negative changes over the last 2 quarters (None when there is no
    negative change in that window).
    """
    extracted = PROJECT_ROOT / "data" / "extracted"
    series = []
    for path in sorted(extracted.glob("snbr_release_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        period = data.get("period_end")
        if not period:
            prefix = "snbr_release_"
            if path.stem.startswith(prefix):
                period = path.stem[len(prefix):]
        if not period or period > base:
            continue
        val = None
        for entry in data.get("adjusted_ebitda_ttm", []) or []:
            if (entry.get("line") or "").strip().lower() == "adjusted ebitda":
                vt = entry.get("value_thousands")
                if vt is not None:
                    val = int(vt * 1000)
                break
        if val is None:
            continue
        series.append({"period_end": period, "adjusted_ebitda": val})
    series.sort(key=lambda r: r["period_end"])
    changes = []
    for prev, cur in zip(series, series[1:]):
        changes.append({
            "from": prev["period_end"],
            "to": cur["period_end"],
            "change": cur["adjusted_ebitda"] - prev["adjusted_ebitda"],
        })
    last_two = changes[-2:] if changes else []
    negatives = [c["change"] for c in last_two if c["change"] < 0]
    avg_decline = (sum(negatives) / len(negatives)) if negatives else None
    return {
        "label": TREND_LABEL,
        "series": series,
        "changes": changes,
        "last_two": last_two,
        "avg_decline": avg_decline,
    }


def quarters_and_risk(cushion, avg_decline):
    """Return (quarters_of_cushion, risk) for one basis.

    Risk rule: HIGH if quarters < 2, MEDIUM if < 4, else LOW. With no
    measured decline (avg_decline None or 0), quarters is None: LOW
    when cushion >= 0, HIGH when already breaching.
    """
    if avg_decline is None or avg_decline == 0:
        if cushion < 0:
            return None, "HIGH"
        return None, "LOW"
    quarters = cushion / abs(avg_decline)
    if quarters < 2:
        return quarters, "HIGH"
    if quarters < 4:
        return quarters, "MEDIUM"
    return quarters, "LOW"


def load_backtest(next_test, proforma):
    """Load the actual next-test result, or None when the file is absent.

    Returns the as-filed actual together with two proforma_scenarios
    entries: like_for_like (savings == proforma, the same assumption
    the projection used) and without_savings (savings == 0). Each is
    None when the file carries no exact match.
    """
    path = PROJECT_ROOT / "data" / "results" / f"snbr_{next_test}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    scenarios = data.get("proforma_scenarios") or []
    like = next((s for s in scenarios if s.get("savings") == proforma),
                None)
    zero = next((s for s in scenarios if s.get("savings") == 0), None)
    return {
        "period_end": data.get("period_end", next_test),
        "numerator": data.get("numerator"),
        "ebitda": data.get("ebitda"),
        "ebitdar": data.get("ebitdar"),
        "net_leverage": data.get("net_leverage"),
        "file_proforma": component_value(
            data, "Pro forma cost savings", default=0),
        "matched_savings": proforma,
        "like_for_like": like,
        "without_savings": zero,
    }


def compute(base):
    """Build the full projection for base period_end."""
    base_result = load_base_result(base)
    contract = load_contract()
    next_test, threshold, threshold_note = find_next_test(contract, base)
    caps = get_next_caps(contract, next_test)
    inputs = baseline_inputs(base, base_result)
    proforma = projected_proforma(inputs["disclosed_proforma"], caps["ix_cap"])
    projections = project_ratios(
        inputs["numerator"], inputs["rent"],
        inputs["onya_pre_proforma"], inputs["company_pre_proforma"],
        proforma, threshold)
    cush = cushions(projections, inputs["numerator"], threshold)
    trend = load_trend(base)
    avg = trend["avg_decline"]
    q_onya, r_onya = quarters_and_risk(cush["onya"], avg)
    q_comp, r_comp = quarters_and_risk(cush["company"], avg)
    backtest = load_backtest(next_test, proforma)
    return {
        "base": base,
        "next_test": next_test,
        "next_threshold": threshold,
        "threshold_note": threshold_note,
        "ix_cap": caps["ix_cap"],
        "ix_note": caps["ix_note"],
        "iv_viii_cap": caps["iv_viii_cap"],
        "iv_viii_note": caps["iv_viii_note"],
        "baseline": inputs,
        "projected_proforma": proforma,
        "projections": projections,
        "cushion": cush,
        "trend": trend,
        "quarters_of_cushion": {"onya": q_onya, "company": q_comp},
        "risk": {"onya": r_onya, "company": r_comp},
        "risk_rule": RISK_RULE,
        "backtest": backtest,
    }


def _fmt_dollars(value):
    if value is None:
        return "n/a"
    return f"${value:,.0f}"


def _fmt_quarters(value):
    if value is None:
        return "n/a (no measured decline)"
    return f"{value:.2f}"


def print_result(result):
    """Print the projection, trend, risk, and backtest."""
    print(f"base {result['base']} -> next Net Leverage test {result['next_test']}")
    print(f"next threshold: {result['next_threshold']} "
          f"({result['threshold_note']})")
    print(f"(a)(ix) cap at next test: {_fmt_dollars(result['ix_cap'])} "
          f"({result['ix_note']})")
    print(f"(a)(iv)+(a)(viii) cap at next test: "
          f"{_fmt_dollars(result['iv_viii_cap'])} ({result['iv_viii_note']})")
    b = result["baseline"]
    print("baseline no operating change (flat from base): "
          f"numerator={_fmt_dollars(b['numerator'])} "
          f"rent={_fmt_dollars(b['rent'])} "
          f"onya_pre_proforma={_fmt_dollars(b['onya_pre_proforma'])} "
          f"company_pre_proforma={_fmt_dollars(b['company_pre_proforma'])} "
          f"({b['company_source']})")
    print(f"disclosed pro forma at base: {_fmt_dollars(b['disclosed_proforma'])} "
          f"({b['disclosed_source']}); "
          f"projected pro forma=min(disclosed, new cap)="
          f"{_fmt_dollars(result['projected_proforma'])}")
    for basis in ("onya", "company"):
        p = result["projections"][basis]
        print(f"projected Net Leverage ({basis}): ratio={p['ratio']:.2f} "
              f"threshold={p['threshold']} "
              f"ebitdar={_fmt_dollars(p['ebitdar'])} "
              f"{'PASS' if p['pass'] else 'FAIL'}")
    c = result["cushion"]
    print(f"required EBITDAR (numerator/threshold): "
          f"{_fmt_dollars(c['required_ebitdar'])}")
    print(f"cushion onya={_fmt_dollars(c['onya'])} "
          f"company={_fmt_dollars(c['company'])}")
    t = result["trend"]
    seq = ", ".join(f"{r['period_end']}={_fmt_dollars(r['adjusted_ebitda'])}"
                    for r in t["series"])
    print(f"{t.get('label', TREND_LABEL)} up to base: {seq or 'n/a'}")
    chg = ", ".join(f"{r['from']}->{r['to']}={_fmt_dollars(r['change'])}"
                    for r in t["changes"])
    print(f"quarter-over-quarter TTM changes: {chg or 'n/a'}")
    print(f"avg_decline (mean of negative changes, last 2 quarters): "
          f"{_fmt_dollars(t['avg_decline'])}")
    q = result["quarters_of_cushion"]
    r = result["risk"]
    print(f"quarters_of_cushion onya={_fmt_quarters(q['onya'])} ({r['onya']}) "
          f"company={_fmt_quarters(q['company'])} ({r['company']})")
    print(f"Risk rule: {result['risk_rule']}")
    back = result.get("backtest")
    if back is None:
        print(f"backtest: no actual result file for {result['next_test']}")
    else:
        like = back.get("like_for_like") or {}
        like_lev = like.get("net_leverage") or {}
        filed_lev = back.get("net_leverage") or {}
        for basis in ("onya", "company"):
            p = result["projections"][basis]
            if like_lev:
                print(f"backtest ({basis}): projected ratio={p['ratio']:.2f} "
                      f"vs actual ratio="
                      f"{like_lev.get('ratio', float('nan')):.2f} "
                      f"(same pro forma savings="
                      f"{_fmt_dollars(like.get('savings'))}) "
                      f"threshold={like_lev.get('threshold')} "
                      f"{'PASS' if like_lev.get('pass') else 'FAIL'} "
                      f"(actual numerator="
                      f"{_fmt_dollars(back.get('numerator'))} "
                      f"ebitdar={_fmt_dollars(like.get('ebitdar'))})")
            else:
                print(f"backtest ({basis}): projected ratio={p['ratio']:.2f} "
                      f"vs actual ratio=n/a (no actual scenario with "
                      f"savings={_fmt_dollars(back.get('matched_savings'))}); "
                      f"as-filed actual ratio="
                      f"{filed_lev.get('ratio', float('nan')):.2f} "
                      f"threshold={filed_lev.get('threshold')} "
                      f"(actual numerator="
                      f"{_fmt_dollars(back.get('numerator'))} "
                      f"ebitdar={_fmt_dollars(back.get('ebitdar'))})")
        zero = back.get("without_savings") or {}
        zero_lev = zero.get("net_leverage") or {}
        if zero_lev:
            print(f"backtest actual without savings: ratio="
                  f"{zero_lev.get('ratio', float('nan')):.2f} "
                  f"threshold={zero_lev.get('threshold')} "
                  f"{'PASS' if zero_lev.get('pass') else 'FAIL'} "
                  f"(ebitdar={_fmt_dollars(zero.get('ebitdar'))})")
        elif not back.get("file_proforma"):
            print(f"backtest actual without savings: ratio="
                  f"{filed_lev.get('ratio', float('nan')):.2f} "
                  f"threshold={filed_lev.get('threshold')} "
                  f"{'PASS' if filed_lev.get('pass') else 'FAIL'} "
                  f"(as-filed actual includes no pro forma savings)")
        else:
            print(f"backtest actual without savings: n/a (as-filed actual "
                  f"includes {_fmt_dollars(back.get('file_proforma'))} "
                  f"of pro forma savings and has no savings=0 scenario)")


def save_result(result):
    """Save to data/results/snbr_projection_<base>.json."""
    path = (PROJECT_ROOT / "data" / "results" /
            f"snbr_projection_{result['base']}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    base = resolve_base()
    result = compute(base)
    print_result(result)
    print(f"saved: {save_result(result)}")


if __name__ == "__main__":
    main()
