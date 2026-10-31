"""Regressions for the user's neck -> back -> forgotten neck transcript."""
import unittest

from x2_agent.competition_flow import HealthGreetingFlow
from x2_agent.health_memory import SessionHealthMemory


class SessionMemoryTests(unittest.TestCase):
    def test_distinct_areas_survive_many_intervening_turns(self):
        flow = HealthGreetingFlow()
        flow.begin()
        flow.respond("今天感觉还可以", {"intent": "health", "state": "状态良好", "detail": None})
        flow.respond("想散步")
        flow.respond("我现在感觉脖子有点疼。")
        flow.respond("有什么缓解脖子疼的办法吗？")
        flow.respond("我感觉腰有点酸。")
        flow.respond("前一阵子就开始了。")
        for i in range(12):
            flow.respond("给我讲个笑话")
        for query in ("今天身体哪里不舒服？", "我和你说过我身体哪里不舒服。", "我刚才跟你说了什么？"):
            with self.subTest(query=query):
                answer = flow.respond(query).text
                self.assertIn("脖子", answer)
                self.assertIn("腰", answer)
        answer = flow.respond("我的脖子呢？").text
        self.assertIn("脖子有点疼", answer)
        self.assertNotIn("腰", answer)
        self.assertIn("脖子有点疼", flow.memory_context())

    def test_question_third_person_and_hypothetical_are_not_symptoms(self):
        for text in ("有什么缓解脖子疼的办法吗？", "我的脖子呢？", "我妈妈脖子有点疼",
                     "如果脖子疼怎么办", "他说腰酸", "我说的是‘脖子疼’这个词"):
            memory = SessionHealthMemory()
            memory.observe(text)
            self.assertEqual(memory.reports, {}, text)

    def test_correction_updates_only_its_own_body_area(self):
        memory = SessionHealthMemory()
        memory.observe("脖子有点疼，腰有点酸")
        memory.observe("脖子已经不疼了")
        self.assertEqual(memory.reports["脖子"], "脖子已经不疼了")
        self.assertEqual(memory.reports["腰"], "腰有点酸")
        self.assertNotIn("脖子有点疼", memory.spoken())
        memory.observe("不是脖子疼，是肩膀疼")
        self.assertEqual(memory.reports["脖子"], "不是脖子疼")
        self.assertEqual(memory.reports["肩膀"], "是肩膀疼")

    def test_no_invention_for_a_body_area_never_reported(self):
        flow = HealthGreetingFlow()
        flow.begin()
        flow.respond("腰有点酸")
        self.assertIn("没有这部分的明确描述", flow.respond("我的脖子呢？").text)
        self.assertNotIn("脖子", flow.body_memory.reports)

    def test_reconnect_preserves_but_new_visitor_clears_memory(self):
        flow = HealthGreetingFlow()
        flow.begin("甲")
        flow.respond("我现在脖子有点疼")
        flow.begin("甲")
        self.assertIn("脖子", flow.memory_context())
        flow.begin("乙")
        self.assertEqual(flow.memory_context(), "")


if __name__ == "__main__":
    unittest.main()
