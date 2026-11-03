"""No silent endings: bounded model calls and one final event per stream."""

import json
import logging
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("SEC_USER_AGENT", "onya-tests test@example.invalid")

from fastapi.testclient import TestClient  # noqa: E402

import agent  # noqa: E402
import api  # noqa: E402
import limits  # noqa: E402
import model_calls  # noqa: E402
import private_compare  # noqa: E402

TOKEN = "stream-test-token"
REQUEST = httpx.Request("POST", "https://model.invalid/v1")
FINALS = {"run_result", "private_result", "error"}
SECRET_PROMPT = "PROMPT-TEXT-THAT-MUST-NOT-BE-LOGGED"


def response(content="done", tokens=10):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                           usage=SimpleNamespace(prompt_tokens=1,
                                                 completion_tokens=1,
                                                 total_tokens=tokens))


def timeout_error():
    return openai.APITimeoutError(request=REQUEST)


def status_error(status):
    cls = (openai.BadRequestError if status == 400
           else openai.InternalServerError)
    return cls("no", response=httpx.Response(status, request=REQUEST),
               body=None)


class ScriptedClient:
    """Each create() takes the next item: raised if an error, else returned."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class ModelCall(unittest.TestCase):
    def call(self, client, deadline_s=270, **kwargs):
        return model_calls.call(
            client, label="test",
            deadline=model_calls.Deadline(deadline_s),
            model="m", messages=[], **kwargs)

    def test_timeout_fits_inside_the_time_left(self):
        client = ScriptedClient(response())
        self.call(client, deadline_s=50)
        self.assertLessEqual(client.requests[0]["timeout"], 47)
        client = ScriptedClient(response())
        self.call(client)
        self.assertEqual(client.requests[0]["timeout"],
                         model_calls.PER_CALL_SECONDS)

    def test_retries_once_and_reports_it(self):
        retries = []
        client = ScriptedClient(timeout_error(), response())
        self.call(client, on_retry=retries.append)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(retries, [{"type": "model_retry", "label": "test",
                                    "attempt": 2, "reason": "timeout"}])

    def test_never_retries_twice(self):
        client = ScriptedClient(timeout_error(), status_error(500), response())
        with self.assertRaises(model_calls.ModelCallFailed) as caught:
            self.call(client)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(caught.exception.outcome, "server_error")

    def test_no_retry_when_time_is_short(self):
        retries = []
        client = ScriptedClient(timeout_error(), response())
        with self.assertRaises(model_calls.ModelCallFailed):
            self.call(client, deadline_s=model_calls.MIN_RETRY_SECONDS - 1,
                      on_retry=retries.append)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(retries, [])

    def test_no_retry_on_a_rejected_request(self):
        client = ScriptedClient(status_error(400), response())
        with self.assertRaises(model_calls.ModelCallFailed) as caught:
            self.call(client)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(caught.exception.outcome, "rejected_400")

    def test_no_call_starts_past_the_deadline(self):
        client = ScriptedClient(response())
        with self.assertRaises(model_calls.DeadlineReached):
            self.call(client, deadline_s=model_calls.MIN_CALL_SECONDS - 1)
        self.assertEqual(client.requests, [])

    def test_a_call_that_ignores_its_timeout_is_still_cut_off(self):
        release = threading.Event()
        self.addCleanup(release.set)
        client = ScriptedClient()
        client.chat.completions.create = lambda **kw: release.wait(30)
        started = time.monotonic()
        with self.assertRaises(model_calls.ModelCallFailed) as caught:
            self.call(client, per_call_s=0.1, max_retries=0)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(caught.exception.outcome, "timeout")

    def test_log_has_timing_and_outcome_but_no_content(self):
        client = ScriptedClient(openai.APITimeoutError(request=REQUEST),
                                response(content="MODEL-OUTPUT-TEXT"))
        with self.assertLogs("onya.model", logging.INFO) as logs:
            model_calls.call(
                client, label="test", run_id="r1",
                deadline=model_calls.Deadline(270), model="m",
                messages=[{"role": "user", "content": SECRET_PROMPT}])
        lines = [json.loads(r.getMessage()) for r in logs.records]
        self.assertEqual([(x["phase"], x.get("outcome")) for x in lines],
                         [("start", None), ("end", "timeout"),
                          ("start", None), ("end", "ok")])
        self.assertIn("duration_s", lines[-1])
        text = "\n".join(r.getMessage() for r in logs.records)
        self.assertNotIn(SECRET_PROMPT, text)
        self.assertNotIn("MODEL-OUTPUT-TEXT", text)


class StreamCase(unittest.TestCase):
    def setUp(self):
        self.store = limits.MemoryStore()
        for patcher in (
                patch.dict(os.environ, {"ONYA_DEMO_TOKEN": TOKEN}),
                patch.object(limits, "resolve_store",
                             return_value=self.store)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("ONYA_AGENT_REPLAY", None)
        api._reset_state()
        self.addCleanup(api._reset_state)
        self.client = TestClient(api.app)

    def spent(self):
        return self.store.total(limits.tokens_key())

    def post_agent(self):
        r = self.client.post("/agent/run", json={"question": "q?"},
                             headers={"X-Onya-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        return [json.loads(x) for x in r.text.splitlines() if x]

    def post_private(self):
        r = self.client.post(
            "/private/compare",
            json={"ticker": "SNBR", "period_end": "2026-04-04",
                  "text": "words"},
            headers={"X-Onya-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        return [json.loads(x) for x in r.text.splitlines() if x]

    def assert_one_final_last(self, events):
        finals = [e for e in events if e.get("type") in FINALS]
        self.assertEqual(len(finals), 1, events)
        self.assertIs(events[-1], finals[0])
        return finals[0]


class AgentStream(StreamCase):
    def run_with(self, client, **kwargs):
        real = agent.run_agent

        def with_client(question, run_id=None, on_event=None, call_log=None):
            return real(question, client=client, run_id=run_id,
                        on_event=on_event, call_log=call_log, **kwargs)

        tmp = patch.object(agent, "run_agent", with_client)
        tmp.start()
        self.addCleanup(tmp.stop)
        return self.post_agent()

    def test_success(self):
        final = self.assert_one_final_last(self.run_with(
            ScriptedClient(response("memo", tokens=25))))
        self.assertEqual((final["type"], final["reason"]),
                         ("run_result", "done"))
        self.assertEqual(final["model_calls"][0]["outcome"], "ok")
        self.assertEqual(self.spent(), 25)

    def test_retry_is_visible_then_succeeds(self):
        events = self.run_with(ScriptedClient(timeout_error(), response()))
        final = self.assert_one_final_last(events)
        self.assertEqual(final["reason"], "done")
        retries = [e for e in events if e["type"] == "model_retry"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["reason"], "timeout")

    def test_model_timeout_ends_with_an_error(self):
        final = self.assert_one_final_last(self.run_with(
            ScriptedClient(timeout_error(), timeout_error())))
        self.assertEqual((final["type"], final["code"]),
                         ("error", "model_failed"))
        self.assertEqual(final["error"], agent.MODEL_FAILED_ANSWER)
        self.assertEqual([c["outcome"] for c in final["model_calls"]],
                         ["timeout", "timeout"])

    def test_tokens_from_a_failed_run_count(self):
        tool = SimpleNamespace(
            id="c1", function=SimpleNamespace(name="no_such_tool",
                                              arguments="{}"))
        first = response(tokens=40)
        first.choices[0].message.content = ""
        first.choices[0].message.tool_calls = [tool]
        final = self.assert_one_final_last(self.run_with(
            ScriptedClient(first, status_error(400))))
        self.assertEqual(final["code"], "model_failed")
        self.assertEqual(self.spent(), 40)

    def test_270s_deadline_is_one_final_result(self):
        final = self.assert_one_final_last(self.run_with(
            ScriptedClient(), deadline_s=0))
        self.assertEqual((final["type"], final["reason"]),
                         ("run_result", "took_too_long"))

    def test_deadline_during_the_run_is_one_final_result(self):
        final = self.assert_one_final_last(self.run_with(
            ScriptedClient(response()),
            deadline_s=model_calls.MIN_CALL_SECONDS - 1))
        self.assertEqual(final["reason"], "took_too_long")

    def test_exception_is_one_error_with_no_detail(self):
        def boom(question, **kwargs):
            raise RuntimeError(f"secret detail {PROJECT_ROOT}")

        with patch.object(agent, "run_agent", boom):
            final = self.assert_one_final_last(self.post_agent())
        self.assertEqual(final["error"], api.RUN_FAILED_MESSAGE)

    def test_heartbeats_while_waiting_then_a_result(self):
        def slow(question, run_id=None, **kwargs):
            time.sleep(0.25)
            return {"answer": "ok", "reason": "done", "total_tokens": 1,
                    "tool_calls": 0, "figure_fields": []}

        with patch.object(agent, "run_agent", slow), \
                patch.object(api, "HEARTBEAT_SECONDS", 0.05):
            events = self.post_agent()
        self.assert_one_final_last(events)
        beats = [e for e in events if e["type"] == "heartbeat"]
        self.assertGreaterEqual(len(beats), 2)

    def test_stuck_worker_hits_the_watchdog(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def stuck(question, run_id=None, on_event=None, **kwargs):
            on_event({"step": 1, "type": "tool_call", "tool": "x",
                      "total_tokens": 7})
            release.wait(30)
            return {"answer": "late", "reason": "done", "total_tokens": 7}

        with patch.object(agent, "run_agent", stuck), \
                patch.object(api, "HEARTBEAT_SECONDS", 0.05), \
                patch.object(api, "STREAM_WATCHDOG_SECONDS", 0.2):
            final = self.assert_one_final_last(self.post_agent())
        self.assertEqual(final["reason"], "took_too_long")
        self.assertEqual(self.spent(), 7)


class OneFinal(unittest.TestCase):
    def test_nothing_after_the_first_final(self):
        out = list(api._one_final(iter([
            {"type": "heartbeat"}, {"type": "error", "error": "a"},
            {"type": "error", "error": "b"}])))
        self.assertEqual([e.get("error") for e in out], [None, "a"])

    def test_stream_with_no_final_gets_one(self):
        out = list(api._one_final(iter([{"type": "progress"}])))
        self.assertEqual(out[-1]["code"], "lost")

    def test_raising_stream_gets_one_without_its_text(self):
        def events():
            yield {"type": "progress"}
            raise RuntimeError("secret detail")

        out = list(api._one_final(events()))
        self.assertEqual(out[-1]["code"], "lost")
        self.assertNotIn("secret detail", json.dumps(out))


class PrivateStream(StreamCase):
    def setUp(self):
        super().setUp()
        patcher = patch.dict(os.environ, {"BASETEN_API_KEY": "k",
                                          "BASETEN_BASE_URL":
                                          "https://model.invalid/v1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("ONYA_PRIVATE_REPLAY", None)

    def with_client(self, client):
        patcher = patch.object(private_compare, "make_baseten_client",
                               return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_model_timeout_ends_with_an_error(self):
        self.with_client(ScriptedClient(timeout_error(), timeout_error()))
        events = self.post_private()
        final = self.assert_one_final_last(events)
        self.assertEqual(final["code"], "model_failed")
        self.assertEqual(
            [e["type"] for e in events].count("model_retry"), 1)

    def test_retry_then_result(self):
        figures = json.dumps({"covenants": [], "components": []})
        self.with_client(ScriptedClient(
            timeout_error(), response(figures, tokens=9)))
        final = self.assert_one_final_last(self.post_private())
        self.assertEqual(final["type"], "private_result")
        self.assertEqual(self.spent(), 9)

    def test_unusable_output_is_one_error(self):
        self.with_client(ScriptedClient(response("not json")))
        final = self.assert_one_final_last(self.post_private())
        self.assertEqual(final["type"], "error")

    def test_unexpected_exception_is_one_error(self):
        with patch.object(private_compare, "run_compare",
                          side_effect=RuntimeError("cert text")):
            events = self.post_private()
        final = self.assert_one_final_last(events)
        self.assertNotIn("cert text", json.dumps(events))
        self.assertEqual(final["error"], "comparison failed")

    def test_unavailable_is_one_error_with_a_code(self):
        with patch.object(
                private_compare, "run_compare",
                side_effect=private_compare.PrivateUnavailable("off")):
            final = self.assert_one_final_last(self.post_private())
        self.assertEqual(final["code"], "unavailable")

    def test_stuck_worker_hits_the_watchdog(self):
        release = threading.Event()
        self.addCleanup(release.set)
        with patch.object(private_compare, "run_compare",
                          side_effect=lambda *a, **k: release.wait(30)), \
                patch.object(api, "HEARTBEAT_SECONDS", 0.05), \
                patch.object(api, "STREAM_WATCHDOG_SECONDS", 0.2):
            events = self.post_private()
        final = self.assert_one_final_last(events)
        self.assertEqual(final["code"], "took_too_long")
        self.assertIn("heartbeat", [e["type"] for e in events])


class ConcurrentRuns(unittest.TestCase):
    def test_a_run_starting_does_not_clear_another_runs_corpus(self):
        """Memo verification reads this corpus on a shared instance."""
        first_recorded = threading.Event()
        second_started = threading.Event()
        seen = {}

        def first():
            agent.reset_corpus()
            agent._record({"who": "first"})
            first_recorded.set()
            second_started.wait(5)
            seen["first"] = list(agent._TOOL_OUTPUTS)

        def second():
            first_recorded.wait(5)
            agent.reset_corpus()
            agent._record({"who": "second"})
            second_started.set()
            seen["second"] = list(agent._TOOL_OUTPUTS)

        threads = [threading.Thread(target=f) for f in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(seen["first"], [{"who": "first"}])
        self.assertEqual(seen["second"], [{"who": "second"}])

    def test_tool_threads_see_their_runs_corpus(self):
        agent.reset_corpus()
        agent._record({"who": "run"})
        self.assertEqual(
            agent._call_with_timeout(
                lambda: list(agent._TOOL_OUTPUTS), 5, "tool"),
            [{"who": "run"}])
        agent._call_with_timeout(
            lambda: agent._record({"who": "tool"}), 5, "tool")
        self.assertEqual(len(agent._TOOL_OUTPUTS), 2)


if __name__ == "__main__":
    unittest.main()
