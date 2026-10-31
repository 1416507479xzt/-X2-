import json
import unittest
from types import SimpleNamespace

from x2_agent.model_dialogue import ModelDialogue, generate_dialogue, remove_registration_prefix
from x2_agent.presentation import capabilities


class ReplyStyleTests(unittest.IsolatedAsyncioTestCase):
    def test_observed_registration_prefixes(self):
        cases = {
            "我记下您脖子不舒服啦。别长时间保持同一姿势。": "别长时间保持同一姿势。",
            "您脖子不舒服我记下了。您说。": "您说。",
            "好的，您肚子不舒服的情况我记下了，要是之后有变化可以告诉我。": "要是之后有变化可以告诉我。",
            "我了解您现在腰部也不舒服，多留意腰部的状态。": "多留意腰部的状态。",
            "我知道您现在肚子不舒服了。这样多久了？": "这样多久了？",
            "我记下了。": "",
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertEqual(remove_registration_prefix(original), expected)

    def test_preserve_recall_quotes_questions_and_medical_conditions(self):
        for text in ("我记得您说过脖子疼，后来又说不疼了。",
                     "“我记下了”这句话显得生硬。",
                     "您是想让我记下这个提醒吗？",
                     "如果疼痛持续不缓解，请咨询医护。",
                     "您之前提过腰酸，现在是加重了吗？"):
            self.assertEqual(remove_registration_prefix(text), text)

    async def test_valid_remainder_kept_without_extra_model_call(self):
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            yield "text", json.dumps(dict(intent="other", action="continue",
                reply="我知道您现在肚子不舒服了。这样多久了？", emotion="neutral", gesture=None))
        memory = ModelDialogue()
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "肚子不舒服",
                {**memory.context(), "capabilities": capabilities()}, "model", "key")
        self.assertEqual(answer["reply"], "这样多久了？")
        self.assertEqual(len(calls), 1)
        memory.commit("肚子不舒服", answer)
        self.assertEqual(memory.verbatim_turns[-1], {"user": "肚子不舒服", "assistant": "这样多久了？"})

    async def test_empty_remainder_uses_bounded_repair(self):
        calls = []
        async def stream(prompt, *args, **kwargs):
            calls.append(prompt)
            yield "text", json.dumps(dict(intent="other", action="continue",
                reply="我记下了。" if len(calls) == 1 else "这样多久了？", emotion=None, gesture=None))
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "肚子不舒服",
                {**ModelDialogue().context(), "capabilities": capabilities()}, "model", "key")
        self.assertEqual(answer["reply"], "这样多久了？")
        self.assertEqual(len(calls), 2)
        self.assertIn("registration_only_reply", calls[1])
