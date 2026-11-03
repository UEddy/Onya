#!/usr/bin/env python3
"""Read-only view of the limiter's Redis keys. Usage:

    .venv/bin/python scripts/limiter_keys.py ~/.config/onya/upstash.env

The file holds UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN. Keep it
out of the main .env, because local runs would then use the production
counters. Prints key names, run counts, and time left. Token counters are
listed by name only. Writes nothing.
"""

import sys

from dotenv import dotenv_values
from upstash_redis import Redis


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    env = dotenv_values(sys.argv[1])
    redis = Redis(url=env["UPSTASH_REDIS_REST_URL"],
                  token=env["UPSTASH_REDIS_REST_TOKEN"])
    for key in sorted(redis.keys("onya:*")):
        if key.startswith("onya:runs:"):
            print(f"{key}  runs={redis.get(key)}  ttl={redis.ttl(key)}s")
        else:
            print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
