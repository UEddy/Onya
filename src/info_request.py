"""Borrower information request built from computed results only.

Every requested item ties to a specific flagged finding and its figure:
capped add-backs, pro forma savings approval, the compliance
certificate, the forecast through the next test, and (for a
forbearance) expiry and termination events. No model prose, no
invented facts, no dates beyond the tool outputs.
"""

from agent import prose_date


def _millions(value):
    """18732000 -> '$18.7 million'; 25000000 -> '$25 million'."""
    millions = abs(float(value)) / 1e6
    if millions == int(millions):
        return "$%d million" % int(millions)
    return "$%.1f million" % millions


def _exact(value):
    """962096000 -> '$962,096,000'."""
    return "$%s" % f"{int(round(float(value))):,}"


def _cap_for_period(cap_group, period_end):
    """Cap amount from the latest schedule entry on/before period_end."""
    best = None
    for entry in cap_group.get("schedule") or []:
        end = entry.get("period_end") or ""
        if end <= period_end and entry.get("amount_usd") is not None:
            if best is None or end > (best.get("period_end") or ""):
                best = entry
    return best


def _addback_lines(compute_result):
    """EBITDA add-back components keyed by clause ref."""
    lines = {}
    for comp in compute_result.get("components") or []:
        clause = comp.get("clause")
        if isinstance(clause, str) and clause.startswith("(a)("):
            lines.setdefault(clause, []).append(comp)
    return lines


def build_info_request(compute_result, reviewed, projection, agreement):
    """Assemble the lender-to-borrower request, or no request.

    Returns {"subject", "items", "reply_by", "request", "figures"}
    where figures lists every raw value rendered into the text, so
    tests can trace each figure back to the inputs. Returns
    {"request": None, "reason": ...} when nothing is breached and
    the next test is not high risk.
    """
    compute_result = compute_result or {}
    reviewed = reviewed or {}
    projection = projection or {}
    agreement = agreement or {}
    period_end = compute_result.get("period_end") or ""
    period_prose = prose_date(period_end) if period_end else period_end

    verdicts = []
    for key, label in (("net_leverage", "Net leverage"),
                       ("interest_coverage", "Interest coverage")):
        block = compute_result.get(key) or {}
        if block.get("pass") is False:
            verdicts.append((label, block))

    risk = ((projection.get("risk") or {}).get("onya") or "").upper()
    high_risk = risk == "HIGH"
    if not verdicts and not high_risk:
        return {"request": None,
                "reason": "no breach or high risk for %s" % period_end}

    items = []
    figures = []

    def use(value):
        figures.append(value)
        return value

    lines = _addback_lines(compute_result)
    for group in reviewed.get("cap_groups") or []:
        clauses = group.get("applies_to_clauses") or []
        if not clauses:
            continue
        claimed = sum((line.get("value") or 0)
                      for clause in clauses
                      for line in lines.get(clause, []))
        sched = _cap_for_period(group, period_end)
        if sched is None:
            continue
        cap = sched["amount_usd"]
        use(cap)
        if claimed <= cap:
            continue
        over = claimed - cap
        use(over)
        parts = []
        for clause in clauses:
            total = sum((line.get("value") or 0)
                        for line in lines.get(clause, []))
            use(total)
            label = next((line.get("name") or clause
                          for line in lines.get(clause, [])), clause)
            parts.append("%s %s (%s)" % (label, _exact(total), clause))
        names = " and ".join(clauses)
        items.append({
            "text": ("Support for each %s add-back: %s, against the "
                     "shared %s cap." % (
                         names, "; ".join(parts), _millions(cap))),
            "why": ("%s add-backs exceeded the shared %s cap by %s, "
                    "which was disallowed from EBITDA." % (
                        names, _millions(cap), _millions(over))),
        })

    ix_lines = _addback_lines(compute_result).get("(a)(ix)", [])
    ix_group = next(
        (g for g in reviewed.get("cap_groups") or []
         if "(a)(ix)" in (g.get("applies_to_clauses") or [])), None)
    if ix_group is not None:
        ix_sched = _cap_for_period(ix_group, period_end)
        ix_cap = ix_sched["amount_usd"] if ix_sched else None
        claimed_savings = sum((line.get("value") or 0)
                              for line in ix_lines)
        if ix_cap is not None:
            use(ix_cap)
            use(claimed_savings)
            if claimed_savings:
                amount = "of %s " % _exact(claimed_savings)
            else:
                amount = ""
            items.append({
                "text": ("Support for projected pro forma savings %s"
                         "under (a)(ix) (cap %s) and the administrative "
                         "agent approval status." % (
                             amount, _millions(ix_cap))),
                "why": ("Pro forma savings need support and agent approval "
                        "before they count toward EBITDA."),
            })

    items.append({
        "text": ("The compliance certificate for the %s test and its "
                 "supporting calculation." % period_prose),
        "why": "The certificate is the formal record of the test.",
    })

    next_test = projection.get("next_test") or ""
    next_limit = projection.get("next_threshold")
    if next_test and next_limit is not None:
        use(next_limit)
        items.append({
            "text": ("A liquidity and covenant forecast through the %s "
                     "test (limit %sx)." % (
                         prose_date(next_test), next_limit)),
            "why": ("The next test sets the limit the forecast must "
                    "clear."),
        })

    title = str((agreement.get("base") or {}).get("title") or "")
    desc = str((agreement.get("base") or {}).get("description") or "")
    is_forbearance = bool((agreement.get("base") or {}).get(
        "is_forbearance")) or "forbearance" in (title + desc).lower()
    if is_forbearance:
        items.append({
            "text": ("Confirmation of the forbearance expiry date and "
                     "the termination events."),
            "why": ("The governing document is a forbearance agreement; "
                    "its expiry bounds every cure."),
        })

    subject = ("Information request: Sleep Number covenants, %s test"
               % period_prose)
    numbered = "\n".join(
        "%d. %s\n   Why: %s" % (n, item["text"], item["why"])
        for n, item in enumerate(items, 1))
    request = ("%s\n\n%s\n\nReply by: [lender to fill]\n" % (
        subject, numbered))
    return {"subject": subject, "items": items,
            "reply_by": "[lender to fill]", "request": request,
            "figures": figures}
