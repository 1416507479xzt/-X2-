"""Contract/state tests; semantic quality requires live evaluation."""
import json
import unittest
from types import SimpleNamespace

from x2_agent.model_dialogue import ModelDialogue, validate_reply, generate_dialogue
from x2_agent.presentation import capabilities


def plan(intent, reply, action="continue"):
    return dict(intent=intent, action=action, reply=reply, emotion="neutral", gesture=None)


class PurposeTests(unittest.IsolatedAsyncioTestCase):
    async def test_opening_status_is_not_lost_as_acknowledgement(self):
        memory = ModelDialogue()
        memory.begin()
        calls = []
        async def stream(prompt, *args, **kwargs):
            calls.append(prompt)
            value = (plan("acknowledge", "好的，您感觉舒服就好。") if len(calls) == 1 else
                     plan("health", "听您说今天还可以。还有哪里不舒服吗？", "followup"))
            yield "text", json.dumps(value, ensure_ascii=False)
        result = await generate_dialogue(SimpleNamespace(stream=stream), "我今天感觉还可以啊",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 2)
        self.assertIn("不是简单致谢", calls[1])
        self.assertEqual((result["intent"], result["action"]), ("health", "followup"))

    async def test_repeated_bad_opening_status_keeps_question_not_apology(self):
        memory = ModelDialogue()
        memory.begin()
        async def stream(*args, **kwargs):
            yield "text", json.dumps(plan("acknowledge", "好的，您感觉舒服就好。"), ensure_ascii=False)
        result = await generate_dialogue(SimpleNamespace(stream=stream), "我今天感觉还可以啊",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual((result["intent"], result["action"]), ("health", "followup"))
        self.assertIn("不舒服吗？", result["reply"])

    async def test_logged_long_ack_then_short_ack_still_advances_interview(self):
        memory = ModelDialogue()
        memory.begin()
        calls = []
        async def stream(prompt, *args, **kwargs):
            calls.append(prompt)
            text = ("听您说今天还可以，我也放心些。最近身体上还有哪里不舒服吗？" if len(calls) == 1
                    else "好的，您感觉舒服就好。")
            yield "text", json.dumps(plan("acknowledge", text), ensure_ascii=False)
        result = await generate_dialogue(SimpleNamespace(stream=stream), "我今天感觉还可以啊",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 2)
        self.assertIn("不是简单致谢", calls[1])
        self.assertEqual((result["intent"], result["action"]), ("health", "followup"))

    def test_courtesy_action_mismatch_is_normalized_only_for_model_delivery(self):
        ctx = self.context()
        draft = plan("acknowledge", "好的。", "close")
        self.assertIsNone(validate_reply(json.dumps(draft), ctx))
        delivered = validate_reply(json.dumps(draft), ctx, degrade_presentation=True)
        self.assertEqual(delivered["action"], "continue")

    async def test_farewell_action_mismatch_is_normalized_without_apology(self):
        memory = ModelDialogue()
        async def stream(*args, **kwargs):
            yield "text", json.dumps(plan("decline", "好的，有需要再叫我。", "continue"), ensure_ascii=False)
        result = await generate_dialogue(SimpleNamespace(stream=stream), "没有其他问题了",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual((result["intent"], result["action"]), ("decline", "close"))

    def setUp(self):
        self.memory = ModelDialogue()
        self.memory.begin()
        self.memory.commit("疲惫", plan("health", "昨晚睡得好吗？", "followup"))
        self.memory.commit("睡得不好", plan("health", "希望您今天舒服一些。", "close"))

    def context(self):
        return {**self.memory.context(), "capabilities": capabilities()}

    def test_ack_does_not_advance_interview_or_forget_history(self):
        before = list(self.memory.verbatim_turns)
        for _ in range(2):
            answer = plan("acknowledge", "嗯，好。")
            self.assertIsNotNone(validate_reply(json.dumps(answer), self.context()))
            self.memory.commit("好的", answer)
        self.assertEqual(self.memory.health_rounds, 2)
        self.assertFalse(self.memory.interview_active)
        self.assertEqual(self.memory.verbatim_turns[:2], before)

    def test_decline_ack_then_reengage_preserves_memory_without_reinterview(self):
        self.memory.commit("先不聊了", plan("decline", "好的，再见。", "close"))
        self.assertEqual(self.memory.context()["conversation_state"], "ended")
        self.memory.commit("谢谢", plan("acknowledge", "不客气。"))
        self.assertEqual(self.memory.conversation_state, "ended")
        answer = plan("reengage", "您好，我在听，您说。")
        self.assertIsNotNone(validate_reply(json.dumps(answer), self.context()))
        self.memory.commit("你好灵犀", answer)
        self.assertEqual(self.memory.conversation_state, "engaged")
        self.assertFalse(self.memory.interview_active)
        self.assertEqual(self.memory.health_quotes, ["疲惫", "睡得不好"])

    def test_ack_contract_rejects_long_or_question_response(self):
        for reply in ("还有问题吗？", "嗯" * 16):
            diagnostic = {}
            self.assertIsNone(validate_reply(json.dumps(plan("acknowledge", reply)),
                                            self.context(), diagnostics=diagnostic))
            self.assertEqual(diagnostic["reason"], "acknowledgement_not_brief")
        self.assertIsNone(validate_reply(json.dumps(plan("reengage", "您好", "close")), self.context()))

    async def test_fatigue_question_only_is_revised_with_a_practical_tip(self):
        memory = ModelDialogue()
        memory.begin()
        values = [plan("health", "昨晚睡得怎么样？", "followup"),
                  plan("health", "睡前可以听些轻松的音乐，试着放松一下。昨晚睡得怎么样？", "followup")]
        calls = []
        async def stream(prompt, history, *args, **kwargs):
            calls.append(prompt)
            yield "text", json.dumps(values[len(calls) - 1])
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "今天有点疲惫",
                       {**memory.context(), "capabilities": capabilities()}, "model", "key")
        self.assertEqual(len(calls), 1)
        self.assertIn("保持规律的作息", answer["reply"])
        self.assertIn("影响您今天做事了吗", answer["reply"])

    async def test_ended_state_and_old_advice_are_sent_to_model(self):
        self.memory.commit("没有问题了", plan("decline", "有需要随时叫我。", "close"))
        captured = []
        async def stream(prompt, history, *args, **kwargs):
            captured.append(json.loads(history[0]["content"]))
            yield "text", json.dumps(plan("reengage", "您好，我在呢。"))
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "你好灵犀",
                                        self.context(), "model", "key")
        self.assertEqual(answer["intent"], "reengage")
        self.assertEqual(captured[0]["conversation_state"], "ended")
        self.assertEqual(captured[0]["verbatim_turns"][-1]["assistant"], "有需要随时叫我。")

    async def test_healthy_answer_then_medicine_keeps_memory_and_advances(self):
        for first_reply in ("状态不错就好，昨晚睡得怎么样？", "状态不错就好。昨晚睡得怎么样？", "昨晚睡得怎么样？"):
            memory = ModelDialogue()
            memory.begin()
            outputs = [plan("health", first_reply, "followup"),
                       plan("other", "降压药种类不同，不要自行停药或加减量。服用前请对照本人处方或药盒说明，确认服用时间和每次用量。")]
            calls = []
            async def stream(prompt, messages, *args, **kwargs):
                calls.append(json.loads(messages[0]["content"]))
                yield "text", json.dumps(outputs[len(calls) - 1])
            for utterance in ("我今天还好。", "降压药怎么吃？"):
                result = await generate_dialogue(SimpleNamespace(stream=stream), utterance,
                    {**memory.context(), "capabilities": capabilities(), "life_assistance": {"medicines": []}}, "m", "k")
                self.assertIsNotNone(result)
                memory.commit(utterance, result)
            self.assertEqual(len(calls), 2)
            self.assertEqual(memory.health_rounds, 1)
            self.assertFalse(memory.interview_active)
            self.assertEqual(calls[1]["verbatim_turns"][0]["user"], "我今天还好。")

    def test_two_healthy_rounds_close_without_style_failure(self):
        memory = ModelDialogue()
        memory.begin()
        first = plan("health", "状态不错就好，昨晚睡得好吗？", "followup")
        diagnostic = {}
        self.assertIsNotNone(validate_reply(json.dumps(first), {**memory.context(), "capabilities": capabilities()}, diagnostics=diagnostic))
        self.assertEqual(diagnostic["style_note"], "health_followup_single_sentence")
        memory.commit("我今天还好。", first)
        second = plan("health", "听您这么说我也很高兴，有需要随时叫我。", "close")
        self.assertIsNotNone(validate_reply(json.dumps(second), {**memory.context(), "capabilities": capabilities()}))
        memory.commit("我今天挺好的。", second)
        self.assertFalse(memory.interview_active)
        self.assertEqual(memory.health_rounds, 2)
