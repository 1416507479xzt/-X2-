import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from x2_agent.dining_feedback import load_feedback, prepare_transition, render_dashboard, save_feedback
from x2_agent.model_dialogue import ModelDialogue, generate_dialogue
from x2_agent.presentation import capabilities


class DiningFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.memory = ModelDialogue()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "feedback.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    async def turn(self, utterance, intent, token, *, commit=True):
        async def stream(prompt, messages, *args, **kwargs):
            self.prompt = prompt
            self.payload = json.loads(messages[0]["content"])
            yield "text", json.dumps({"intent": intent, "action": "continue", "reply": token,
                                      "emotion": None, "gesture": None}, ensure_ascii=False)

        result = await generate_dialogue(SimpleNamespace(stream=stream), utterance,
            {**self.memory.context(), "capabilities": capabilities()}, "model", "key")
        if commit and result is not None:
            self.memory.commit(utterance, result, dining_records_path=self.path)
        return result

    async def test_prepare_confirmation_writes_once_and_session_clears(self):
        first = await self.turn("食堂青菜太咸，下次少放盐", "dining",
                                "[[DINING_PREPARE|taste|青菜|太咸|少放盐]]")
        self.assertIn("要记入食堂反馈表吗", first["reply"])
        self.assertEqual(load_feedback(self.path), [])
        self.assertEqual(self.payload["pending_dining"], None)
        second = await self.turn("确认提交", "dining", "[[DINING_CONFIRM]]")
        self.assertIn("已经记入", second["reply"])
        self.assertIsNone(self.memory.pending_dining)
        records = load_feedback(self.path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["item"], "青菜")
        self.assertEqual(records[0]["request"], "少放盐")
        self.assertEqual(records[0]["source"], "voice_confirmed")
        save_feedback(records[0], self.path)
        self.assertEqual(len(load_feedback(self.path)), 1)

    async def test_correction_replaces_item_and_cancel_does_not_write(self):
        await self.turn("食堂青菜太咸", "dining", "[[DINING_PREPARE|taste|青菜|太咸|-]]")
        result = await self.turn("不是青菜，是汤太咸", "dining", "[[DINING_PREPARE|taste|汤|太咸|]]")
        self.assertIn("汤太咸", result["reply"])
        self.assertEqual(self.memory.pending_dining["item"], "汤")
        await self.turn("不提交了", "dining", "[[DINING_CANCEL]]")
        self.assertIsNone(self.memory.pending_dining)
        self.assertEqual(load_feedback(self.path), [])

    async def test_homophone_asks_for_clarification_and_cannot_submit(self):
        await self.turn("食堂青菜太咸，下次少放盐", "dining", "[[DINING_PREPARE|taste|青菜|太咸|少放盐]]")
        uncertain = await self.turn("不是青菜太咸，是糖太咸了", "dining",
                                    "[[DINING_PREPARE|taste|糖|太咸|少放盐]]")
        self.assertIn("您说的是‘汤’吗", uncertain["reply"])
        self.assertEqual(self.memory.pending_dining["stage"], "await_item_clarification")
        self.assertEqual(self.memory.pending_dining["request"], "少放盐")
        result = await self.turn("确认提交", "dining", "[[DINING_CONFIRM]]")
        self.assertIn("暂时没有提交", result["reply"])
        self.assertEqual(load_feedback(self.path), [])
        corrected = await self.turn("不是青菜，是汤太咸了", "dining",
                                    "[[DINING_PREPARE|taste|汤|太咸|少放盐]]")
        self.assertIn("汤太咸", corrected["reply"])
        self.assertIn("希望少放盐", corrected["reply"])
        await self.turn("确认提交", "dining", "[[DINING_CONFIRM]]")
        self.assertEqual(load_feedback(self.path)[0]["item"], "汤")

    async def test_complaint_is_not_read_back_as_desired_result(self):
        result = await self.turn("今天的汤有点咸", "dining",
                                 "[[DINING_PREPARE|taste|汤|有点咸|今天的汤有点咸]]")
        self.assertIn("汤有点咸", result["reply"])
        self.assertNotIn("希望今天的汤有点咸", result["reply"])
        self.assertEqual(self.memory.pending_dining["request"], "")

    async def test_observation_keeps_users_milder_degree_and_natural_confirmation(self):
        result = await self.turn("今天食堂的青菜有点咸，下次少放盐", "dining",
                                 "[[DINING_PREPARE|taste|青菜|太咸|少放盐]]")
        self.assertIn("青菜有点咸", result["reply"])
        self.assertNotIn("太咸", result["reply"])
        self.assertEqual(self.memory.pending_dining["observation"], "有点咸")
        await self.turn("要记录", "dining", "[[DINING_CONFIRM]]")
        self.assertEqual(load_feedback(self.path)[0]["observation"], "有点咸")

    async def test_generic_dish_does_not_inherit_model_invented_specific_dish(self):
        result = await self.turn("今天的菜有点咸，下次少放点盐", "dining",
                                 "[[DINING_PREPARE|taste|汤|有点咸|少放盐]]")
        self.assertIn("今天的菜有点咸", result["reply"])
        self.assertIn("少放点盐", result["reply"])
        self.assertEqual(self.memory.pending_dining["item"], "今天的菜")
        self.assertEqual(load_feedback(self.path), [])

    async def test_decline_clears_unsubmitted_feedback(self):
        await self.turn("今天的肉有点咸", "dining", "[[DINING_PREPARE|taste|肉|有点咸|]]")
        self.memory.commit("这个不用了", {"intent": "decline", "action": "close",
                                     "reply": "好的。", "emotion": None, "gesture": None})
        self.assertIsNone(self.memory.pending_dining)
        self.assertEqual(load_feedback(self.path), [])

    async def test_model_cannot_invent_detail_or_write_without_explicit_confirmation(self):
        result = await self.turn("食堂青菜太咸", "dining", "[[DINING_PREPARE|taste|青菜|太咸|少放盐]]")
        self.assertIn("暂时没有提交", result["reply"])
        self.assertIsNone(self.memory.pending_dining)
        await self.turn("食堂青菜太咸", "dining", "[[DINING_PREPARE|taste|青菜|太咸|-]]")
        result = await self.turn("今天我有点累", "dining", "[[DINING_CONFIRM]]")
        self.assertIn("暂时没有提交", result["reply"])
        self.assertEqual(load_feedback(self.path), [])
        self.assertIsNotNone(self.memory.pending_dining)

    async def test_other_service_does_not_change_pending_or_write(self):
        await self.turn("食堂想吃清蒸鱼", "dining", "[[DINING_PREPARE|dish_request|清蒸鱼|-|想吃清蒸鱼]]")
        pending = self.memory.pending_dining.copy()
        result = await self.turn("我今天脖子有点酸", "other", "可以暂时换个舒服的姿势。")
        self.assertEqual(result["intent"], "other")
        self.assertEqual(self.memory.pending_dining, pending)
        self.assertEqual(load_feedback(self.path), [])

    def test_dashboard_escapes_user_text_and_confirmation_requires_pending(self):
        rendered = render_dashboard([{"submitted_at": "2026-10-25", "category": "taste",
                                     "item": "<script>alert(1)</script>", "observation": "太咸",
                                     "request": "少放盐", "status": "new"}])
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        _, error = prepare_transition("[[DINING_CONFIRM]]", None, "确认提交")
        self.assertEqual(error, "dining_confirmation_without_pending")

    def test_storage_failure_does_not_claim_submission(self):
        transition, error = prepare_transition("[[DINING_PREPARE|taste|青菜|太咸|-]]", None, "食堂青菜太咸")
        self.assertIsNone(error)
        self.memory.pending_dining = transition["pending"]
        confirmed, error = prepare_transition("[[DINING_CONFIRM]]", self.memory.pending_dining, "确认提交")
        self.assertIsNone(error)
        blocked = Path(self.tmp.name) / "blocked"
        blocked.mkdir()
        result = {"intent": "dining", "action": "continue", "reply": confirmed["reply"],
                  "emotion": None, "gesture": None, "_dining_transition": confirmed}
        reply = self.memory.commit("确认提交", result, dining_records_path=blocked)
        self.assertIn("没保存成功", reply.text)
        self.assertIsNotNone(self.memory.pending_dining)
