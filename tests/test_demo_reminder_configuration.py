import unittest
from datetime import datetime
from x2_agent.life_assistance import load_context, LOCAL_TIME
from x2_agent.health_reminders import expand_reminder_reply, reminder_reply_error


class DemoReminderConfigurationTests(unittest.TestCase):
    def test_all_required_categories_and_demo_label(self):
        ctx = load_context(now=datetime(2026, 10, 24, 7, 45, tzinfo=LOCAL_TIME))
        self.assertEqual(ctx["status"], "ready")
        self.assertTrue(ctx["demo"])
        self.assertTrue({"water", "medication", "appointment", "other"}.issubset(
            {row["kind"] for row in ctx["today_reminders"]}))
        self.assertEqual(ctx["next_reminder"]["id"], "demo-medication")
        text = expand_reminder_reply("[[REMINDER_MEDICATION]]", ctx)
        self.assertIn("预设时间", text)
        self.assertNotIn("（演示）", text)
        self.assertIn("还没到这个时间", text)
        self.assertIn("按医嘱", text)

    def test_appointment_repeats_daily_and_is_not_a_real_booking(self):
        ctx = load_context(now=datetime(2026, 10, 24, 9, 0, tzinfo=LOCAL_TIME))
        self.assertEqual(ctx["next_reminder"]["id"], "demo-followup")
        self.assertEqual(ctx["next_reminder"]["title"], "复诊提醒（演示）")
        self.assertNotIn("资料准备", expand_reminder_reply("[[REMINDER_NEXT]]", ctx))
        self.assertIn("未实际预约", ctx["next_reminder"]["detail"])
        later = load_context(now=datetime(2026, 10, 25, 9, 0, tzinfo=LOCAL_TIME))
        self.assertIn("demo-followup", [r["id"] for r in later["today_reminders"]])
        self.assertEqual(later["next_reminder"]["id"], "demo-followup")
        self.assertEqual(later["next_reminder"]["time_label"], "今天9点30分")

    def test_passed_medication_is_not_called_missed(self):
        ctx = load_context(now=datetime(2026, 10, 23, 14, 0, tzinfo=LOCAL_TIME))
        text = expand_reminder_reply("[[REMINDER_MEDICATION]]", ctx)
        self.assertIn("已经吃过药了吗", text)
        self.assertNotIn("漏服", text)

    def test_today_reply_uses_natural_intro_and_remaining_question_is_distinct(self):
        ctx = load_context(now=datetime(2026, 10, 24, 11, 52, tzinfo=LOCAL_TIME))
        spoken = expand_reminder_reply("[[REMINDER_TODAY]]", ctx)
        self.assertTrue(spoken.startswith("您今天有这些提醒："))
        self.assertNotIn("按这份安排", spoken)
        self.assertNotIn("：今天", spoken)
        self.assertEqual(reminder_reply_error({"intent": "reminder", "reply": "[[REMINDER_TODAY]]"},
                                              "今天还有什么要做的吗？"), "reminder_remaining_misclassified")
        self.assertIsNone(reminder_reply_error({"intent": "reminder", "reply": "[[REMINDER_REMAINING]]"},
                                                "今天还有什么要做的吗？"))


if __name__ == "__main__":
    unittest.main()
