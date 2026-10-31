"""Offline contract tests, not evidence of live model semantic accuracy."""
import asyncio
import json
import unittest
from types import SimpleNamespace

from x2_agent.model_dialogue import ModelDialogue, generate_dialogue, validate_reply
from x2_agent.presentation import capabilities


def result(intent="recall", **changes):
    data = dict(intent=intent, action="continue", reply="您之前说过腰酸和脖子疼。",
                emotion="neutral", gesture=None)
    data.update(changes)
    return data


class RecallDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.memory = ModelDialogue()
        self.memory.begin()
        self.memory.commit("我今天腰有点酸", result("health", action="close"))
        self.memory.commit("我脖子也疼", result("health", action="close"))
        self.memory.commit("向我挥挥手", result("other", reply="好的。"))

    def context(self):
        return {**self.memory.context(), "capabilities": capabilities()}

    async def test_new_information_and_prior_advice_reach_model_after_close(self):
        memory = ModelDialogue()
        memory.begin()
        memory.commit("今天有点疲惫", result("health", action="followup",
                      reply="昨晚睡得怎么样？"))
        memory.commit("昨晚没睡好", result("health", action="close",
                      reply="今天别太劳累，有需要随时叫我。"))
        captured = []
        async def stream(prompt, messages, *args, **kwargs):
            captured.append((prompt, json.loads(messages[0]["content"])))
            yield "text", json.dumps(result("other", action="continue",
                                      reply="您说昨晚腰酸影响了睡眠，这一晚确实不好受。"))
        value = await generate_dialogue(SimpleNamespace(stream=stream),
                 "因为昨晚腰酸，所以没睡好", {**memory.context(), "capabilities": capabilities()},
                 "model", "key")
        self.assertIsNotNone(value)
        prompt, payload = captured[0]
        self.assertFalse(payload["interview_active"])
        self.assertEqual(payload["utterance"], "因为昨晚腰酸，所以没睡好")
        self.assertEqual(payload["verbatim_turns"][-1]["assistant"], "今天别太劳累，有需要随时叫我。")
        self.assertIn("不为避免重复而编造新建议", prompt)
        self.assertIn("close仅是流程状态", prompt)
        # This verifies transport and prompt constraints, not actual model quality.

    async def test_recall_after_topic_change_has_both_original_quotes(self):
        captured = []
        async def stream(prompt, messages, *args, **kwargs):
            captured.append(json.loads(messages[0]["content"]))
            yield "text", json.dumps(result())
        for utterance in ("我今天哪里不舒服？", "我刚才说过身体哪几个部位不舒服。"):
            answer = await generate_dialogue(SimpleNamespace(stream=stream),
                                             utterance, self.context(), "model", "key")
            self.assertEqual(answer["intent"], "recall")
            self.assertEqual(captured[-1]["health_quotes"],
                             ["我今天腰有点酸", "我脖子也疼"])
            self.assertEqual(captured[-1]["verbatim_turns"][-1]["user"], "向我挥挥手")

    def test_correction_is_retained_without_advancing_health_rounds(self):
        before = self.memory.health_rounds
        corrected = result("correction", reply="明白，脖子已经不疼了，腰酸的情况还需要留意。")
        self.assertIsNotNone(validate_reply(json.dumps(corrected), self.context()))
        self.memory.commit("脖子已经不疼了，但腰还是酸", corrected)
        self.assertEqual(self.memory.health_rounds, before)
        self.assertEqual(self.memory.context()["verbatim_turns"][-1]["user"],
                         "脖子已经不疼了，但腰还是酸")
        # Historical quotes remain history; the prompt must apply later corrections.
        self.assertIn("我今天腰有点酸", self.memory.health_quotes)

    def test_precise_validation_reasons(self):
        for text, expected in (
            ("not json", "invalid_json_or_duplicate_key"),
            ("{}", "invalid_fields"),
            (json.dumps(result(action="close")), "intent_action_mismatch"),
            (json.dumps(result(gesture="clap")), "capability_unavailable"),
            (json.dumps(result("health", action="followup", reply="哪里不舒服？")),
             "health_interview_already_closed"),
        ):
            with self.subTest(expected=expected):
                diagnostic = {}
                self.assertIsNone(validate_reply(text, self.context(), diagnostics=diagnostic))
                self.assertEqual(diagnostic["reason"], expected)

    async def test_failure_log_contains_reason_not_raw_output_or_credentials(self):
        async def stream(*args, **kwargs):
            yield "text", "secret-provider-output"
        with self.assertLogs("x2_agent.model_dialogue", level="WARNING") as logs:
            self.assertIsNone(await generate_dialogue(SimpleNamespace(stream=stream),
                              "私人健康原话", self.context(), "model", "secret-api-key"))
        combined = "\n".join(logs.output)
        self.assertIn("reason=invalid_json_or_duplicate_key", combined)
        self.assertIn("history_turns=3", combined)
        for private in ("secret-provider-output", "secret-api-key", "私人健康原话"):
            self.assertNotIn(private, combined)

    async def test_provider_timeout_and_tools_have_distinct_reasons(self):
        async def provider(*args, **kwargs):
            raise RuntimeError("secret-error")
            yield
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
            yield "text", "{}"
        async def tool(*args, **kwargs):
            yield "tool_call", {"name": "unsafe"}
        for stream, reason in ((provider, "provider_or_stream_error"),
                               (slow, "timeout"), (tool, "unexpected_tool_call")):
            with self.subTest(reason=reason):
                with self.assertLogs("x2_agent.model_dialogue", level="WARNING") as logs:
                    self.assertIsNone(await generate_dialogue(SimpleNamespace(stream=stream),
                                      "您好", self.context(), "model", "key", timeout=.01))
                self.assertIn("reason=" + reason, "\n".join(logs.output))
                self.assertNotIn("secret-error", "\n".join(logs.output))
