#!/usr/bin/env python3
"""Live load test through the public site. Usage:

    scripts/load_test.py SITE_URL [--rounds 3] [--agents 2] [--privates 1]

Each round starts its agent runs and private checks at the same time and
waits for all of them. A run passes when its stream ends with one final
event (a result or an explicit error). It fails if the connection drops,
the stream closes with no final event, or it hangs past the time limit.
Spends real tokens and counts against the rate limits; prints no secrets.
Stops before a round that could take the total over --max-tokens.
"""

import argparse
import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.request

QUESTION = ("Check Sleep Number's covenants as of the April 2026 test and "
            "tell me what to do.")
FINALS = {"run_result", "private_result", "error"}
HANG_SECONDS = 295  # past the site's 290 s limit
AGENT_TOKENS_ESTIMATE = 70_000
PRIVATE_TOKENS_ESTIMATE = 6_000


def post(url, body):
    return urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "onya-load-test"})


def run_one(name, request):
    """One stream's outcome, with the gaps between its events."""
    started = time.monotonic()
    row = {"name": name, "status": None, "http": None, "final": None,
           "reason": None, "tokens": 0, "heartbeats": 0, "retries": 0,
           "max_gap_s": 0.0, "model_calls": [], "seconds": None,
           "finals": 0}
    last = started
    try:
        with urllib.request.urlopen(request, timeout=HANG_SECONDS) as res:
            row["http"] = res.status
            for raw in res:
                now = time.monotonic()
                row["max_gap_s"] = max(row["max_gap_s"], round(now - last, 1))
                last = now
                if now - started > HANG_SECONDS:
                    row["status"] = "HANG"
                    break
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "heartbeat":
                    row["heartbeats"] += 1
                elif kind == "model_retry":
                    row["retries"] += 1
                elif kind in FINALS:
                    row["finals"] += 1
                    row["final"] = kind
                    row["reason"] = event.get("reason") or event.get("code")
                    row["tokens"] = event.get("total_tokens") or 0
                    row["model_calls"] = event.get("model_calls") or []
        if row["status"] is None:
            row["status"] = ("NO_FINAL" if row["finals"] == 0
                             else "BAD_FINALS" if row["finals"] > 1
                             else "error" if row["final"] == "error"
                             or row["reason"] not in
                             ("done", "private_compare")
                             else "ok")
    except urllib.error.HTTPError as exc:
        row["http"] = exc.code
        row["status"] = "refused"  # an explicit answer: limits or paused
        row["reason"] = json.loads(exc.read() or b"{}").get("detail", "")[:60]
    except TimeoutError:
        row["status"] = "HANG"
    except Exception as exc:
        row["status"] = "DROPPED"
        row["reason"] = type(exc).__name__
    row["seconds"] = round(time.monotonic() - started, 1)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("site")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--agents", type=int, default=2)
    parser.add_argument("--privates", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=450_000)
    args = parser.parse_args()
    site = args.site.rstrip("/")
    with urllib.request.urlopen(f"{site}/api/private", timeout=60) as res:
        sample = json.load(res)["text"]
    jobs = ([("agent", f"{site}/api/agent", {"question": QUESTION})]
            * args.agents
            + [("private", f"{site}/api/private",
                {"ticker": "SNBR", "period_end": "2026-04-04",
                 "text": sample})] * args.privates)
    estimate = (args.agents * AGENT_TOKENS_ESTIMATE
                + args.privates * PRIVATE_TOKENS_ESTIMATE)
    rows = []
    for number in range(1, args.rounds + 1):
        spent = sum(r["tokens"] for r in rows)
        if spent + estimate > args.max_tokens:
            print(f"stopping before round {number}: {spent} tokens spent")
            break
        with concurrent.futures.ThreadPoolExecutor(len(jobs)) as pool:
            done = list(pool.map(
                lambda job: run_one(job[0], post(job[1], job[2])), jobs))
        for row in done:
            row["round"] = number
            slowest = max((c["duration_s"] for c in row["model_calls"]),
                          default=0)
            bad = [c["outcome"] for c in row["model_calls"]
                   if c["outcome"] != "ok"]
            print(f"round {number} {row['name']:8} {row['status']:9} "
                  f"reason={row['reason']} {row['seconds']:6}s "
                  f"tokens={row['tokens']} heartbeats={row['heartbeats']} "
                  f"retries={row['retries']} max_gap={row['max_gap_s']}s "
                  f"calls={len(row['model_calls'])} slowest_call={slowest}s "
                  f"failed_calls={bad}", flush=True)
        rows.extend(done)
    bad = [r for r in rows
           if r["status"] in ("HANG", "NO_FINAL", "DROPPED", "BAD_FINALS")]
    ok = {n: sum(1 for r in rows if r["name"] == n and r["status"] == "ok")
          for n in ("agent", "private")}
    total = {n: sum(1 for r in rows if r["name"] == n)
             for n in ("agent", "private")}
    print(f"\nsuccess: agent {ok['agent']}/{total['agent']}, "
          f"private {ok['private']}/{total['private']}")
    print(f"explicit errors or refusals: "
          f"{sum(1 for r in rows if r['status'] in ('error', 'refused'))}")
    print(f"silent endings or hangs: {len(bad)}")
    print(f"tokens: {sum(r['tokens'] for r in rows)}")
    print(json.dumps(rows))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
