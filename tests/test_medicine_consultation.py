"""Synthetic identity/contract tests, not clinical correctness tests."""
import copy
import unittest
from x2_agent.medicine_consultation import prepare_medicines, MEDICINE_PROMPT, dosage_context, medication_reply_error, medication_safe_fallback, load_education, expand_medicine_reply
from x2_agent.life_assistance import build_context


class MedicineTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(name="测试药品非真实药", strength="测试规格甲", form="测试剂型",
                        manufacturer="测试企业", source="合成测试来源", reviewed=True)

    def test_missing_sections_not_filled(self):
        row = prepare_medicines([self.row])[0]
        self.assertEqual(row["usage"], "")
        self.assertIn("usage", row["missing_sections"])
        self.assertIn("missed_dose", row["missing_sections"])

    def test_dose_hidden_until_current_identity_confirmed(self):
        service = {"medicines": [{**self.row, "usage": "DOSE_TEST", "missed_dose": "MISSED_TEST"}]}
        for text in ("降压药怎么吃", "测试药品非真实药", "我说错了，是别的药"):
            row = dosage_context(service, text)["medicines"][0]
            self.assertEqual(row["usage"], "")
            self.assertEqual(row["missed_dose"], "")
        text = "测试药品非真实药 测试规格甲 测试剂型 测试企业"
        self.assertEqual(dosage_context(service, text)["medicines"][0]["usage"], "DOSE_TEST")
        self.assertEqual(service["medicines"][0]["usage"], "DOSE_TEST")

    def test_generic_blood_pressure_question_gets_practical_answer_without_drug_name_gate(self):
        service = {"medicines": [{**self.row, "usage": "DOSE_TEST"}]}
        ctx = dosage_context(service, "降压药怎么吃？")
        self.assertEqual(ctx["medication_contract"]["generic_category"], "降压药")
        self.assertTrue(ctx["medication_contract"]["confirm_schedule"])
        self.assertEqual(ctx["medicines"][0]["usage"], "")
        reply = medication_safe_fallback(ctx)["reply"]
        self.assertIn("按处方", reply)
        self.assertIn("服用时间和每次用量", reply)
        self.assertNotIn("完整药名", reply)
        self.assertNotRegex(reply, r"[？?]")
        self.assertEqual(medication_reply_error("请按处方服用，不要自行停药。", ctx),
                         "medicine_generic_schedule_notice_missing")
        self.assertEqual(medication_reply_error("处方上写的服用时间和每次用量是什么？", ctx),
                         "medicine_generic_unwanted_question")
        self.assertIsNone(medication_reply_error(reply, ctx))
        self.assertEqual(medication_reply_error("请提供药盒上的完整药名。", ctx), "medicine_generic_name_barrier")
        self.assertEqual(medication_reply_error("比如测试药品非真实药。", ctx), "medicine_generic_specific_name")
        self.assertEqual(medication_reply_error("降压药每天吃两片。", ctx), "medicine_dose_not_authorized")

    def test_safe_generic_answer_gets_schedule_boundary_without_model_retry(self):
        ctx = dosage_context({"medicines": []}, "降压药怎么吃？")
        reply = expand_medicine_reply("降压药要按处方规律服用，不要自行停药。", ctx)
        self.assertIn("确认服用时间和每次用量", reply)
        self.assertIsNone(medication_reply_error(reply, ctx))

    def test_common_category_reference_covers_recent_user_questions(self):
        education = load_education()
        self.assertEqual(education.get("status"), None)
        for question, category in (("血压药怎么吃", "降压药"), ("感冒药怎么吃", "感冒药"),
                                   ("止泻药怎么吃", "止泻药"), ("止痛药怎么吃", "止痛药"),
                                   ("胃药怎么吃", "胃药"), ("便秘药怎么吃", "通便药"),
                                   ("过敏药怎么吃", "抗过敏药"), ("抗生素怎么吃", "抗生素")):
            ctx = dosage_context({"medicines": [], "medicine_education": education}, question)
            self.assertEqual(ctx["medication_contract"]["generic_category"], category)
            answer = medication_safe_fallback(ctx)["reply"]
            self.assertRegex(answer, "处方|医嘱|包装说明")
            self.assertNotIn("完整药名", answer)
            self.assertIsNone(medication_reply_error(answer, ctx))
            self.assertEqual(medication_reply_error("目前暂未查询到这类药的资料。", ctx),
                             "medicine_generic_ignores_reference")

    def test_unheard_category_asks_for_purpose_not_exact_product(self):
        ctx = dosage_context({"medicines": [], "medicine_education": load_education()}, "干药怎么吃？")
        self.assertTrue(ctx["medication_contract"]["unknown_category"])
        reply = medication_safe_fallback(ctx)["reply"]
        self.assertIn("治什么不舒服", reply)
        self.assertNotIn("完整药名", reply)
        reminder = dosage_context({"medicines": [], "medicine_education": load_education()}, "该吃药了吗？")
        self.assertNotIn("medication_contract", reminder)

    def test_preserves_conditions_and_source_verbatim(self):
        self.row.update(usage="测试条件：仅用于接口测试，非医嘱。", population="测试范围", reviewed_on="2026-10-23")
        row = prepare_medicines([self.row])[0]
        for key in ("usage", "population", "source", "reviewed_on"):
            self.assertEqual(row[key], self.row[key])

    def test_distinct_strengths_kept_duplicate_identity_rejected(self):
        other = {**self.row, "strength": "测试规格乙"}
        self.assertEqual(len(prepare_medicines([self.row, other])), 2)
        with self.assertRaises(ValueError):
            prepare_medicines([self.row, copy.deepcopy(self.row)])

    def test_aliases_are_not_generated(self):
        self.assertEqual(prepare_medicines([self.row])[0]["aliases"], [])
        self.row["aliases"] = ["测试别名", "测试别名"]
        self.assertEqual(prepare_medicines([self.row])[0]["aliases"], ["测试别名"])
        self.row["aliases"] = "bad list"
        with self.assertRaises(ValueError):
            prepare_medicines([self.row])

    def test_unreviewed_does_not_count_as_available(self):
        self.row["reviewed"] = False
        ctx = build_context(dict(version=1, demo=True, medicines=[self.row], reminders=[]))
        self.assertEqual(ctx["medicine_catalog_state"], "empty")
        self.assertEqual(ctx["medicines"], [])

    def test_clarification_correction_and_no_conversion_constraints(self):
        for phrase in ("已经提供的名称/规格不要重问", "以纠正后的信息重新核对", "不能自行换算片数",
                       "不把旧药的用量", "不要从模型记忆补剂量"):
            self.assertIn(phrase, MEDICINE_PROMPT)
