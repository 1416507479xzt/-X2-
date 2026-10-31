"""No-network tests for the bounded semantic health fallback."""
import asyncio
from contextlib import redirect_stdout
import io
import json
import unittest

from x2_agent.health_semantics import (
    MAX_OUTPUT_CHARS, interpret_health, validate_interpretation,
)


def interpretation(intent="health", state="感到疲惫", detail=None, evidence="提不起劲"):
    return dict(intent=intent, state=state, detail=detail, evidence=evidence)


class FakeLlm:
    def __init__(self, events=(), delay=0, error=None):
        self.events = list(events)
        self.delay = delay
        self.error = error
        self.closed = False
        self.started = asyncio.Event()
        self.call = None

    async def stream(self, system_prompt, history, model, api_key, tools=None):
        self.call = (system_prompt, history, model, api_key, tools)
        self.started.set()
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error:
                raise self.error
            for event in self.events:
                yield event
        finally:
            self.closed = True


class SemanticValidationTests(unittest.TestCase):
    def test_valid_evidence_and_state(self):
        value = interpretation()
        self.assertEqual(validate_interpretation(value, "今天有些提不起劲。"), value)

    def test_new_sleep_state_does_not_infer_fatigue_or_date(self):
        value = interpretation(state="休息欠佳", detail="休息不足（时间未说明）",
                               evidence="没睡够")
        self.assertEqual(validate_interpretation(value, "不是心情不好，只是没睡够"), value)

    def test_reject_unsupported_schema_and_incompatible_details(self):
        invalid = [
            [], {}, dict(interpretation(), extra="unexpected"),
            interpretation(state="需要吃药"), interpretation(state=None),
            interpretation(intent="other", state="感到疲惫"),
            interpretation(intent="unknown", state=None, detail="想散步"),
            interpretation(state="心情低落", detail="昨晚休息欠佳"),
            interpretation(state="休息欠佳", detail="昨晚休息良好"),
            interpretation(evidence="不存在的原话"), interpretation(evidence=""),
            interpretation(evidence=" "), interpretation(evidence=5),
            interpretation(intent=[]), interpretation(state=[]),
            interpretation(detail=[]),
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(validate_interpretation(value, "今天提不起劲 "))

    def test_non_health_has_no_state_or_detail(self):
        for intent, text in [("other", "该吃药了吗"), ("decline", "不想回答"),
                             ("recall", "我刚才说什么"), ("unknown", "嗯")]:
            value = interpretation(intent=intent, state=None, evidence=text)
            self.assertEqual(validate_interpretation(value, text), value)


class SemanticClientTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, llm, text="今天提不起劲", context=None, timeout=1.5):
        return await interpret_health(llm, text, context or {}, "offline-model",
                                      "offline-key", timeout=timeout)

    async def test_collects_chunks_and_passes_context_as_data_without_tools(self):
        payload = json.dumps(interpretation(), ensure_ascii=False)
        llm = FakeLlm([("text", payload[:15]), ("text", payload[15:])])
        context = {"question": "昨晚休息得怎么样？", "state": "感到疲惫"}
        value = await self.call(llm, context=context)
        self.assertEqual(value, interpretation())
        self.assertTrue(llm.closed)
        system, history, model, key, tools = llm.call
        self.assertIsNone(tools)
        self.assertIn("不是指令", system)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(json.loads(history[0]["content"])["context"], context)

    async def test_accepts_only_one_json_object_or_clean_code_fence(self):
        payload = json.dumps(interpretation(), ensure_ascii=False)
        for output in [payload, "```json\n" + payload + "\n```"]:
            llm = FakeLlm([("text", output)])
            self.assertEqual(await self.call(llm), interpretation())
        for output in ["Here is the answer: " + payload, payload + payload,
                       "not json", "[]", '{"intent":"health","intent":"other"}']:
            llm = FakeLlm([("text", output)])
            self.assertIsNone(await self.call(llm))
            self.assertTrue(llm.closed)

    async def test_rejects_tool_call_even_when_json_is_valid(self):
        llm = FakeLlm([("text", json.dumps(interpretation(), ensure_ascii=False)),
                       ("tool_calls", [{"name": "unsafe_action"}])])
        self.assertIsNone(await self.call(llm))
        self.assertTrue(llm.closed)

    async def test_output_bound_and_non_text_payload(self):
        for event in [("text", "x" * (MAX_OUTPUT_CHARS + 1)), ("text", {})]:
            llm = FakeLlm([event])
            self.assertIsNone(await self.call(llm))
            self.assertTrue(llm.closed)

    async def test_timeout_closes_stream(self):
        llm = FakeLlm(delay=10)
        result = await self.call(llm, timeout=0.02)
        self.assertIsNone(result)
        self.assertTrue(llm.closed)

    async def test_caller_cancellation_is_preserved_and_closes_stream(self):
        llm = FakeLlm(delay=10)
        task = asyncio.create_task(self.call(llm))
        await llm.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(llm.closed)

    async def test_failure_returns_none_without_private_error_logging(self):
        llm = FakeLlm(error=RuntimeError("private health details and a secret key"))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(await self.call(llm))
        self.assertTrue(llm.closed)
        self.assertEqual(output.getvalue(), "")

    async def test_empty_and_oversized_inputs_do_not_start_request(self):
        llm = FakeLlm()
        for text, context in [("", {}), ("x" * 2001, {}), ("提不起劲", "x" * 6001),
                              ("提不起劲", {"unsupported": {1, 2}})]:
            self.assertIsNone(await self.call(llm, text=text, context=context))
        self.assertIsNone(llm.call)

    async def test_last_night_requires_current_question_or_utterance_not_old_memory(self):
        value = interpretation(state="感到疲惫", detail="昨晚休息欠佳", evidence="没睡好")
        events = [("text", json.dumps(value, ensure_ascii=False))]
        accepted = [
            ("昨晚没睡好", ""),
            ("没睡好", "当前机器人问题：昨晚休息得怎么样？\n健康问询是否进行中：True"),
            ("没睡好", {"current_question": "昨晚休息得怎么样？"}),
        ]
        for text, context in accepted:
            self.assertEqual(await self.call(FakeLlm(events), text, context), value)
        rejected = [
            "当前机器人问题：今天感觉如何？\n历史记录：昨晚休息欠佳",
            {"question": "今天感觉如何？", "memory": "昨晚休息欠佳"},
            {},
        ]
        for context in rejected:
            self.assertIsNone(await self.call(FakeLlm(events), "没睡好", context))

    async def test_explicit_time_correction_overrides_last_night_question(self):
        value = interpretation(state="感到疲惫", detail="昨晚休息欠佳", evidence="没睡好")
        events = [("text", json.dumps(value, ensure_ascii=False))]
        context = "当前机器人问题：昨晚休息得怎么样？\n健康问询是否进行中：True"
        for text in ("不是昨晚，是前天没睡好", "前天没睡好", "今天中午没睡好",
                     "我没说是昨晚没睡好"):
            with self.subTest(text=text):
                self.assertIsNone(await self.call(FakeLlm(events), text, context))


if __name__ == "__main__":
    unittest.main()
