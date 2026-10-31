import copy
import json
import unittest
from datetime import datetime
from types import SimpleNamespace

from x2_agent.life_assistance import build_context, LOCAL_TIME
from x2_agent.model_dialogue import ModelDialogue, generate_dialogue, validate_reply
from x2_agent.presentation import capabilities


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.memory = ModelDialogue()
        self.data = {"version": 1, "demo": True, "medicines": [], "reminders": [
            {"id": "med", "date": "daily", "time": "08:00", "kind": "medication", "title": "用药安排核对（演示）"},
            {"id": "water", "date": "daily", "time": "10:00", "kind": "water", "title": "喝水提醒"}]}
        self.service = build_context(self.data, datetime(2026, 10, 23, 15, 33, tzinfo=LOCAL_TIME))

    async def turn(self, user, token, commit=True):
        async def stream(prompt, messages, *args, **kwargs):
            self.payload = json.loads(messages[0]["content"])
            yield "text", json.dumps(dict(intent="reminder", action="continue", reply=token, emotion=None, gesture=None))
        result = await generate_dialogue(SimpleNamespace(stream=stream), user,
            {**self.memory.context(), "capabilities": capabilities(), "life_assistance": self.service}, "m", "k")
        if commit:
            self.memory.commit(user, result)
        return result

    async def test_review_short_answer_has_explicit_question_and_clears_it(self):
        await self.turn("今天还有什么要做", "[[REMINDER_REMAINING]]")
        self.assertEqual(self.memory.pending_question, {"kind": "review_today"})
        result = await self.turn("需要", "[[REMINDER_TODAY]]")
        self.assertEqual(self.payload["pending_question"]["kind"], "review_today")
        self.assertIn("您今天有这些提醒：8点整", result["reply"])
        self.assertIn("10点整", result["reply"])
        self.assertIsNone(self.memory.pending_question)

    async def test_taken_is_session_self_report_and_not_reasked(self):
        await self.turn("该吃药了吗", "[[REMINDER_MEDICATION]]")
        self.assertEqual(self.memory.pending_question["occurrence_id"], "med@2026-10-23")
        await self.turn("吃过了", "[[REMINDER_TAKEN]]")
        self.assertEqual(self.memory.reminder_self_reports, {"med@2026-10-23": "taken"})
        result = await self.turn("那还要吃吗", "[[REMINDER_MEDICATION]]")
        self.assertIn("不要", result["reply"])
        self.assertNotIn("吃过药了吗", result["reply"])
        self.assertEqual(self.service["today_reminders"][0]["completion"], "unknown")

    async def test_no_commit_no_state_change_and_transaction_can_rollback(self):
        await self.turn("该吃药了吗", "[[REMINDER_MEDICATION]]")
        snapshot = copy.deepcopy(self.memory.__dict__)
        result = await self.turn("吃过了", "[[REMINDER_TAKEN]]", commit=False)
        self.assertEqual(self.memory.__dict__, snapshot)
        self.memory.commit("吃过了", result)
        self.memory.__dict__.update(snapshot)
        self.assertEqual(self.memory.reminder_self_reports, {})

    async def test_completion_requires_current_medication_question(self):
        result = await self.turn("吃过饭了", "[[REMINDER_TAKEN]]")
        self.assertNotIn("既然", result["reply"])
        self.assertFalse(self.memory.reminder_self_reports)

    async def test_yesterday_answer_cannot_complete_today(self):
        await self.turn("该吃药了吗", "[[REMINDER_MEDICATION]]")
        self.service = build_context(self.data, datetime(2026, 10, 24, 15, 33, tzinfo=LOCAL_TIME))
        await self.turn("吃过了", "[[REMINDER_TAKEN]]")
        self.assertFalse(self.memory.reminder_self_reports)

    async def test_not_taken_and_uncertain_do_not_instruct_extra_dose(self):
        for token, status in (("[[REMINDER_NOT_TAKEN]]", "not_taken"), ("[[REMINDER_UNSURE]]", "unsure")):
            self.memory = ModelDialogue()
            await self.turn("该吃药了吗", "[[REMINDER_MEDICATION]]")
            await self.turn("回答", token)
            self.assertEqual(self.memory.reminder_self_reports["med@2026-10-23"], status)

    def test_closed_interview_cannot_keep_closing_new_pain(self):
        result = dict(intent="health", action="close", reply="有需要叫我。", emotion=None, gesture=None)
        diagnostic = {}
        self.assertIsNone(validate_reply(json.dumps(result), self.memory.context(), diagnostics=diagnostic))
        self.assertEqual(diagnostic["reason"], "health_interview_already_closed")

    def test_runtime_preserves_clarification_but_does_not_reopen_interview(self):
        result = dict(intent="health", action="followup", reply="近期有没有摔倒或扭伤？", emotion=None, gesture=None)
        normalized = validate_reply(json.dumps(result), self.memory.context(), degrade_presentation=True)
        self.assertEqual(normalized["intent"], "other")
        self.assertEqual(normalized["action"], "continue")
        self.assertEqual(normalized["reply"], result["reply"])
        self.memory.commit("腰疼", normalized)
        self.assertFalse(self.memory.interview_active)
        self.assertEqual(self.memory.health_rounds, 0)
