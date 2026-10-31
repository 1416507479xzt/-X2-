"""Offline model orchestration and AimDK contracts. Never contacts a robot/cloud."""
import asyncio
import json
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from x2_agent.agent import DoubaoAgent
from x2_agent.agent_config import AgentConfig
from x2_agent.gateway import T
from x2_agent.model_dialogue import ModelDialogue, validate_reply, generate_dialogue, FALLBACK_REPLY
from x2_agent.presentation import AimdkPresentation, unity_plan, capabilities


def answer(**overrides):
    value = dict(intent="health", action="followup", reply="听起来有些累。昨晚休息得怎么样？",
                 emotion="sympathy", gesture=None)
    value.update(overrides)
    return value


class ContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dialogue = ModelDialogue()
        self.dialogue.begin()
        self.ctx = self.dialogue.context()
        self.ctx["capabilities"] = capabilities()

    def validate(self, **kw):
        return validate_reply(json.dumps(answer(**kw), ensure_ascii=False), self.ctx)

    def test_valid_plan_and_memory(self):
        result = self.validate()
        self.assertIsNotNone(result)
        self.dialogue.commit("脖子不舒服", result)
        result = answer(action="close", reply="腰也有些不舒服，您先歇一歇，有需要再叫我。")
        self.dialogue.commit("腰也酸", result)
        self.assertEqual(self.dialogue.health_quotes, ["脖子不舒服", "腰也酸"])
        self.assertEqual(self.dialogue.health_rounds, 2)

    def test_opening_symptom_apology_is_softened_without_changing_question(self):
        draft = answer(reply="很抱歉您今天感觉不舒服，请问是哪里不舒服呢？")
        normalized = validate_reply(json.dumps(draft, ensure_ascii=False), self.ctx,
                                    degrade_presentation=True)
        self.assertEqual(normalized["reply"], "听您说今天感觉不舒服，请问是哪里不舒服呢？")

    def test_reject_arbitrary_action_emotion_and_extra_sdk_parameters(self):
        for changes in [dict(gesture="walk"), dict(gesture={"motion": 1002}),
                        dict(emotion="invented"), dict(priority=99), dict(gesture=1)]:
            with self.subTest(changes=changes):
                self.assertIsNone(self.validate(**changes))

    def test_no_control_cannot_produce_actuation(self):
        self.ctx["capabilities"] = capabilities(False)
        self.assertIsNone(self.validate())
        self.assertIsNotNone(self.validate(emotion=None))

    def test_backend_catalogs_and_meanings(self):
        from x2_agent.presentation import EMOJI_IDS, MOTIONS
        unity = capabilities()
        aimdk = capabilities(backend="aimdk")
        self.assertEqual(len(EMOJI_IDS), 20)
        self.assertEqual(len(MOTIONS), 20)
        for catalog in (unity, aimdk):
            self.assertEqual(set(catalog["emotions"]), set(catalog["emotion_meanings"]))
            self.assertEqual(set(catalog["gestures"]), set(catalog["gesture_meanings"]))
        self.assertNotIn("clap", unity["gestures"])
        self.assertIn("clap", aimdk["gestures"])
        self.assertEqual(MOTIONS["clap"], (3017, 11))
        self.assertEqual(MOTIONS["heart_both"], (1007, 3))
        self.assertEqual(EMOJI_IDS["neutral"], 10)
        self.assertEqual(EMOJI_IDS["sympathy"], 120)
        self.assertEqual(capabilities(False, "aimdk")["gestures"], [])
        self.assertEqual(unity["explanation_gestures"], ["open_arms"])
        self.assertEqual(aimdk["explanation_gestures"], ["raise_right", "raise_left"])
        self.assertEqual(capabilities(False)["explanation_gestures"], [])

    def test_model_can_choose_expanded_but_not_unavailable_capabilities(self):
        for emotion in ("neutral", "happy", "sad", "surprised", "admiration"):
            self.assertIsNotNone(self.validate(emotion=emotion, gesture="open_arms"))
        self.assertIsNone(self.validate(gesture="clap"))
        self.ctx["capabilities"] = capabilities(backend="aimdk")
        self.assertIsNotNone(self.validate(emotion="thinking", gesture="heart_both"))
        self.assertEqual(unity_plan("neutral", "open_arms", "您好"),
                         [("emotion", "neutral", {}), ("gesture", "open_arms", {})])
        with self.assertRaises(ValueError):
            unity_plan("happy", "clap", "您好")

    def test_two_round_limit_and_decline(self):
        self.ctx["health_rounds"] = 1
        self.assertIsNone(self.validate())
        self.assertIsNone(self.validate(intent="decline"))
        self.assertIsNotNone(self.validate(intent="decline", action="close", reply="好的，有需要再叫我。"))

    def test_greeting_only_on_wake_context(self):
        self.assertIsNone(self.validate(intent="greeting", action="continue"))
        self.ctx["turn_kind"] = "greeting"
        self.assertIsNotNone(self.validate(intent="greeting", action="continue"))

    def test_unity_mapping_is_explicit(self):
        plan = unity_plan("sympathy", "wave_hands", "您好")
        self.assertEqual([(x[0], x[1]) for x in plan],
                         [("emotion", "love"), ("gesture", "wave_hands")])
        with self.assertRaises(ValueError):
            unity_plan("happy", "walk", "你好")

    async def test_bad_json_tools_timeout_and_cancellation(self):
        async def invalid(*a, **kw):
            yield "text", "这不是JSON"
        self.assertIsNone(await generate_dialogue(NS(stream=invalid), "您好", self.ctx, "m", "k"))
        async def slow(*a, **kw):
            await asyncio.sleep(5)
            yield "text", "{}"
        self.assertIsNone(await generate_dialogue(NS(stream=slow), "您好", self.ctx, "m", "k", timeout=.01))
        task = asyncio.create_task(generate_dialogue(NS(stream=slow), "您好", self.ctx, "m", "k"))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch("x2_agent.agent.LlmClient"), patch("x2_agent.agent.BidiTtsClient"):
            self.agent = DoubaoAgent(AgentConfig(
                speech_key="offline", ark_key="offline", competition_mode=True))
        self.agent.health_flow.begin()
        self.agent._competition_greeted = True
        self.frames = []
        self.agent.send = AsyncMock(side_effect=lambda ws, obj: self.frames.append(obj))
        self.plan = answer()
        self.calls = []
        async def llm(prompt, history, *a, **kw):
            self.calls.append(json.loads(history[0]["content"]))
            yield "text", json.dumps(self.plan, ensure_ascii=False)
        self.agent.llm.stream = llm
        async def speech(texts):
            async for text in texts:
                self.assertNotIn('"intent"', text)
                yield b"\0\0"
        self.agent.speech_stream = speech

    async def turn(self, text):
        await self.agent.agent_round(None, {"eventId": "test"}, b"",
                                    NS(finish=AsyncMock(return_value=text)))

    def spoken(self):
        return "".join(f.get("text", "") for f in self.frames if f["type"] == T["llm_delta"])

    async def test_common_keyword_still_goes_through_model(self):
        with patch.object(self.agent.health_flow, "respond", side_effect=AssertionError("legacy route")):
            await self.turn("今天有点疲惫")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.spoken(), self.plan["reply"])
        skills = [f for f in self.frames if f["type"] == T["skill"]]
        self.assertEqual([f["skillName"] for f in skills], ["love"])
        kinds = [f["type"] for f in self.frames]
        self.assertLess(kinds.index(T["skill"]), kinds.index(T["tts_delta"]))

    async def test_model_decides_explicit_and_spontaneous_wave(self):
        self.plan = answer(intent="chat", action="continue", reply="您好，很高兴见到您。",
                           emotion="happy", gesture="wave_hands")
        await self.turn("请挥挥手")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(any(f.get("skillName") == "wave_hands" for f in self.frames))

    async def test_wake_greeting_is_model_generated_and_remembered(self):
        self.agent._competition_greeted = False
        self.plan = answer(intent="greeting", action="continue", reply="您好，今天感觉怎么样？",
                           emotion="happy", gesture="wave_hands")
        self.plan = {k: self.plan[k] for k in ("reply", "emotion", "gesture")}
        await self.agent.greet(None)
        self.assertEqual(self.calls, [])
        await self.turn("林夕林夕")
        self.assertTrue(self.agent._competition_greeted)
        self.assertEqual(self.spoken(), self.plan["reply"])
        self.assertEqual(self.agent.health_flow.model_dialogue.health_rounds, 0)
        self.assertIn("今天感觉", self.agent.health_flow.model_dialogue.verbatim_turns[-1]["assistant"])
        self.assertFalse(any(f["type"] == T["skill"] and f.get("skillType") == "gesture"
                             for f in self.frames))

    async def test_wake_greeting_uses_normal_question_when_model_times_out(self):
        self.agent._competition_greeted = False
        with patch("x2_agent.agent.generate_dialogue", new=AsyncMock(return_value=None)) as generate:
            await self.turn("林夕林夕")
        self.assertEqual(generate.call_args.kwargs["timeout"], 3.0)
        self.assertEqual(self.spoken(), "您好，我是灵犀。见到您真好！您今天感觉怎么样？")
        self.assertTrue(self.agent._competition_greeted)
        self.assertTrue(self.agent.health_flow.awaiting_health)
        self.assertIn("今天感觉", self.agent.health_flow.model_dialogue.verbatim_turns[-1]["assistant"])
        self.frames.clear()
        await self.turn("林夕林夕")
        self.assertEqual(self.spoken(), "我在，您说。")

    def test_unity_greeting_disables_failed_gestures_without_changing_aimdk_catalog(self):
        unity = self.agent._model_context(greeting=True)["capabilities"]
        self.assertEqual(unity["gestures"], [])
        self.assertEqual(unity["gesture_meanings"], {})
        self.assertEqual(unity["explanation_gestures"], [])
        self.agent.args.presentation_backend = "aimdk"
        aimdk = self.agent._model_context(greeting=True)["capabilities"]
        self.assertIn("wave_hands", aimdk["gestures"])

    def test_recent_or_failed_gesture_is_not_offered_to_model(self):
        self.agent._last_model_gesture = time.monotonic() - 20
        self.assertEqual(self.agent._model_context()["capabilities"]["gestures"], [])
        self.agent._last_model_gesture = float("-inf")
        self.agent._failed_gestures_until["open_arms"] = time.monotonic() + 40
        available = self.agent._model_context()["capabilities"]
        self.assertNotIn("open_arms", available["gestures"])
        self.assertNotIn("open_arms", available["explanation_gestures"])
        self.agent._failed_gestures_until["open_arms"] = time.monotonic() - 1
        self.assertIn("open_arms", self.agent._model_context()["capabilities"]["gestures"])

    async def test_failure_does_not_trigger_expression_or_motion(self):
        self.plan = answer(intent="invented", gesture="walk")
        await self.turn("往前走")
        self.assertEqual(self.spoken(), FALLBACK_REPLY)
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))
        self.assertEqual(self.agent.health_flow.model_dialogue.health_rounds, 0)
        self.assertEqual(self.agent.health_flow.model_dialogue.verbatim_turns[-1],
                         {"user": "往前走", "assistant": "", "response_status": "unanswered"})

    async def test_control_revoked_during_synthesis(self):
        async def speech(texts):
            async for _ in texts:
                self.agent.control_active = False
                yield b"\0\0"
        self.agent.speech_stream = speech
        await self.turn("今天累")
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))
        self.assertEqual(self.spoken(), self.plan["reply"])

    async def test_model_selected_explanation_gesture_uses_existing_skill(self):
        self.plan = answer(intent="other", action="continue", reply="睡前可以留一点时间放松。",
                           emotion="neutral", gesture="open_arms")
        await self.turn("有什么睡眠方面的生活建议吗")
        gestures = [f for f in self.frames if f["type"] == T["skill"] and f.get("skillType") == "gesture"]
        self.assertEqual([f["skillName"] for f in gestures], ["open_arms"])
        self.assertEqual(self.agent._model_context()["capabilities"]["explanation_gestures"], [])

    async def test_advice_does_not_force_gesture_when_model_selects_none(self):
        self.plan = answer(intent="other", action="continue", reply="睡前可以留一点时间放松。",
                           emotion="neutral", gesture=None)
        await self.turn("只说话，不要做动作")
        self.assertFalse(any(f["type"] == T["skill"] and f.get("skillType") == "gesture"
                             for f in self.frames))

    async def test_tts_failure_rolls_back_memory_and_does_not_dispatch(self):
        async def failed(texts):
            async for _ in texts:
                raise RuntimeError("offline")
                yield b""
        self.agent.speech_stream = failed
        await self.turn("脖子不舒服")
        self.assertEqual(self.agent.health_flow.model_dialogue.health_quotes, [])
        self.assertEqual(self.agent.health_flow.model_dialogue.verbatim_turns[-1],
                         {"user": "脖子不舒服", "assistant": "", "response_status": "unanswered"})
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))


class AimdkTests(unittest.IsolatedAsyncioTestCase):
    def make_backend(self, mode="STAND_DEFAULT", status=100, accepted=True):
        b = object.__new__(AimdkPresentation)
        b.lock = asyncio.Lock()
        b.last_motion = float("-inf")
        b.types = {k: NS(Request=lambda: NS(motion=NS(value=0), area=NS(value=0)))
                   for k in ("emoji", "motion", "mode")}
        calls = []
        async def call(kind, req):
            calls.append((kind, req))
            if kind == "mode":
                return NS(header=NS(code=0), info=NS(
                    action_desc=mode, current_action=NS(value=200), status=NS(value=status)))
            if kind == "emoji":
                return NS(success=accepted, header=NS(code=0))
            return NS(response=NS(header=NS(code=0 if accepted else 1), task_id=23))
        b._call = call
        return b, calls

    async def test_exact_ids_and_non_interrupting_safe_priority(self):
        b, calls = self.make_backend()
        receipts = await b.dispatch("sympathy", "wave_hands", lambda: True)
        self.assertEqual([r["status"] for r in receipts], ["accepted", "accepted"])
        emoji, motion = calls[0][1], calls[2][1]
        self.assertEqual((emoji.emotion_id, emoji.mode, emoji.priority), (120, 1, 1))
        self.assertEqual((motion.motion.value, motion.area.value, motion.interrupt), (1002, 2, False))
        await b.dispatch(None, "wave_hands", lambda: True)
        self.assertEqual(sum(k == "motion" for k, _ in calls), 1)

    async def test_unknown_or_transition_mode_blocks_even_if_deprecated_numeric_matches(self):
        for mode, status in [("LOCOMOTION_DEFAULT", 100), ("STAND_DEFAULT", 200), ("", 100)]:
            b, calls = self.make_backend(mode, status)
            result = await b.dispatch(None, "wave_hands", lambda: True)
            self.assertEqual(result[0]["status"], "blocked")
            self.assertFalse(any(k == "motion" for k, _ in calls))

    async def test_no_control_and_outer_emoji_success(self):
        b, calls = self.make_backend(accepted=False)
        await b.dispatch("happy", "wave_hands", lambda: False)
        self.assertEqual(calls, [])
        results = await b.dispatch("happy", None, lambda: True)
        self.assertEqual(results[0]["status"], "rejected")

    async def test_timeout_is_unknown_and_not_retried(self):
        b, calls = self.make_backend()
        original = b._call
        async def timeout(kind, req):
            if kind == "motion":
                calls.append((kind, req))
                return None
            return await original(kind, req)
        b._call = timeout
        result = await b.dispatch(None, "wave_hands", lambda: True)
        self.assertEqual(result[0]["status"], "unknown")
        self.assertEqual(sum(k == "motion" for k, _ in calls), 1)

    def test_real_backend_requires_explicit_configuration(self):
        with self.assertRaises(ValueError):
            AgentConfig(speech_key="x", ark_key="x", presentation_backend="aimdk")


if __name__ == "__main__":
    unittest.main()
