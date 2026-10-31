"""Synthetic boundary tests, not clinical certification."""
import json
import unittest
from types import SimpleNamespace
from x2_agent.medicine_consultation import dosage_context, medication_reply_error, expand_medicine_reply
from x2_agent.model_dialogue import generate_dialogue, ModelDialogue
from x2_agent.presentation import capabilities


class GuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.row = dict(name="测试药", strength="5mg", form="普通片", manufacturer="测试药厂",
                        usage="测试资料：一般5mg每日一次；特殊人群2.5mg每日一次，个人用量由医生确认。")
        self.service = {"medicines": [self.row]}
        self.full = "测试药，5毫克，普通片，测试药厂"

    def test_missing_slot_question_required(self):
        ctx = dosage_context(self.service, "测试药")
        self.assertEqual(medication_reply_error("需由医生确认。", ctx), "medicine_clarification_missing")
        self.assertIsNone(medication_reply_error("药盒上的规格是什么？", ctx))

    def test_no_false_lookup_promise(self):
        self.assertEqual(medication_reply_error("完整说明书暂未收录，请报药名，我帮您进一步查询。", self.service),
                         "medicine_lookup_unavailable")
        self.assertIsNone(medication_reply_error("说明书尚未收录，请提供完整说明书或请药师核对。", self.service))

    def test_token_expands_complete_usage_and_precaution(self):
        self.row["precautions"] = "测试注意事项；第二条测试事项。"
        ctx = dosage_context(self.service, self.full)
        result = expand_medicine_reply("资料记载：[[MEDICINE_USAGE]]", ctx)
        self.assertFalse(result.startswith("资料记载"))
        self.assertIn("特殊人群2.5毫克每日一次", result)
        self.assertIn("测试注意事项", result)
        self.assertNotIn("。。", expand_medicine_reply("[[MEDICINE_USAGE]]。", ctx))
        self.assertIsNone(medication_reply_error(result, ctx))
        self.assertEqual(medication_reply_error(self.row["usage"], ctx), "medicine_precaution_missing")
        locked = dosage_context(self.service, "不知道药名")
        self.assertIsNone(expand_medicine_reply("[[MEDICINE_USAGE]]", locked))

    def test_spoken_source_label_is_removed_without_changing_guidance(self):
        ctx = dosage_context({"medicines": [], "medicine_education": {
            "categories": [{"name": "降压药", "aliases": [], "usage": "按处方规律服用。",
                            "precautions": "不要自行停药。", "boundary": "不能按类别定量。",
                            "source": "test"}], "entries": []}}, "降压药怎么吃")
        for prefix in ("这份资料记载：", "按这份资料，", "按这份说明书："):
            reply = expand_medicine_reply(prefix + "按处方规律服用。不要自行停药。", ctx)
            self.assertTrue(reply.startswith("按处方规律服用。不要自行停药。"))
            self.assertIn("确认服用时间和每次用量", reply)
            self.assertNotIn("这份资料", reply)

    async def test_token_expansion_enters_actual_history_without_markers(self):
        async def stream(*args, **kwargs):
            yield "text", json.dumps(dict(intent="other", action="continue", reply="资料记载：[[MEDICINE_USAGE]]", emotion=None, gesture=None))
        memory = ModelDialogue()
        result = await generate_dialogue(SimpleNamespace(stream=stream), self.full,
            {**memory.context(), "life_assistance": self.service, "capabilities": capabilities()}, "m", "k")
        memory.commit(self.full, result)
        self.assertNotIn("[[", memory.verbatim_turns[-1]["assistant"])
        self.assertIn("特殊人群", memory.verbatim_turns[-1]["assistant"])

    def test_condition_loss_and_extra_dose_rejected(self):
        ctx = dosage_context(self.service, self.full)
        self.assertEqual(medication_reply_error("通常5mg每日一次。", ctx), "medicine_usage_conditions_missing")
        self.assertIsNone(medication_reply_error(self.row["usage"].replace("mg", "毫克"), ctx))
        self.assertEqual(medication_reply_error(self.row["usage"] + "再吃一片。", ctx), "medicine_extra_dose")

    def test_unconfirmed_numbers_chinese_and_arabic_blocked(self):
        ctx = dosage_context(self.service, "这个药怎么吃")
        for reply in ("吃5mg。", "吃五毫克。", "吃半片。"):
            self.assertEqual(medication_reply_error(reply, ctx), "medicine_dose_not_authorized")

    def test_identity_only_multiturn_and_topic_reset(self):
        history = [{"user": "测试药", "assistant": "污染：测试药厂5mg普通片"}]
        ctx = dosage_context(self.service, "5mg", history)
        self.assertEqual(ctx["medication_contract"]["clarify_field"], "form")
        history += [{"user": "5mg"}, {"user": "普通片"}]
        ctx = dosage_context(self.service, "测试药厂", history)
        self.assertEqual(ctx["medicines"][0]["usage"], self.row["usage"])
        history += [{"user": "不对，是另外一种药"}]
        self.assertEqual(dosage_context(self.service, "测试药厂", history)["medicines"][0]["usage"], "")

    def test_negated_or_uncertain_identity_does_not_release(self):
        for prefix in ("不是", "不确定是不是", "假设"):
            self.assertEqual(dosage_context(self.service, prefix + self.full)["medicines"][0]["usage"], "")

    async def test_failed_repair_returns_no_dose_fallback(self):
        calls = []
        async def stream(prompt, *args, **kwargs):
            calls.append(prompt)
            yield "text", json.dumps(dict(intent="other", action="continue", reply="通常5mg每日一次。",
                                           emotion=None, gesture=None))
        result = await generate_dialogue(SimpleNamespace(stream=stream), self.full,
            {**ModelDialogue().context(), "life_assistance": self.service, "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("5", result["reply"])
        self.assertIsNone(result["gesture"])
        self.assertIn("medicine_usage_conditions_missing", calls[1])

    async def test_valid_repair_delivered(self):
        calls = []
        async def stream(prompt, *args, **kwargs):
            calls.append(prompt)
            reply = "通常5mg每日一次。" if len(calls) == 1 else self.row["usage"]
            yield "text", json.dumps(dict(intent="other", action="continue", reply=reply, emotion=None, gesture=None))
        result = await generate_dialogue(SimpleNamespace(stream=stream), self.full,
            {**ModelDialogue().context(), "life_assistance": self.service, "capabilities": capabilities()}, "m", "k")
        self.assertEqual(result["reply"], self.row["usage"])
