import os
import socket
import time
from pathlib import Path

import requests
import urllib3.util.connection
from dotenv import load_dotenv

urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

load_dotenv(os.path.expanduser("~/.config/onya/.env"))

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT")
if not SEC_USER_AGENT:
    raise SystemExit("SEC_USER_AGENT missing from ~/.config/onya/.env")
print(f"Using User-Agent: {SEC_USER_AGENT}")

RAW_DIR = Path("data/raw")

FILES = [
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718726000035/ex101thirteenthamendmentto.htm",
        "snbr_13th_amendment.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000123/snbr-20251110.htm",
        "snbr_8k_20251110.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000121/snbr-20250927.htm",
        "snbr_10q_20250927.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000096/a2025-q2ex991earnings.htm",
        "snbr_earnings_q2_2025.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718725000116/a2025-q3ex991earnings.htm",
        "snbr_earnings_q3_2025.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/827187/000082718726000012/a2025-q4ex991earnings.htm",
        "snbr_earnings_q4_2025.htm",
    ),
    (
        "https://www.sec.gov/Archives/edgar/data/0000827187/000082718726000039/a2026-q1ex991earnings.htm",
        "snbr_earnings_q1_2026.htm",
    ),
    (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000827187.json",
        "snbr_companyfacts.json",
    ),
]


def fetch(url, filename):
    dest = RAW_DIR / filename
    if dest.exists():
        return dest
    headers = {"User-Agent": SEC_USER_AGENT}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise requests.HTTPError(
            f"GET {url} failed with status {resp.status_code}",
            response=resp,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    time.sleep(0.5)
    return dest


def main():
    succeeded = 0
    failed = 0
    for url, filename in FILES:
        try:
            path = fetch(url, filename)
        except requests.RequestException as e:
            resp = getattr(e, "response", None)
            status = resp.status_code if resp is not None else "unknown"
            print(f"{filename}: FAILED (HTTP {status})")
            failed += 1
            continue
        size_kb = path.stat().st_size / 1024
        print(f"{filename}: {size_kb:.2f} KB")
        succeeded += 1
    print(f"Done: {succeeded} succeeded, {failed} failed")
    return succeeded, failed


if __name__ == "__main__":
    main()
