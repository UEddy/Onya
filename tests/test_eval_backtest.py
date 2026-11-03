"""make eval recomputes the totals from committed data, and fails on a change."""

import contextlib
import io
import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import eval_backtest  # noqa: E402


class Eval(unittest.TestCase):
    def setUp(self):
        for name in ("getaddrinfo", "create_connection"):
            patcher = patch.object(socket, name, getattr(socket, name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = eval_backtest.main(**kwargs)
        return code, out.getvalue()

    def test_prints_the_stated_totals(self):
        code, text = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Disclosed figures: 23 of 23 matched", text)
        self.assertIn("Contract limits: 19 of 21 matched "
                      "(2 changed by later amendments, flagged; 0 mismatched)",
                      text)

    def test_exits_non_zero_when_totals_differ(self):
        code, _ = self.run_main(expected={"disclosed": (23, 23),
                                          "limits": (21, 21)})
        self.assertEqual(code, 1)

    def test_it_recomputes_rather_than_reads_the_saved_match_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "backtest"
            shutil.copytree(PROJECT_ROOT / "data" / "backtest", copy)
            path = copy / "terms_TRS.json"
            record = json.loads(path.read_text())
            for row in record["covenants"]:
                row["match"] = False
            path.write_text(json.dumps(record))
            self.assertEqual(eval_backtest.recompute(copy)["limits"], (19, 21))

    def test_it_refuses_the_network(self):
        eval_backtest.recompute()
        with self.assertRaises(OSError):
            socket.create_connection(("example.invalid", 80))


if __name__ == "__main__":
    unittest.main()
