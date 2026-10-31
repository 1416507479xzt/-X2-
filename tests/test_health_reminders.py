import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from x2_agent.life_assistance import build_context, LOCAL_TIME
from x2_agent.health_reminders import expand_reminder_reply, reminder_reply_error
from x2_agent.model_dialogue import generate_dialogue, ModelDialogue
from x2_agent.presentation import capabilities


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def test_remaining_question_normalizes_today_token_without_second_call(self):
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            yield "text", json.dumps(dict(intent="reminder", action="continue",
                                           reply="[[REMINDER_TODAY]]", emotion=None, gesture=None))
        result = await generate_dialogue(SimpleNamespace(stream=stream), "今天还有什么提醒事项？",
            {**ModelDialogue().context(), "capabilities": capabilities(), "life_assistance": self.context(15, 20)}, "m", "k")
        self.assertEqual(len(calls), 1)
        self.assertIn("今天接下来没有其他", result["reply"])

    def setUp(self):
        self.data = {"version": 1, "demo": True, "medicines": [], "reminders": [
            {"id": "water", "date": "daily", "time": "10:00", "kind": "water", "title": "喝水提醒"},
            {"id": "visit", "date": "2026-10-24", "time": "09:30", "kind": "appointment", "title": "复诊安排"}]}

    def context(self, hour, minute=0, second=0):
        return build_context(self.data, datetime(2026, 10, 23, hour, minute, second, tzinfo=LOCAL_TIME))

    def test_due_minute_is_not_tomorrow(self):
        for second in (0, 59):
            ctx = self.context(10, 0, second)
            self.assertEqual(ctx["next_reminder"]["status"], "due_now")
            self.assertEqual(ctx["next_reminder"]["time_label"], "今天10点整")
            self.assertEqual(ctx["reminder_summary"]["due_now_count"], 1)
        ctx = self.context(10, 1)
        self.assertEqual(ctx["today_reminders"][0]["status"], "passed_unknown")
        self.assertEqual(ctx["next_reminder"]["time_label"], "明天9点30分")

    def test_soon_window_and_no_false_completion(self):
        self.assertFalse(self.context(9, 29)["next_reminder"]["is_soon"])
        ctx = self.context(9, 30)
        self.assertTrue(ctx["next_reminder"]["is_soon"])
        self.assertEqual(ctx["next_reminder"]["minutes_until"], 30)
        self.assertEqual(ctx["next_reminder"]["completion"], "unknown")
        self.assertEqual(ctx["next_reminder"]["occurrence_id"], "water@2026-10-23")

    def test_timezone_and_midnight(self):
        ctx = build_context(self.data, datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(ctx["now"], "2026-10-23T00:00:00+08:00")
        self.assertEqual(ctx["next_reminder"]["time_label"], "今天10点整")

    def test_no_today_remaining_does_not_mean_no_schedule(self):
        ctx = self.context(23, 59)
        self.assertEqual(ctx["remaining_today"], [])
        self.assertEqual(ctx["reminder_summary"]["today_count"], 1)
        text = expand_reminder_reply("[[REMINDER_TODAY]]", ctx)
        self.assertIn("时间已经过了", text)
        self.assertIn("还需要确认", text)
        self.assertIn("下一项预设提醒是明天", text)
        self.assertNotIn("演示", text)

    async def test_water_self_report_answers_short_turn_without_repeating_schedule(self):
        memory = ModelDialogue()
        ctx = self.context(15, 20)
        answers = iter(("[[REMINDER_WATER]]", "[[REMINDER_WATER_DONE]]"))
        async def stream(*args, **kwargs):
            yield "text", json.dumps(dict(intent="reminder", action="continue",
                                           reply=next(answers), emotion=None, gesture=None))
        for user in ("该喝水了吗？", "好的，我已经喝过了"):
            result = await generate_dialogue(SimpleNamespace(stream=stream), user,
                {**memory.context(), "capabilities": capabilities(), "life_assistance": ctx}, "m", "k")
            memory.commit(user, result)
        self.assertIn("您说这次已经喝过水了", result["reply"])
        self.assertNotIn("您今天有这些提醒", result["reply"])
        self.assertEqual(memory.reminder_self_reports["water@2026-10-23"], "done")

    def test_empty_and_unavailable_distinct(self):
        self.data["reminders"] = []
        self.assertIn("没有后续安排", expand_reminder_reply("[[REMINDER_NEXT]]", self.context(9)))
        self.assertIn("读取不到", expand_reminder_reply("[[REMINDER_NEXT]]", {"status": "unavailable"}))

    def test_validation_and_medication_boundary(self):
        for value in (True, -1, 1441, "30"):
            self.data["remind_before_minutes"] = value
            with self.assertRaises(ValueError):
                self.context(9)
        self.data["remind_before_minutes"] = 30
        self.data["reminders"][0]["kind"] = "medication"
        self.data["reminders"][0]["title"] = "核对服药安排"
        self.assertIn("服药请核对医嘱", expand_reminder_reply("[[REMINDER_NEXT]]", self.context(9, 50)))

    async def test_next_fragment_used_in_actual_reply_and_memory(self):
        async def stream(*args, **kwargs):
            yield "text", json.dumps(dict(intent="reminder", action="continue", reply="[[REMINDER_NEXT]]",
                                           emotion="neutral", gesture=None))
        memory = ModelDialogue()
        result = await generate_dialogue(SimpleNamespace(stream=stream), "下一项几点",
            {**memory.context(), "capabilities": capabilities(), "life_assistance": self.context(9, 45)}, "m", "k")
        self.assertIn("今天10点整", result["reply"])
        self.assertIn("还有15分钟", result["reply"])
        memory.commit("下一项几点", result)
        self.assertNotIn("[[", memory.verbatim_turns[-1]["assistant"])

    def test_false_write_and_unstructured_schedule_rejected(self):
        self.assertEqual(reminder_reply_error(dict(intent="reminder", reply="下一项是十五点。")), "reminder_unstructured_reply")
        self.assertEqual(reminder_reply_error(dict(intent="other", reply="好的，我会把喝水提醒调整到十一点。")), "reminder_false_write_claim")
        self.assertIsNone(reminder_reply_error(dict(intent="reminder", reply="[[REMINDER_CHANGE_UNSUPPORTED]]")))

    def test_specific_appointment_and_water_not_replaced_by_next(self):
        ctx = build_context(self.data, datetime(2026, 10, 24, 11, 0, tzinfo=LOCAL_TIME))
        visit = expand_reminder_reply("[[REMINDER_APPOINTMENT]]", ctx)
        self.assertIn("复诊", visit)
        self.assertIn("今天9点30分", visit)
        self.assertNotIn("社区活动", visit)
        self.assertIn("喝水", expand_reminder_reply("[[REMINDER_WATER]]", ctx))
        self.assertEqual(reminder_reply_error(dict(intent="reminder", reply="[[REMINDER_NEXT]]"), "我什么时候去复诊？"), "reminder_wrong_topic_appointment")
        self.assertEqual(reminder_reply_error(dict(intent="reminder", reply="[[REMINDER_NEXT]]"), "喝水安排呢？"), "reminder_wrong_topic_water")
        self.assertIsNone(reminder_reply_error(dict(intent="reminder", reply="[[REMINDER_CHANGE_UNSUPPORTED]]"), "把复诊改明天"))

    def test_no_medication_is_not_permission_to_take_or_skip(self):
        text = expand_reminder_reply("[[REMINDER_MEDICATION]]", self.context(9))
        self.assertIn("没有您今天的用药时间", text)
        self.assertIn("不能据此判断", text)
        self.assertNotIn("喝水", text)

    def test_remaining_is_distinct_from_all_and_keeps_demo_metadata(self):
        ctx = self.context(15, 20)
        text = expand_reminder_reply("[[REMINDER_REMAINING]]", ctx)
        self.assertIn("接下来没有", text)
        self.assertNotIn("10点", text)
        self.assertNotIn("明天", text)
        self.assertTrue(ctx["demo"])
        ctx = self.context(9, 45)
        text = expand_reminder_reply("[[REMINDER_REMAINING]]", ctx)
        self.assertIn("还有15分钟", text)
        self.assertNotIn("（", text)
        self.assertNotIn("演示", text)

    async def test_unstructured_reply_repaired_to_grounded_time(self):
        calls = []
        async def stream(prompt, *args, **kwargs):
            calls.append(prompt)
            yield "text", json.dumps(dict(intent="reminder", action="continue",
                reply="下一项是十五点。" if len(calls) == 1 else "[[REMINDER_NEXT]]", emotion=None, gesture=None))
        result = await generate_dialogue(SimpleNamespace(stream=stream), "下一项几点",
            {**ModelDialogue().context(), "capabilities": capabilities(), "life_assistance": self.context(9)}, "m", "k")
        self.assertEqual(len(calls), 2)
        self.assertIn("今天10点整", result["reply"])

    async def test_oversized_expansion_does_not_leak_marker_or_apology(self):
        for row in self.data["reminders"]:
            row["title"] = "测试长标题" * 20
            row["date"] = "daily"
        async def stream(*args, **kwargs):
            yield "text", json.dumps(dict(intent="reminder", action="continue", reply="[[REMINDER_TODAY]]", emotion=None, gesture=None))
        result = await generate_dialogue(SimpleNamespace(stream=stream), "今日安排",
            {**ModelDialogue().context(), "capabilities": capabilities(), "life_assistance": self.context(9)}, "m", "k")
        self.assertNotIn("[[", result["reply"])
        self.assertNotIn("抱歉", result["reply"])
        self.assertIsNone(result["gesture"])
