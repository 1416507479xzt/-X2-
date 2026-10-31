"""Offline stage-one integration: no credentials, cloud calls or robot required."""
import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

from x2_agent.agent import DoubaoAgent, COMPETITION_EMPTY_REPLY, is_explicit_skill_request, is_wake_utterance
from x2_agent.agent_config import AgentConfig
from x2_agent.gateway import T


class HealthIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = DoubaoAgent(AgentConfig(
            speech_key="offline", ark_key="offline", competition_mode=True,
            health_semantic="rules", elder_name="王阿姨"))
        self.agent.health_flow.begin("王阿姨")
        self.agent._competition_greeted = True
        self.frames = []

        class Socket:
            async def send(inner, raw):
                self.frames.append(json.loads(raw))

        self.socket = Socket()

    async def asyncTearDown(self):
        await self.agent.close()

    @staticmethod
    async def speech(texts):
        async for _ in texts:
            yield b"\0\0" * 100

    async def run_turn(self, text):
        class Recognized:
            async def finish(inner):
                return text
        await asyncio.wait_for(self.agent.agent_round(
            self.socket, {"eventId": "offline-health"}, b"", Recognized()), 3)

    def spoken(self):
        return "".join(f["text"] for f in self.frames if f["type"] == T["llm_delta"])

    async def test_health_expression_is_sent_at_first_audio_not_before_synthesis(self):
        ready, release = asyncio.Event(), asyncio.Event()

        async def delayed_speech(texts):
            async for _ in texts:
                ready.set()
                await release.wait()
                yield b"\0\0" * 100

        with patch.object(self.agent, "speech_stream", delayed_speech), \
                patch.object(self.agent.llm, "stream", side_effect=AssertionError("No LLM")):
            task = asyncio.create_task(self.run_turn("今天有点疲惫"))
            try:
                await asyncio.wait_for(ready.wait(), 1)
                self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))
            finally:
                release.set()
                await task
        skills = [f for f in self.frames if f["type"] == T["skill"]]
        self.assertEqual([f["skillName"] for f in skills], ["love"])
        self.assertGreaterEqual(skills[0]["skillParam"]["durationMs"], 3000)
        kinds = [f["type"] for f in self.frames]
        self.assertLess(kinds.index(T["skill"]), kinds.index(T["tts_delta"]))
        self.assertNotIn("呜", self.spoken())
        self.assertEqual(self.agent.metrics.get_counter("llm_success_count"), 0)
        self.assertEqual(self.agent.metrics.get_counter("health_reply_count"), 1)

    async def test_handoff_preserves_memory_and_answers_new_question_without_tools(self):
        self.agent.health_flow.respond("有点累")
        calls = []

        async def llm(prompt, history, *args, **kwargs):
            calls.append((prompt, history, kwargs))
            yield "text", "我还没有您的用药计划，不能判断是否到服药时间。"

        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", llm):
            await self.run_turn("今天该吃药了吗")
        self.assertIn("用药计划", self.spoken())
        self.assertNotIn("注意休息", self.spoken())
        self.assertIn("感到疲惫", calls[0][0])
        self.assertEqual(calls[0][1][-1]["content"], "今天该吃药了吗")
        self.assertIsNone(calls[0][2]["tools"])
        self.assertFalse(self.agent.health_flow.awaiting_followup)

    async def test_unsolicited_tool_only_output_cannot_replace_answer_with_emotion_ack(self):
        async def llm(*args, **kwargs):
            yield "tool_calls", [{"name": "robot_skill", "arguments":
                                  '{"skillType":"emotion","skillName":"sad"}'}]
        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", llm):
            await self.run_turn("今天该吃药了吗")
        self.assertEqual(self.spoken(), COMPETITION_EMPTY_REPLY)
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))

    async def test_explicit_gesture_still_available(self):
        async def llm(*args, **kwargs):
            self.assertIsNotNone(kwargs["tools"])
            yield "tool_calls", [{"name": "robot_skill", "arguments":
                                  '{"skillType":"gesture","skillName":"wave_hands"}'}]
        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", llm):
            await self.run_turn("请挥挥手")
        self.assertTrue(any(f.get("skillName") == "wave_hands" for f in self.frames))

    async def test_semantic_fallback_only_for_unknown_phrase_and_not_spoken_as_json(self):
        self.agent.args.health_semantic = "auto"
        observation = {"intent": "health", "state": "感到疲惫", "detail": None,
                       "evidence": "电量只剩一格"}
        with patch("x2_agent.agent.interpret_health", new_callable=AsyncMock,
                   return_value=observation) as semantic, \
                patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", side_effect=AssertionError("No response LLM")):
            await self.run_turn("我像电量只剩一格似的")
        semantic.assert_awaited_once()
        self.assertEqual(self.agent.health_flow.health_state, "感到疲惫")
        self.assertNotIn("intent", self.spoken())
        self.assertIn("？", self.spoken())

    async def test_explicit_wave_does_not_authorize_unrequested_walk(self):
        async def llm(*args, **kwargs):
            yield "tool_calls", [{"name": "robot_skill", "arguments":
                                  '{"skillType":"movement","skillName":"walk"}'}]
        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", llm):
            await self.run_turn("请挥挥手")
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))
        self.assertIn("不会执行", self.spoken())

    async def test_free_form_followup_uses_history_without_authorizing_skills(self):
        with patch.object(self.agent, "speech_stream", self.speech):
            await self.run_turn("心情不太好")
        self.frames.clear()

        async def llm(prompt, history, *args, **kwargs):
            self.assertIn("遇到什么事", prompt)
            self.assertIn("第二轮补充交流", prompt)
            self.assertEqual(history[-1]["content"], "跟邻居拌了几句嘴")
            self.assertTrue(any("遇到什么事" in m.get("content", "") for m in history))
            self.assertIsNone(kwargs["tools"])
            yield "text", "跟邻居拌嘴，心里不好受吧。您愿意的话，可以和我说说。"

        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", llm):
            await self.run_turn("跟邻居拌了几句嘴")
        self.assertIn("跟邻居拌嘴", self.spoken())
        self.assertNotIn("细节我还没听清", self.spoken())
        self.assertEqual(self.agent.health_flow.health_state, "心情低落")
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))
        self.assertEqual(self.frames[-1]["type"], T["tts_done"])

    async def test_body_memory_reaches_llm_after_original_turn_leaves_window(self):
        self.agent.health_flow.respond("我现在感觉脖子有点疼")
        self.agent.health_flow.respond("我感觉腰有点酸")
        self.agent.history = [{"role": "user", "content": "我现在感觉脖子有点疼"}]
        for i in range(12):
            self.agent.history.extend([{"role": "user", "content": "其他聊天"},
                                       {"role": "assistant", "content": "普通回答"}])

        async def llm(prompt, history, *args, **kwargs):
            self.assertNotIn("脖子", str(history))
            self.assertIn("脖子有点疼", prompt)
            self.assertIn("腰有点酸", prompt)
            yield "text", "我记得您提过脖子疼和腰酸。"

        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", llm):
            await self.run_turn("可以帮我回顾一下这些情况吗")
        self.assertIn("脖子疼和腰酸", self.spoken())
        self.assertFalse(any(f["type"] == T["error"] for f in self.frames))

    async def test_semantic_timeout_result_uses_local_clarification(self):
        self.agent.args.health_semantic = "auto"
        with patch("x2_agent.agent.interpret_health", new_callable=AsyncMock,
                   return_value=None) as semantic, \
                patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", side_effect=AssertionError("No response LLM")):
            await self.run_turn("有一种说不出的感觉")
        semantic.assert_awaited_once()
        self.assertIn("？", self.spoken())
        self.assertFalse(any(f["type"] == T["error"] for f in self.frames))

    async def test_failed_tts_rolls_back_health_state_and_history(self):
        before = copy.deepcopy(self.agent.health_flow.__dict__)

        async def failed_speech(texts):
            async for _ in texts:
                raise RuntimeError("offline synthesis failure")
                yield b""

        with patch.object(self.agent, "speech_stream", failed_speech):
            with self.assertLogs("x2_agent.agent", level="ERROR"):
                await self.run_turn("有点累")
        self.assertEqual(self.agent.health_flow.__dict__, before)
        self.assertEqual(self.agent.history, [])
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))
        self.assertEqual(self.frames[-1]["type"], T["tts_done"])

    async def test_no_control_still_answers_without_automatic_action_error(self):
        self.agent.control_active = False
        with patch.object(self.agent, "speech_stream", self.speech):
            await self.run_turn("今天有点累")
        self.assertIn("累", self.spoken())
        self.assertNotIn("控制权", self.spoken())
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))

    async def test_authority_lost_while_synthesizing_suppresses_presentation(self):
        async def speech(texts):
            async for _ in texts:
                self.agent.control_active = False
                yield b"\0\0" * 100
        with patch.object(self.agent, "speech_stream", speech):
            await self.run_turn("今天有点累")
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))
        self.assertTrue(any(f["type"] == T["tts_delta"] for f in self.frames))
        self.assertEqual(self.agent.health_flow.health_state, "感到疲惫")

    async def test_partial_audio_failure_still_rolls_back_followup(self):
        self.agent.health_flow.respond("有点累")
        before = copy.deepcopy(self.agent.health_flow.__dict__)

        async def speech(texts):
            async for _ in texts:
                yield b"\0\0" * 100
                raise RuntimeError("offline partial TTS failure")

        with patch.object(self.agent, "speech_stream", speech):
            with self.assertLogs("x2_agent.agent", level="ERROR"):
                await self.run_turn("昨晚没睡好")
        self.assertTrue(any(f["type"] == T["tts_delta"] for f in self.frames))
        self.assertEqual(self.agent.health_flow.__dict__, before)
        self.assertEqual(self.agent.history, [])
        self.assertEqual(self.frames[-1]["type"], T["tts_done"])

    async def test_cancelled_round_closes_stream_and_rolls_back_state(self):
        before = copy.deepcopy(self.agent.health_flow.__dict__)
        started, closed = asyncio.Event(), asyncio.Event()

        async def speech(texts):
            try:
                async for _ in texts:
                    yield b"\0\0" * 100
                    started.set()
                    await asyncio.Event().wait()
            finally:
                closed.set()

        with patch.object(self.agent, "speech_stream", speech):
            task = asyncio.create_task(self.run_turn("今天有点累"))
            try:
                await asyncio.wait_for(started.wait(), 1)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertTrue(closed.is_set())
        self.assertEqual(self.agent.health_flow.__dict__, before)
        self.assertEqual(self.agent.history, [])
        self.assertEqual(self.frames[-1]["type"], T["tts_done"])

    async def test_known_phrase_in_auto_mode_does_not_use_classifier(self):
        self.agent.args.health_semantic = "auto"
        with patch("x2_agent.agent.interpret_health", new_callable=AsyncMock) as semantic, \
                patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", side_effect=AssertionError("No model")):
            await self.run_turn("今天有点疲惫")
        semantic.assert_not_awaited()
        self.assertFalse(any(f["type"] == T["error"] for f in self.frames))

    async def test_reconnect_does_not_restart_interview_or_repeat_wave(self):
        self.agent._competition_greeted = False
        with patch.object(self.agent, "speech_stream", self.speech):
            await self.agent.greet(self.socket, wake_triggered=True)
            self.agent.health_flow.respond("今天有点累")
            before = copy.deepcopy(self.agent.health_flow.__dict__)
            self.frames.clear()
            await self.agent.greet(self.socket)
        self.assertEqual(self.frames, [])
        self.assertEqual(self.agent.health_flow.__dict__, before)

    def arm_wake(self):
        self.agent._competition_greeted = False
        self.agent.health_flow = type(self.agent.health_flow)()

    async def test_connect_waits_silently_for_voice_wake(self):
        self.arm_wake()
        with patch.object(self.agent, "speech_stream", side_effect=AssertionError("No greeting before wake")):
            await self.agent.greet(self.socket)
        self.assertEqual(self.frames, [])
        self.assertFalse(self.agent.health_flow.awaiting_health)

    async def test_unrelated_speech_before_wake_is_ignored_and_turn_finishes(self):
        self.arm_wake()
        with patch.object(self.agent.llm, "stream", side_effect=AssertionError("No LLM before wake")), \
                patch.object(self.agent, "speech_stream", side_effect=AssertionError("No TTS before wake")):
            await self.run_turn("今天有点累")
        self.assertEqual(self.spoken(), "")
        self.assertEqual(self.agent.history, [])
        self.assertFalse(self.agent._competition_greeted)
        self.assertEqual(self.frames[-1]["type"], T["tts_done"])
        self.assertEqual(self.frames[-1]["eventId"], "offline-health")

    async def test_voice_wake_greets_on_captured_event_and_followup_continues(self):
        self.arm_wake()
        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", side_effect=AssertionError("No model needed")):
            await self.run_turn("灵犀，灵犀！")
            # Even a legacy --elder-name launch must not label an unknown visitor.
            self.assertEqual(self.agent.args.elder_name, "王阿姨")
            self.assertTrue(self.spoken().startswith("您好"))
            self.assertNotIn("王阿姨", self.spoken())
            self.assertIn("今天感觉怎么样", self.spoken())
            self.assertTrue(self.agent._competition_greeted)
            self.assertTrue(self.agent.health_flow.awaiting_health)
            self.assertTrue(all(f["eventId"] == "offline-health" for f in self.frames))
            self.assertEqual([f["skillName"] for f in self.frames if f["type"] == T["skill"]],
                             ["wave_hands", "happy"])
            self.frames.clear()
            await self.run_turn("今天有点累")
            self.assertIn("昨晚休息", self.spoken())
            self.assertTrue(self.agent.health_flow.awaiting_followup)

    async def test_failed_wake_greeting_can_be_retried(self):
        self.arm_wake()
        async def failed_speech(texts):
            async for _ in texts:
                raise RuntimeError("offline wake synthesis failure")
                yield b""
        with patch.object(self.agent, "speech_stream", failed_speech):
            with self.assertLogs("x2_agent.agent", level="WARNING"):
                await self.run_turn("灵犀")
        self.assertFalse(self.agent._competition_greeted)
        self.assertFalse(self.agent.health_flow.awaiting_health)
        self.frames.clear()
        with patch.object(self.agent, "speech_stream", self.speech):
            await self.run_turn("灵犀")
        self.assertTrue(self.agent._competition_greeted)
        self.assertIn("今天感觉怎么样", self.spoken())

    async def test_real_log_wake_transcriptions_start_greeting(self):
        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", side_effect=AssertionError("Wake must not need LLM")):
            for transcript in ("你好，灵犀 X2。", "林夕林夕", "哦，林夕。", "你好，林夕。", "你好，林欣。",
                               "凌曦，凌曦", "您好，琳熙！"):
                with self.subTest(transcript=transcript):
                    self.arm_wake()
                    self.frames.clear()
                    await self.run_turn(transcript)
                    self.assertTrue(self.agent._competition_greeted)
                    self.assertIn("您好，我是灵犀", self.spoken())
                    self.assertNotIn("王阿姨", self.spoken())
                    self.assertTrue(self.agent.health_flow.awaiting_health)
                    self.assertEqual(self.frames[-1]["type"], T["tts_done"])

    async def test_repeated_wake_preserves_current_question(self):
        self.agent.health_flow.respond("今天有点累")
        before = copy.deepcopy(self.agent.health_flow.__dict__)
        with patch.object(self.agent, "speech_stream", self.speech), \
                patch.object(self.agent.llm, "stream", side_effect=AssertionError("No model needed")):
            await self.run_turn("灵犀灵犀")
        self.assertEqual(self.spoken(), "我在，您说。")
        self.assertEqual(self.agent.health_flow.__dict__, before)
        self.assertFalse(any(f["type"] == T["skill"] for f in self.frames))


class CompetitionBoundaryTests(unittest.TestCase):
    def test_wake_word_matches_calls_not_mentions_or_negation(self):
        for text in ("灵犀", "你好灵犀", "你好，灵犀！", "小灵犀在吗", "灵犀你好",
                     "灵犀灵犀", "灵犀，灵犀！", "灵犀灵犀灵犀", "你好灵犀，灵犀你在吗",
                     "灵溪灵溪", "灵汐", "灵熙", "林夕林夕", "你好，林夕。", "你好，林欣。",
                     "你好，灵犀 X2。", "灵犀x2", "你好林夕X2",
                     "凌曦凌曦", "零西，零西", "铃希", "琳熙琳熙", "邻溪",
                     "小凌曦在吗", "灵犀；林夕：凌曦！", "灵犀" * 6):
            self.assertTrue(is_wake_utterance(text), text)
        for text in ("", "灵犀是什么", "不要唤醒灵犀", "我今天有点累", "我在和灵犀说话",
                     "别叫灵犀灵犀了", "我刚才叫了灵犀灵犀", "林夕是谁", "灵犀X2多少钱",
                     "今天今天今天晚上早点睡吧，皮子。", "当时说两个小时。", "傻喽。",
                     "吃啥呢？我一回来你就吃光了。", "凌曦是谁", "不要叫琳熙",
                     "灵犀灵犀今天累了", "灵气灵气", "联系联系", "邻居", "零食",
                     "灵犀" * 7, "lingxi", "灵🙂犀", "灵犀去散步", "林欣", "林欣林欣"):
            self.assertFalse(is_wake_utterance(text), text)

    def test_explicit_command_gate(self):
        for text in ("请挥挥手", "请你显示开心表情", "往前走一米", "停止动作"):
            self.assertTrue(is_explicit_skill_request(text), text)
        for text in ("我今天不开心", "不要挥手", "我腰疼能往前走一米吗", "为什么你是开心表情"):
            self.assertFalse(is_explicit_skill_request(text), text)

    def test_invalid_semantic_setting_rejected(self):
        with self.assertRaises(ValueError):
            AgentConfig(speech_key="offline", ark_key="offline", health_semantic="invalid")


if __name__ == "__main__":
    unittest.main()
