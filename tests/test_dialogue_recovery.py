import asyncio
import json
import time
import unittest
from types import SimpleNamespace

from x2_agent.model_dialogue import generate_dialogue, ModelDialogue
from x2_agent.presentation import capabilities


def plan(**kwargs):
    return dict(dict(intent="chat", action="continue", reply="我在，您说。",
                     emotion="happy", gesture=None), **kwargs)


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = {**ModelDialogue().context(), "capabilities": capabilities()}
        self.calls = []

    async def run_plans(self, plans, context=None, utterance="您好"):
        async def stream(prompt, history, *args, **kwargs):
            self.calls.append((prompt, history))
            yield "text", json.dumps(plans[min(len(self.calls)-1, len(plans)-1)])
        return await generate_dialogue(SimpleNamespace(stream=stream), utterance,
                                       context or self.ctx, "model", "key")

    async def test_unavailable_gesture_does_not_discard_speech_or_expression(self):
        value = await self.run_plans([plan(gesture="clap")])
        self.assertEqual(value, plan())
        self.assertEqual(len(self.calls), 1)

    async def test_no_control_drops_both_and_does_not_retry(self):
        self.ctx["capabilities"] = capabilities(False)
        value = await self.run_plans([plan(gesture={"motion": 1002})])
        self.assertEqual(value, plan(emotion=None))
        self.assertEqual(len(self.calls), 1)

    async def test_greeting_uses_three_fields_without_model_flow_classification(self):
        self.ctx["turn_kind"] = "greeting"
        repaired = plan(intent="greeting", reply="您好，今天感觉怎么样？")
        value = await self.run_plans([{k: repaired[k] for k in ("reply", "emotion", "gesture")}])
        self.assertEqual(value, repaired)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("不需要识别意图", self.calls[0][0])

    async def test_bad_greeting_is_still_rejected_and_repaired(self):
        self.ctx["turn_kind"] = "greeting"
        bad = {"reply": "您好", "emotion": "happy", "gesture": None}
        good = {**bad, "reply": "您好，今天状态怎么样？"}
        value = await self.run_plans([bad, good])
        self.assertEqual(value["intent"], "greeting")
        self.assertEqual(len(self.calls), 2)

    async def test_help_clarification_after_interview_is_allowed(self):
        self.ctx["health_rounds"] = 2
        self.ctx["interview_active"] = False
        value = await self.run_plans([plan(intent="other", reply="这次不舒服持续多久了？")])
        self.assertEqual(value["action"], "continue")
        self.assertIn("care_reference", json.loads(self.calls[0][1][0]["content"]))

    async def test_second_round_question_preserved_as_service(self):
        self.ctx.update(interview_active=True, health_rounds=1)
        value = await self.run_plans([
            plan(intent="health", action="close", reply="还有哪里不舒服？"),
            plan(intent="health", action="close", reply="有需要随时叫我。")])
        self.assertEqual(value["reply"], "还有哪里不舒服？")
        self.assertEqual((value["intent"], value["action"]), ("other", "continue"))
        self.assertEqual(len(self.calls), 1)

    async def test_first_health_continue_with_question_keeps_model_answer(self):
        self.ctx.update(interview_active=True, health_rounds=0)
        draft = plan(intent="health", action="continue",
                     reply="听您说有些不舒服。您能说说是哪里不舒服吗？", emotion="sympathy")
        value = await self.run_plans([draft], utterance="我今天感觉有点不舒服")
        self.assertEqual((value["intent"], value["action"]), ("health", "followup"))
        self.assertEqual(value["reply"], draft["reply"])
        self.assertEqual(len(self.calls), 1)

    async def test_first_health_continue_without_question_adds_interview_followup(self):
        self.ctx.update(interview_active=True, health_rounds=0)
        draft = plan(intent="health", action="continue", reply="您先坐下来歇一会儿。")
        value = await self.run_plans([draft], utterance="我今天感觉有点不舒服")
        self.assertEqual((value["intent"], value["action"]), ("health", "followup"))
        self.assertTrue(value["reply"].startswith(draft["reply"]))
        self.assertIn("影响您今天活动吗", value["reply"])

    async def test_urgent_health_continue_stays_service_not_interview(self):
        self.ctx.update(interview_active=True, health_rounds=0)
        draft = plan(intent="health", action="continue", reply="请立即联系现场医护。")
        value = await self.run_plans([draft], utterance="我突然胸痛")
        self.assertEqual((value["intent"], value["action"]), ("other", "continue"))

    async def test_two_failures_stop(self):
        self.assertIsNone(await self.run_plans([plan(intent="unknown")]))
        self.assertEqual(len(self.calls), 2)

    async def test_second_call_shares_deadline(self):
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                await asyncio.sleep(.02)
                yield "text", "{}"
            else:
                await asyncio.sleep(2)
                yield "text", "{}"
        started = time.monotonic()
        self.assertIsNone(await generate_dialogue(SimpleNamespace(stream=stream),
                          "您好", self.ctx, "model", "key", timeout=.08))
        self.assertEqual(len(calls), 2)
        self.assertLess(time.monotonic() - started, .5)

    async def test_cancellation_does_not_retry(self):
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            await asyncio.sleep(10)
            yield "text", "{}"
        task = asyncio.create_task(generate_dialogue(SimpleNamespace(stream=stream),
                                   "您好", self.ctx, "model", "key"))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(calls), 1)
