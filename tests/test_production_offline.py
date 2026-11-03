"""Production path for the SNBR information request and private check.

Runs the real endpoints with ONYA_ENV=production against the bundled data,
with every DNS lookup and socket connection refused and recorded. Code in
these paths swallows lookup errors, so the record is what proves no SEC
call was attempted: an answer alone would not.
"""

import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("SEC_USER_AGENT", "onya-tests test@example.invalid")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import edgar  # noqa: E402
import limits  # noqa: E402
import private_compare  # noqa: E402

TOKEN = "production-offline-token"
FORBEARANCE_FLAG = ("The certificate's net leverage of 5.06x is still above "
                    "the 4.75x limit. Its compliance statement relies on the "
                    "forbearance, not the ratio.")
CERT_FIGURES = {"covenants": [
    {"name": "Net Leverage Ratio", "direction": "max", "threshold": 4.75,
     "actual": 5.06, "quote": "q", "verified": True},
    {"name": "Interest Coverage Ratio", "direction": "min", "threshold": 2.1,
     "actual": 1.7, "quote": "q", "verified": True}],
    "components": []}


class ProductionOffline(unittest.TestCase):
    def setUp(self):
        self.attempts = []

        def refuse(*args, **kwargs):
            self.attempts.append(args[:2])
            raise OSError("network refused by test")

        overlay = tempfile.TemporaryDirectory()
        self.addCleanup(overlay.cleanup)
        env = {"ONYA_ENV": "production", "ONYA_RUNTIME_DIR": overlay.name,
               "ONYA_DEMO_TOKEN": TOKEN, "ONYA_PRIVATE_REPLAY": "1"}
        store = limits.MemoryStore()
        for patcher in (
                patch.dict(os.environ, env),
                patch.object(socket, "getaddrinfo", side_effect=refuse),
                patch.object(socket, "create_connection",
                             side_effect=refuse),
                # A refused call must fail the test fast, not wait on retries.
                patch.object(edgar.time, "sleep"),
                patch.object(limits, "resolve_store", return_value=store)):
            patcher.start()
            self.addCleanup(patcher.stop)
        api._reset_state()
        self.addCleanup(api._reset_state)
        self.client = TestClient(api.app)

    def test_information_request_has_forbearance_item(self):
        r = self.client.post(
            "/agent/info-request",
            json={"company": "SNBR", "period_end": "2026-04-04"},
            headers={"X-Onya-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        events = [json.loads(line) for line in r.text.splitlines() if line]
        text = events[-1]["info_request"].upper()
        self.assertIn("FORBEARANCE EXPIRY DATE", text)
        self.assertNotIn("FOURTEENTH", text)
        self.assertEqual(self.attempts, [])

    def test_private_check_has_forbearance_flag(self):
        with patch.object(api, "_private_replay_figures",
                          return_value={"figures": CERT_FIGURES}):
            r = self.client.post(
                "/private/compare",
                json={"ticker": "SNBR", "period_end": "2026-04-04",
                      "text": "words"},
                headers={"X-Onya-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        events = [json.loads(line) for line in r.text.splitlines() if line]
        result = next(e for e in events if e.get("type") == "private_result")
        self.assertIn(FORBEARANCE_FLAG, result["comparison"]["flags"])
        self.assertEqual(self.attempts, [])

    def test_private_check_stays_offline_for_each_computed_period(self):
        for period_end in ("2025-09-27", "2026-01-03", "2026-04-04"):
            with self.subTest(period_end=period_end):
                private_compare.compare_with_onya(
                    "SNBR", period_end, CERT_FIGURES)
                self.assertEqual(self.attempts, [])


if __name__ == "__main__":
    unittest.main()
