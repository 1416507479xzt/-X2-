import copy
import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from x2_agent.life_assistance import build_context, load_context, LOCAL_TIME
from x2_agent.model_dialogue import ModelDialogue, generate_dialogue
from x2_agent.presentation import capabilities


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.data = {"version": 1, "demo": True, "medicines": [], "reminders": [
            {"id": "a", "date": "daily", "time": "10:00", "kind": "water", "title": "演示喝水"},
            {"id": "b", "date": "2026-10-23", "time": "09:00", "kind": "appointment", "title": "演示复诊"}]}
        self.now = datetime(2026, 10, 22, 10, 1, tzinfo=LOCAL_TIME)

    def test_passed_is_unknown_not_completed_or_missed(self):
        ctx = build_context(self.data, self.now)
        self.assertEqual(ctx["today_reminders"][0]["status"], "passed_unknown")
        self.assertEqual(ctx["next_reminder"]["id"], "b")
        self.assertEqual(ctx["next_reminder"]["due_at"], "2026-10-23T09:00:00+08:00")

    def test_daily_rolls_to_tomorrow(self):
        self.data["reminders"].pop()
        self.assertEqual(build_context(self.data, self.now)["next_reminder"]["due_at"],
                         "2026-10-23T10:00:00+08:00")

    def test_bad_data_rejected(self):
        for key, value in (("time", "25:00"), ("date", "tomorrow"), ("kind", "unknown")):
            data = copy.deepcopy(self.data)
            data["reminders"][0][key] = value
            with self.assertRaises(ValueError):
                build_context(data, self.now)
        self.data["reminders"].append(self.data["reminders"][0])
        with self.assertRaises(ValueError):
            build_context(self.data, self.now)

    def test_unreviewed_medicine_not_exposed(self):
        self.data["medicines"] = [{"name": "测试名称", "strength": "测试规格", "form": "测试剂型",
                                   "source": "测试来源", "reviewed": False}]
        self.assertEqual(build_context(self.data, self.now)["medicines"], [])
        self.data["medicines"][0]["reviewed"] = True
        self.assertEqual(build_context(self.data, self.now)["medicines"][0]["usage"], "")

    def test_missing_file_fails_closed(self):
        self.assertEqual(load_context("__missing_service_file__.json")["status"], "unavailable")

    async def test_service_keeps_memory_and_ends_interview_without_restart(self):
        memory = ModelDialogue()
        memory.begin()
        memory.remember("脖子酸", "这种情况持续多久了？")
        captured = []
        async def stream(prompt, history, *args, **kwargs):
            captured.append((prompt, history))
            yield "text", json.dumps({"intent": "other", "action": "continue", "reply": "降压药种类不同，服药时间和用量按处方，不要自行停药。", "emotion": "neutral", "gesture": None})
        ctx = {**memory.context(), "capabilities": capabilities(),
               "life_assistance": build_context(self.data, self.now)}
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "降压药怎么吃", ctx, "model", "key")
        memory.commit("降压药怎么吃", answer)
        self.assertFalse(memory.interview_active)
        self.assertEqual(memory.verbatim_turns[0]["user"], "脖子酸")
        self.assertIn("不从模型常识补药量", captured[0][0])
        self.assertIn("today_reminders", str(captured[0][1]))


if __name__ == "__main__":
    unittest.main()
