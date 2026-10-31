"""Offline checks for the opt-in competition greeting."""
import asyncio
import json
import unittest
from unittest.mock import patch

from x2_agent.agent import DoubaoAgent, parse_args
from x2_agent.competition_flow import GREETING, HealthGreetingFlow
from x2_agent.gateway import T


class HealthGreetingFlowTests(unittest.TestCase):
    def test_two_turn_targeted_reply_closes_and_keeps_normalized_memory(self):
        for utterance, state, emotion in (
            ("腰有点酸", "腰部不适", "love"),
            ("心情不太好", "心情低落", "love"),
            ("有点累", "感到疲惫", "love"),
            ("还行", "状态良好", "happy"),
        ):
            with self.subTest(utterance=utterance):
                flow = HealthGreetingFlow()
                self.assertEqual(flow.begin(), GREETING)
                result = flow.respond(utterance)
                self.assertEqual(result.emotion, emotion)
                self.assertIn("？", result.text)
                self.assertTrue(flow.awaiting_health)
                closing = flow.respond("谢谢，我知道了")
                self.assertIn("有需要随时叫我", closing.text)
                self.assertFalse(flow.awaiting_health)
                self.assertIn(state, flow.memory_context())
                self.assertIsNone(flow.respond("其他问题"))

    def test_ambiguous_answer_gets_only_one_clarification(self):
        flow = HealthGreetingFlow()
        flow.begin()
        self.assertIn("身体", flow.respond("嗯").text)
        self.assertTrue(flow.awaiting_health)
        self.assertIn("没听清", flow.respond("不知道").text)
        self.assertFalse(flow.awaiting_health)
        self.assertEqual(flow.memory_context(), "")

    def test_clarified_status_closes_in_second_turn(self):
        flow = HealthGreetingFlow()
        flow.begin()
        flow.respond("嗯")
        result = flow.respond("有点累")
        self.assertIn("有些累", result.text)
        self.assertIn("有需要随时叫我", result.text)
        self.assertFalse(flow.awaiting_health)

    def test_personalized_greeting_and_second_turn_memory(self):
        flow = HealthGreetingFlow()
        self.assertTrue(flow.begin("王阿姨").startswith("王阿姨，您好"))
        flow.respond("有点累")
        closing = flow.respond("昨晚没睡好")
        self.assertIn("昨晚没休息好", closing.text)
        self.assertIn("昨晚休息欠佳", flow.memory_context())

    def test_log_phrasing_is_remembered_and_can_be_recalled(self):
        flow = HealthGreetingFlow()
        flow.begin("王阿姨")
        self.assertIn("昨晚休息", flow.respond("感觉有点疲惫。").text)
        self.assertIn("昨晚没休息好", flow.respond("休息得不太好。").text)
        self.assertIn("昨晚休息欠佳", flow.memory_context())
        for question in ("我今天感觉怎么样？", "知道我刚才说了些什么吗？"):
            with self.subTest(question=question):
                answer = flow.respond(question)
                self.assertIn("您说今天有些累", answer.text)
                self.assertIn("昨晚休息得不太好", answer.text)
                self.assertIsNone(answer.emotion)

    def test_new_health_statement_after_closure_starts_new_check(self):
        flow = HealthGreetingFlow()
        flow.begin()
        flow.respond("还行")
        flow.respond("想散步")
        self.assertFalse(flow.awaiting_health)
        self.assertIsNone(flow.respond("该吃药了吗"))
        answer = flow.respond("今天有点疲惫")
        self.assertIn("昨晚休息得怎么样", answer.text)
        self.assertEqual(flow.health_state, "感到疲惫")
        self.assertTrue(flow.awaiting_followup)

    def test_back_discomfort_followup_and_respectful_low_mood(self):
        flow = HealthGreetingFlow()
        flow.begin()
        flow.respond("腰有点酸")
        self.assertIn("建议让医护人员了解", flow.respond("好几天了").text)
        self.assertIn("持续多日", flow.memory_context())
        flow.begin()
        flow.respond("心情不太好")
        self.assertIn("不想说也可以", flow.respond("不想说").text)

    def test_negated_symptom_is_not_marked_unwell(self):
        flow = HealthGreetingFlow()
        flow.begin()
        flow.respond("今天不累")
        self.assertEqual(flow.health_state, "状态良好")
        flow.begin()
        flow.respond("我不难过")
        self.assertEqual(flow.health_state, "状态良好")


class CompetitionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # These tests exercise the retained deterministic compatibility path.
        # Model-first behavior is covered by test_model_presentation.py.
        args = parse_args(["--competition-mode", "--health-semantic", "rules"])
        args.ark_key = args.speech_key = "offline-test-key"
        self.agent = DoubaoAgent(args)
        self.frames = []

        class Socket:
            async def send(inner_self, raw):
                self.frames.append(json.loads(raw))

        self.socket = Socket()

    async def asyncTearDown(self):
        await self.agent.close()

    async def test_greeting_emits_speech_and_two_skills(self):
        async def speech(texts):
            async for spoken in texts:
                self.assertEqual(spoken, GREETING)
                yield b"\0\0" * 100

        with patch.object(self.agent, "speech_stream", speech):
            await self.agent.greet(self.socket, wake_triggered=True)
        skills = [(f["skillType"], f["skillName"]) for f in self.frames
                  if f["type"] == T["skill"]]
        self.assertEqual(skills, [("gesture", "wave_hands"), ("emotion", "happy")])
        self.assertTrue(self.agent.health_flow.awaiting_health)

    async def test_health_round_does_not_need_llm_and_remembers_state(self):
        self.agent._competition_greeted = True
        self.agent.health_flow.begin()

        class Recognized:
            async def finish(self):
                return "今天有点累"

        async def speech(texts):
            async for _ in texts:
                yield b"\0\0" * 100

        def forbidden_llm(*args, **kwargs):
            raise AssertionError("The fixed health-check reply must not use the LLM")

        with patch.object(self.agent.llm, "stream", forbidden_llm), \
                patch.object(self.agent, "speech_stream", speech):
            await asyncio.wait_for(self.agent.agent_round(
                self.socket, {"eventId": "health-test"}, b"", Recognized()), 3)

        spoken = "".join(f["text"] for f in self.frames if f["type"] == T["llm_delta"])
        self.assertIn("有些累", spoken)
        self.assertTrue(any(f["type"] == T["skill"] and f["skillName"] == "love"
                            for f in self.frames))
        self.assertIn("感到疲惫", self.agent.health_flow.memory_context())
        self.assertTrue(self.agent.health_flow.awaiting_health)
        self.assertTrue(self.agent.health_flow.awaiting_followup)

        class Followup:
            async def finish(self):
                return "休息得不太好"

        self.frames.clear()
        with patch.object(self.agent.llm, "stream", forbidden_llm), \
                patch.object(self.agent, "speech_stream", speech):
            await asyncio.wait_for(self.agent.agent_round(
                self.socket, {"eventId": "followup-test"}, b"", Followup()), 3)
        spoken = "".join(f["text"] for f in self.frames if f["type"] == T["llm_delta"])
        self.assertIn("昨晚没休息好", spoken)
        self.assertFalse(self.agent.health_flow.awaiting_health)
        self.assertIn("昨晚休息欠佳", self.agent.health_flow.memory_context())

        class Recall:
            async def finish(self):
                return "知道我刚才说了些什么吗？"

        self.frames.clear()
        with patch.object(self.agent.llm, "stream", forbidden_llm), \
                patch.object(self.agent, "speech_stream", speech):
            await asyncio.wait_for(self.agent.agent_round(
                self.socket, {"eventId": "recall-test"}, b"", Recall()), 3)
        spoken = "".join(f["text"] for f in self.frames if f["type"] == T["llm_delta"])
        self.assertIn("您说今天有些累", spoken)
        self.assertIn("昨晚休息得不太好", spoken)
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))


if __name__ == "__main__":
    unittest.main()
