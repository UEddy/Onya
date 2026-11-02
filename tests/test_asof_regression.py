"""Regression tests: no hindsight leak in agreement selection.

The Apr 4, 2026 test (as of May 19, 2026) is governed by the Apr 28,
2026 forbearance agreement and thirteenth amendment. The fourteenth
amendment filed Jun 16, 2026 must never surface under that as-of
date, on any selection path.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import requests

import agent
import edgar

AS_OF = "2026-05-19"

FORBEARANCE_TITLE = ("FORBEARANCE AGREEMENT AND THIRTEENTH AMENDMENT "
                     "TO AMENDED AND RESTATED CREDIT AND SECURITY AGREEMENT")
FOURTEENTH_TITLE = ("FOURTEENTH AMENDMENT TO AMENDED AND RESTATED CREDIT "
                    "AND SECURITY AGREEMENT")


def _no_network():
    def dead(*args, **kwargs):
        raise AssertionError("network call attempted")
    return patch.object(edgar.requests, "get", side_effect=dead), \
        patch.object(edgar.requests, "post", side_effect=dead)


class BundledCacheHit(unittest.TestCase):
    def test_ticker_resolves_and_cache_hits_with_zero_network(self):
        get_patch, post_patch = _no_network()
        with get_patch, post_patch:
            base, amendments = edgar.select_agreement("SNBR", as_of=AS_OF)
        self.assertEqual(base["filingDate"], "2026-04-28")
        self.assertIn("FORBEARANCE", (base["title"] or "").upper())
        self.assertIn("THIRTEENTH", (base["title"] or "").upper())
        self.assertEqual(amendments, [])

    def test_production_layout_reads_bundled_cache_first(self):
        get_patch, post_patch = _no_network()
        env = {"ONYA_ENV": "production",
               "ONYA_RUNTIME_DIR": "/tmp/asof-regression-overlay"}
        with get_patch, post_patch, patch.dict(os.environ, env):
            base, _ = edgar.select_agreement("SNBR", as_of=AS_OF)
        self.assertEqual(base["filingDate"], "2026-04-28")
        self.assertIn("THIRTEENTH", (base["title"] or "").upper())

    def test_delisted_ticker_resolves_via_registry(self):
        self.assertEqual(edgar.get_cik("SNBR"), "0000827187")


class LatestComputedDefault(unittest.TestCase):
    def test_default_is_apr_2026_for_snbr(self):
        self.assertEqual(agent.latest_computed_period("SNBR"),
                         "2026-04-04")
        self.assertEqual(agent.default_as_of("SNBR"),
                         ("2026-04-04", "2026-05-19"))

    def test_unknown_company_has_no_default(self):
        self.assertIsNone(agent.latest_computed_period("NOPE"))
        self.assertEqual(agent.default_as_of("NOPE"), (None, None))

    def test_explicit_as_of_never_defaults(self):
        self.assertEqual(agent.effective_as_of("SNBR", "2026-11-02"),
                         ("2026-11-02", False, None))

    def test_find_agreements_defaults_without_as_of(self):
        get_patch, post_patch = _no_network()
        with get_patch, post_patch:
            result = agent.tool_find_agreements("SNBR")
        self.assertEqual(result["as_of"], "2026-05-19")
        self.assertTrue(result["as_of_defaulted"])
        self.assertEqual(result["default_period_end"], "2026-04-04")
        self.assertEqual(result["base"]["filingDate"], "2026-04-28")
        self.assertIn("THIRTEENTH",
                      (result["base"]["title"] or "").upper())

    def test_compute_covenants_defaults_without_as_of(self):
        get_patch, post_patch = _no_network()
        with get_patch, post_patch, \
             patch("covenant.save_result",
                   return_value=Path("snbr_2026-04-04.json")):
            result = agent.tool_compute_covenants("SNBR", "2026-04-04")
        self.assertEqual(result["as_of"], "2026-05-19")
        self.assertTrue(result["as_of_defaulted"])
        self.assertNotIn("error", result)


class DefaultDateLine(unittest.TestCase):
    def _finds(self, defaulted):
        return [{
            "tool": "find_agreements",
            "company": "SNBR",
            "as_of": "2026-05-19" if defaulted else "2026-11-02",
            "as_of_defaulted": defaulted,
            "default_period_end": "2026-04-04" if defaulted else None,
            "governing_doc_type": "forbearance",
            "base": {"title": FORBEARANCE_TITLE},
            "amendments": [],
        }]

    def test_prepends_when_defaulted(self):
        out = agent.ensure_default_date_line("Summary\nBody.",
                                             self._finds(True))
        self.assertTrue(
            out.startswith("No test date given; using the latest "
                           "computed test, Apr 4, 2026.\n"), out)

    def test_untouched_when_explicit(self):
        self.assertEqual(
            agent.ensure_default_date_line("Summary\nBody.",
                                           self._finds(False)),
            "Summary\nBody.")

    def test_untouched_when_already_present(self):
        memo = ("No test date given; using the latest computed test, "
                "Apr 4, 2026.\nSummary")
        self.assertEqual(
            agent.ensure_default_date_line(memo, self._finds(True)), memo)

    def test_strips_model_given_date_line_when_defaulted(self):
        memo = ("Test date given; using Apr 4, 2026 with reporting window "
                "to May 19, 2026.\nSummary")
        self.assertEqual(
            agent.ensure_default_date_line(memo, self._finds(True)),
            "No test date given; using the latest computed test, "
            "Apr 4, 2026.\nSummary")

    def test_strips_model_given_date_line_when_explicit(self):
        memo = ("Test date given; using Apr 4, 2026 with reporting window "
                "to May 19, 2026.\nSummary")
        self.assertEqual(
            agent.ensure_default_date_line(memo, self._finds(False)),
            "Summary")


class DiscoveryCutoff(unittest.TestCase):
    def _candidates(self):
        # Discovery order is newest first; the first complete
        # candidate on/before the cutoff becomes the base.
        return [
            {"url": "https://example.invalid/fourteenth.htm",
             "filingDate": "2026-06-16", "form": "8-K",
             "description": "fourteenth amendment",
             "title": FOURTEENTH_TITLE,
             "is_forbearance": False, "is_amendment": True,
             "is_complete": True},
            {"url": "https://example.invalid/forbear.htm",
             "filingDate": "2026-04-28", "form": "8-K",
             "description": "forbearance and thirteenth amendment",
             "title": FORBEARANCE_TITLE,
             "is_forbearance": True, "is_amendment": True,
             "is_complete": True},
            {"url": "https://example.invalid/base.htm",
             "filingDate": "2024-06-01", "form": "8-K",
             "description": "base credit agreement",
             "title": "AMENDED AND RESTATED CREDIT AND SECURITY AGREEMENT",
             "is_forbearance": False, "is_amendment": False,
             "is_complete": True},
        ]

    def test_live_discovery_excludes_post_cutoff_filing(self):
        with patch.object(edgar, "find_credit_agreements",
                          return_value=self._candidates()), \
             patch.object(edgar, "_load_select_cache", return_value=None), \
             patch.object(edgar, "_save_select_cache",
                          return_value=None):
            base, amendments = edgar.select_agreement(
                "827187", as_of=AS_OF)
        self.assertEqual(base["filingDate"], "2026-04-28")
        self.assertIn("THIRTEENTH", (base["title"] or "").upper())
        for doc in [base, *amendments]:
            self.assertLessEqual(doc["filingDate"], AS_OF)

    def test_stale_cache_forces_rediscovery(self):
        stale = edgar.AgreementSelection(
            {"url": "https://example.invalid/fourteenth.htm",
             "filingDate": "2026-06-16", "form": "8-K",
             "description": "fourteenth amendment",
             "title": FOURTEENTH_TITLE,
             "is_forbearance": False, "is_amendment": True,
             "is_complete": True},
            [])
        with patch.object(edgar, "_load_select_cache",
                          return_value=stale), \
             patch.object(edgar, "find_credit_agreements",
                          return_value=self._candidates()), \
             patch.object(edgar, "_save_select_cache",
                          return_value=None):
            base, amendments = edgar.select_agreement(
                "827187", as_of=AS_OF)
        self.assertEqual(base["filingDate"], "2026-04-28")
        for doc in [base, *amendments]:
            self.assertLessEqual(doc["filingDate"], AS_OF)


class VerifierRejectsForeignLabels(unittest.TestCase):
    def _find_output(self):
        return [{
            "tool": "find_agreements",
            "company": "SNBR",
            "as_of": AS_OF,
            "governing_doc_type": "forbearance",
            "base": {"url": "https://example.invalid/forbear.htm",
                     "filingDate": "2026-04-28", "form": "8-K",
                     "description": "forbearance and thirteenth amendment",
                     "title": FORBEARANCE_TITLE},
            "amendments": [],
        }]

    def test_foreign_ordinal_and_title_flagged(self):
        draft = ("Summary\nSleep Number failed two covenants at the Apr 4, "
                 "2026 test under the Fourteenth amendment to amended and "
                 "restated credit and security agreement, titled "
                 '"Fourteenth Amendment to Amended and Restated Credit and '
                 'Security Agreement".')
        labels = agent.verify_memo_labels(draft, self._find_output())
        self.assertTrue(labels["unverified_ordinals"], labels)
        self.assertTrue(labels["unverified_titles"], labels)

    def test_forbearance_labels_pass(self):
        draft = ("Summary\nSleep Number failed two covenants at the Apr 4, "
                 "2026 test under the " + FORBEARANCE_TITLE + ".")
        labels = agent.verify_memo_labels(draft, self._find_output())
        self.assertEqual(labels["unverified_ordinals"], [])
        self.assertEqual(labels["unverified_titles"], [])


if __name__ == "__main__":
    unittest.main()
