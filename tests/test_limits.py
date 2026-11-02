"""Tests for src/limits.py (memory store, store resolution, Lua claim)."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import limits  # noqa: E402


class MemoryStore(unittest.TestCase):
    def test_claim_counts_up(self):
        store = limits.MemoryStore()
        self.assertEqual(store.claim("k", 3600), 1)
        self.assertEqual(store.claim("k", 3600), 2)

    def test_add_and_total(self):
        store = limits.MemoryStore()
        self.assertEqual(store.add("t", 100, 86400), 100)
        self.assertEqual(store.add("t", 50, 86400), 150)
        self.assertEqual(store.total("t"), 150)

    def test_reset(self):
        store = limits.MemoryStore()
        store.claim("k", 60)
        store.reset()
        self.assertEqual(store.total("k"), 0)

    def test_hour_and_day_keys_differ(self):
        self.assertNotEqual(limits.ip_key("1.2.3.4"),
                            limits.ip_key("1.2.3.4") + "#")
        self.assertTrue(limits.day_key())
        self.assertTrue(limits.tokens_key())


class ResolveStore(unittest.TestCase):
    def test_local_without_redis_is_memory(self):
        env = {"ONYA_ENV": "", "UPSTASH_REDIS_REST_URL": "",
               "UPSTASH_REDIS_REST_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            store = limits.resolve_store()
        self.assertIsInstance(store, limits.MemoryStore)

    def test_production_without_redis_fails_closed(self):
        env = {"ONYA_ENV": "production", "UPSTASH_REDIS_REST_URL": "",
               "UPSTASH_REDIS_REST_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(limits.RedisUnavailable):
                limits.resolve_store()


class UpstashClaim(unittest.TestCase):
    def test_claim_is_single_atomic_eval(self):
        calls = []

        class StubClient:
            def eval(self, script, keys=None, args=None):
                calls.append((script, keys, args))
                return 1

        store = limits.UpstashStore(StubClient())
        self.assertEqual(store.claim("onya:runs:ip:1.2.3.4:x", 3600), 1)
        self.assertEqual(len(calls), 1)
        script, keys, args = calls[0]
        self.assertIn("INCR", script)
        self.assertIn("EXPIRE", script)
        self.assertEqual(keys, ["onya:runs:ip:1.2.3.4:x"])
        self.assertEqual(args[0], 3600)

    def test_unreachable_client_fails_closed(self):
        class DeadClient:
            def eval(self, *args, **kwargs):
                raise ConnectionError("down")

            def get(self, *args, **kwargs):
                raise ConnectionError("down")

        store = limits.UpstashStore(DeadClient())
        with self.assertRaises(limits.RedisUnavailable):
            store.claim("k", 60)
        with self.assertRaises(limits.RedisUnavailable):
            store.total("k")


if __name__ == "__main__":
    unittest.main()
