import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT")

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


if __name__ == "__main__":
    for url, filename in FILES:
        path = fetch(url, filename)
        size_kb = path.stat().st_size / 1024
        print(f"{filename}: {size_kb:.2f} KB")
