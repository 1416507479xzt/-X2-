"""Offline stage-one regression cases drawn from natural elderly-care dialogue."""
import unittest

from x2_agent.competition_flow import HealthGreetingFlow


class HealthFlowRobustnessTests(unittest.TestCase):
    def test_short_sleep_answer_keeps_fatigue_in_context(self):
        for answer, expected in (("还行", "昨晚休息良好"), ("好的", "昨晚休息良好"),
                                 ("不太好", "昨晚休息欠佳"), ("不好", "昨晚休息欠佳")):
            with self.subTest(answer=answer):
                flow = HealthGreetingFlow()
                flow.begin()
                flow.respond("今天有点累")
                self.assertFalse(flow.needs_semantic(answer))
                reply = flow.respond(answer)
                self.assertEqual(flow.health_state, "感到疲惫")
                self.assertEqual(flow.health_detail, expected)
                self.assertNotIn("今天状态还不错", reply.text)
                self.assertNotIn("不客气", reply.text)
                self.assertFalse(flow.awaiting_health)

    def test_same_short_answer_to_general_question_has_different_meaning(self):
        flow = HealthGreetingFlow()
        flow.begin()
        flow.respond("还行")
        self.assertEqual(flow.health_state, "状态良好")
        self.assertIsNone(flow.health_detail)

    def test_free_form_followup_passes_question_to_conversation(self):
        self.flow.respond("心情不太好")
        memory = self.flow.memory_context()
        self.assertIsNone(self.flow.respond("跟邻居拌了几句嘴"))
        context = self.flow.handoff_context()
        self.assertIn("遇到什么事", context)
        self.assertIn("第二轮", context)
        self.assertNotIn("当前提出了新的请求", context)
        self.assertEqual(self.flow.memory_context(), memory)
        self.assertIn("遇到什么事", self.flow.respond("继续刚才的问题").text)

    def test_semantic_same_state_explanation_is_not_reduced_to_ack(self):
        self.flow.respond("心情不太好")
        self.assertIsNone(self.flow.respond("跟邻居拌了几句嘴", {
            "intent": "health", "state": "心情低落", "detail": None,
            "evidence": "跟邻居拌了几句嘴"}))
        self.assertIn("上一句机器人问", self.flow.handoff_context())

    def test_accepting_chat_does_not_append_a_goodbye(self):
        for first, second in (("还行", "想聊天"),
                              ("有点累，昨晚没睡好", "想和你聊聊"),
                              ("心情不好，想家", "好的")):
            with self.subTest(first=first):
                flow = HealthGreetingFlow()
                flow.begin()
                flow.respond(first)
                reply = flow.respond(second)
                self.assertTrue(reply.text.endswith("？"), reply.text)
                self.assertNotIn("有需要随时叫我", reply.text)
                self.assertFalse(flow.awaiting_health)

    def setUp(self):
        self.flow = HealthGreetingFlow()
        self.flow.begin("王阿姨")

    def test_negation_does_not_turn_sleep_into_low_mood(self):
        answer = self.flow.respond("我不是心情不好，只是没睡够")
        self.assertEqual(self.flow.health_state, "休息欠佳")
        self.assertEqual(self.flow.health_detail, "休息不足（时间未说明）")
        self.assertNotIn("昨晚", answer.text)
        self.assertNotIn("心情低落", self.flow.memory_context())
        self.assertNotIn("感到疲惫", self.flow.memory_context())

    def test_double_negation_and_mixed_concern(self):
        for text, state in (("我不是不开心", "状态良好"),
                            ("不累，但心情不好", "心情低落"),
                            ("不是腰疼，是有点累", "感到疲惫"),
                            ("腰不疼，但有些疲惫", "感到疲惫")):
            with self.subTest(text=text):
                self.flow.begin("王阿姨")
                self.flow.respond(text)
                self.assertEqual(self.flow.health_state, state)

    def test_correction_replaces_state_and_detail(self):
        self.flow.respond("腰酸，已经好几天了")
        answer = self.flow.respond("我刚才说错了，不是腰疼，是心情不好")
        self.assertEqual(self.flow.health_state, "心情低落")
        self.assertIsNone(self.flow.health_detail)
        self.assertNotIn("腰部不适", self.flow.memory_context())
        self.assertIn("心情", answer.text)
        self.assertFalse(self.flow.awaiting_health)

    def test_recall_does_not_consume_followup(self):
        self.flow.respond("有点累")
        answer = self.flow.respond("记得我刚才说了什么吗？")
        self.assertIn("有些累", answer.text)
        self.assertTrue(self.flow.awaiting_followup)
        self.flow.respond("休息得不太好")
        self.assertEqual(self.flow.health_detail, "昨晚休息欠佳")

    def test_topic_change_suspends_and_preserves_memory(self):
        for request in ("今天该吃药了吗", "帮我报名社区活动", "今天天气怎么样", "跳个舞蹈", "给我播放音乐"):
            with self.subTest(request=request):
                flow = HealthGreetingFlow()
                flow.begin()
                flow.respond("有点累")
                old_memory = flow.memory_context()
                self.assertFalse(flow.needs_semantic(request))
                self.assertIsNone(flow.respond(request))
                self.assertFalse(flow.awaiting_health)
                self.assertEqual(flow.memory_context(), old_memory)
                self.assertIn("已暂停", flow.handoff_context())

    def test_resume_followup_and_new_concern(self):
        self.flow.respond("有点累")
        self.flow.respond("该吃药了吗")
        answer = self.flow.respond("继续刚才的问题")
        self.assertIn("昨晚", answer.text)
        self.assertTrue(self.flow.awaiting_followup)
        self.flow.respond("休息得很好")
        self.assertEqual(self.flow.health_detail, "昨晚休息良好")
        self.flow.respond("现在腰有点酸")
        self.assertEqual(self.flow.health_state, "腰部不适")
        self.assertTrue(self.flow.awaiting_followup)

    def test_empty_and_refusal(self):
        self.assertIsNone(self.flow.respond("  "))
        self.assertEqual(self.flow.clarifications, 0)
        self.assertTrue(self.flow.awaiting_health)
        self.assertIn("不想说也可以", self.flow.respond("不想说").text)
        self.assertFalse(self.flow.awaiting_health)
        self.assertEqual(self.flow.memory_context(), "")

    def test_no_sleep_fact_from_unrelated_followup(self):
        self.flow.respond("有点累")
        self.flow.respond("今天人很多")
        self.assertIsNone(self.flow.health_detail)
        self.assertNotIn("昨晚休息欠佳", self.flow.memory_context())

    def test_bounded_unknown_and_semantic_fallback(self):
        self.assertTrue(self.flow.needs_semantic("整个人提不起劲"))
        answer = self.flow.respond("整个人提不起劲", {
            "intent": "health", "state": "感到疲惫", "detail": None,
            "evidence": "提不起劲",
        })
        self.assertIn("昨晚", answer.text)
        self.assertEqual(self.flow.health_state, "感到疲惫")
        self.assertIn("昨晚休息得怎么样", self.flow.semantic_context())

    def test_semantic_handoff_does_not_create_health_record(self):
        self.assertIsNone(self.flow.respond("帮我查一下车什么时候到", {
            "intent": "other", "state": None, "detail": None,
            "evidence": "车什么时候到",
        }))
        self.assertEqual(self.flow.memory_context(), "")
        self.assertFalse(self.flow.awaiting_health)

    def test_reconnect_preserves_memory_but_other_person_clears_it(self):
        self.flow.respond("有点累")
        self.flow.respond("昨晚没睡好")
        self.flow.begin("王阿姨")
        self.assertIn("昨晚休息欠佳", self.flow.memory_context())
        self.flow.begin("李叔叔")
        self.assertEqual(self.flow.memory_context(), "")

    def test_multiple_affirmed_concerns_are_not_lost(self):
        self.flow.respond("腰有点酸，还有点累")
        memory = self.flow.memory_context()
        self.assertIn("腰部不适", memory)
        self.assertIn("感到疲惫", memory)

    def test_negated_preference_not_remembered(self):
        self.flow.respond("还行")
        self.flow.respond("不想散步，想听音乐")
        self.assertEqual(self.flow.health_detail, "想听音乐")

    def test_negated_duration_not_remembered(self):
        self.flow.respond("腰有点酸")
        self.flow.respond("不是好几天，就是今天才开始")
        self.assertEqual(self.flow.health_detail, "腰部不适今天出现")

    def test_semantic_gate_is_side_effect_free_and_fast_paths_stay_local(self):
        before = self.flow.__dict__.copy()
        for text in ("今天有点累", "不想说", "该吃药了吗", "我刚才说什么", ""):
            self.assertFalse(self.flow.needs_semantic(text))
        self.assertEqual(before, self.flow.__dict__)

    def test_contextual_keywords_require_semantics_and_unknown_records_nothing(self):
        for text in ("我儿子今天有点累", "昨天累今天很好", "不是很开心",
                     "如果我有点累怎么办", "他说他有点累", "我说的是‘有点累’这个词"):
            with self.subTest(text=text):
                flow = HealthGreetingFlow()
                flow.begin()
                self.assertTrue(flow.needs_semantic(text))
                reply = flow.respond(text, {"intent": "unknown", "state": None, "detail": None, "evidence": ""})
                self.assertIn("身体", reply.text)
                self.assertEqual(flow.memory_context(), "")

    def test_contextual_followup_never_replaces_existing_memory(self):
        self.flow.respond("有点累")
        before = self.flow.memory_context()
        self.assertTrue(self.flow.needs_semantic("我儿子昨晚没睡好"))
        self.flow.respond("我儿子昨晚没睡好")
        self.assertEqual(before, self.flow.memory_context())

    def test_answer_to_own_rest_choice_is_natural_and_keeps_sleep_detail(self):
        answer = self.flow.respond("今天有点累，昨晚没睡好")
        self.assertIn("休息一会", answer.text)
        self.assertFalse(self.flow.needs_semantic("想先休息"))
        closing = self.flow.respond("想先休息")
        self.assertIn("安心歇一会", closing.text)
        self.assertNotIn("没听清", closing.text)
        self.assertEqual(self.flow.health_detail, "昨晚休息欠佳")
        self.assertFalse(self.flow.awaiting_health)

    def test_expression_stop_and_open_arms_are_handoffs(self):
        for command in ("请显示开心表情", "请张开双臂", "停止动作", "停下来", "请挥挥手"):
            with self.subTest(command=command):
                flow = HealthGreetingFlow()
                flow.begin()
                self.assertFalse(flow.needs_semantic(command))
                self.assertIsNone(flow.respond(command))
                self.assertEqual(flow.memory_context(), "")

    def test_same_state_sleep_correction_updates_without_restarting(self):
        self.flow.respond("今天有点累，昨晚没睡好")
        answer = self.flow.respond("我刚才说错了，其实昨晚睡得很好")
        self.assertIn("更正", answer.text)
        self.assertEqual(self.flow.health_state, "感到疲惫")
        self.assertEqual(self.flow.health_detail, "昨晚休息良好")
        self.assertFalse(self.flow.awaiting_health)
        answer = self.flow.respond("更正一下，昨晚其实睡得不太好")
        self.assertIn("更正", answer.text)
        self.assertEqual(self.flow.health_detail, "昨晚休息欠佳")
        self.assertFalse(self.flow.awaiting_health)

    def test_unknown_interpretation_cannot_silently_become_keyword_fact(self):
        self.flow.respond("有点累", {"intent": "unknown", "state": None, "detail": None, "evidence": ""})
        self.assertIsNone(self.flow.health_state)

    def test_negated_refusal_does_not_end_interview(self):
        self.assertTrue(self.flow.needs_semantic("我不是不想说"))
        reply = self.flow.respond("我不是不想说")
        self.assertNotIn("不想说也可以", reply.text)
        self.assertTrue(self.flow.awaiting_health)

    def test_secondary_concern_can_be_denied_without_stale_memory(self):
        self.flow.respond("腰有点酸，还有点累")
        self.flow.respond("腰还有点酸，不过不累了")
        self.assertEqual(self.flow.health_state, "腰部不适")
        self.assertNotIn("感到疲惫", self.flow.memory_context())

    def test_added_concern_does_not_erase_previous_unretracted_concern(self):
        self.flow.respond("腰有点酸")
        self.flow.respond("还有点累")
        self.assertIn("腰部不适", self.flow.memory_context())
        self.assertIn("感到疲惫", self.flow.memory_context())


if __name__ == "__main__":
    unittest.main()
