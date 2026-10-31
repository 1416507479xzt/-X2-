import json
import unittest
from types import SimpleNamespace
from x2_agent.dialogue_quality import question_history, review_flags, repeated_question, suppress_repeated_question, suppress_repeated_advice, unconfirmed_injury_advice, unwanted_injury_followup
from x2_agent.model_dialogue import generate_dialogue, ModelDialogue, ensure_interview_closing, soften_fatigue_question, validate_reply
from x2_agent.presentation import capabilities


def result(text):
    return dict(intent="other", action="continue", reply=text, emotion=None, gesture=None)


class QualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_only_waist_opening_gets_practical_tip_in_one_call(self):
        memory = ModelDialogue()
        memory.begin()
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            yield "text", json.dumps(dict(intent="health", action="followup",
                reply="这种腰酸影响您今天活动吗？", emotion="sympathy", gesture=None), ensure_ascii=False)
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "我今天感觉腰有点酸",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 1)
        self.assertIn("维持日常活动", answer["reply"])
        self.assertIn("影响您今天活动吗", answer["reply"])

    async def test_first_nonurgent_waist_response_keeps_second_round_available(self):
        memory = ModelDialogue()
        memory.begin()
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            yield "text", json.dumps(dict(intent="health", action="close",
                reply="若没有受伤且活动不会加重疼痛，可在不加重疼痛的范围内维持日常活动。若近期摔倒或扭伤请联系医护。",
                emotion="sympathy", gesture=None), ensure_ascii=False)
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "我今天腰有点酸",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 1)
        self.assertEqual(answer["action"], "followup")
        self.assertIn("影响您今天活动吗", answer["reply"])

    def test_long_acknowledgement_shortens_without_retry(self):
        draft = dict(intent="acknowledge", action="continue",
                     reply="好的，您说的话我已经记下来了，如果还有问题可以随时告诉我。",
                     emotion="neutral", gesture=None)
        checked = validate_reply(json.dumps(draft, ensure_ascii=False),
                                 {**ModelDialogue().context(), "capabilities": capabilities()},
                                 degrade_presentation=True)
        self.assertEqual(checked["reply"], "好的。")

    async def test_question_only_fatigue_opening_keeps_single_model_call(self):
        memory = ModelDialogue()
        memory.begin()
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            yield "text", json.dumps(dict(intent="health", action="followup",
                reply="这种疲惫影响您今天做事了吗？", emotion="sympathy", gesture=None), ensure_ascii=False)
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "今天有点疲惫",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 1)
        self.assertIn("保持规律的作息", answer["reply"])
        self.assertIn("影响您今天做事了吗", answer["reply"])

    def test_second_turn_does_not_repeat_opening_hello(self):
        memory = ModelDialogue()
        memory.begin()
        memory.health_rounds = 1
        draft = dict(intent="health", action="close", reply="您好，您说疲惫有点影响活动。今天先照顾好自己。",
                     emotion="sympathy", gesture=None)
        checked = validate_reply(json.dumps(draft, ensure_ascii=False),
                                 {**memory.context(), "capabilities": capabilities()}, degrade_presentation=True)
        self.assertEqual(checked["reply"], "您说疲惫有点影响活动。今天先照顾好自己。")

    def test_fatigue_question_does_not_assume_reverse_causation(self):
        draft = dict(intent="health", action="followup",
                     reply="今天有点疲惫，可以保持规律作息。您的睡眠情况受疲惫影响了吗？",
                     emotion="sympathy", gesture=None)
        repaired = soften_fatigue_question(draft, "今天有点疲惫")
        self.assertIn("您最近睡得怎么样？", repaired["reply"])
        self.assertNotIn("受疲惫影响", repaired["reply"])
        self.assertEqual(repaired["emotion"], "sympathy")

    def test_initial_fatigue_question_is_answerable_by_short_impact_reply(self):
        memory = ModelDialogue()
        memory.begin()
        draft = dict(intent="health", action="followup",
                     reply="今天有点疲惫，可以保持规律作息。昨晚睡得怎么样？",
                     emotion="sympathy", gesture=None)
        revised = soften_fatigue_question(draft, "我今天有点疲惫", memory.context())
        self.assertIn("这种疲惫影响您今天做事了吗？", revised["reply"])
        self.assertNotIn("昨晚", revised["reply"])

    def test_unconfirmed_injury_blocks_routine_neck_back_advice(self):
        advice = "颈部避免长时间保持同一姿势，腰背可以维持日常活动、避免久卧。"
        self.assertTrue(unconfirmed_injury_advice(advice, "脖子疼，腰酸", []))
        self.assertFalse(unconfirmed_injury_advice(advice,
                         "脖子疼，腰酸，没有摔倒，也没有扭伤", []))
        self.assertTrue(unconfirmed_injury_advice(advice,
                        "后来又摔倒了", [{"user": "脖子疼，腰酸，没摔倒，也没扭伤"}]))
        self.assertFalse(unconfirmed_injury_advice(advice + "若近期摔倒或扭伤，请联系医护。",
                         "脖子疼，腰酸", []))
        self.assertTrue(unwanted_injury_followup("最近有没有摔倒或扭伤？", "脖子疼，腰酸", []))
        self.assertFalse(unwanted_injury_followup("若近期摔倒或扭伤，请联系医护。", "脖子疼，腰酸", []))

    async def test_model_repairs_unsafe_second_interview_turn_without_question(self):
        memory = ModelDialogue()
        memory.begin()
        memory.health_rounds = 1
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            draft = (dict(intent="health", action="close", reply="颈部别长时间保持同一姿势，腰背避免久卧。",
                          emotion="sympathy", gesture="open_arms") if len(calls) == 1 else
                     dict(intent="health", action="close", reply="颈部和腰背不适有时与久持一个姿势有关。若没有受伤且活动不加重疼痛，可换个舒服姿势。若近期摔倒或扭伤，请联系医护。今天先照顾好自己，有需要再叫我。",
                          emotion="sympathy", gesture=None))
            yield "text", json.dumps(draft, ensure_ascii=False)
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "脖子疼，腰酸",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 2)
        self.assertEqual((answer["intent"], answer["action"]), ("health", "close"))
        self.assertIn("摔倒或扭伤", answer["reply"])
        self.assertNotIn("久卧", answer["reply"])
        self.assertNotRegex(answer["reply"], r"[？?]")

    async def test_repeated_injury_question_gets_general_advice_not_apology(self):
        memory = ModelDialogue()
        memory.begin()
        async def stream(*args, **kwargs):
            yield "text", json.dumps(dict(intent="health", action="followup",
                reply="颈部避免长时间保持同一姿势。最近有摔倒吗？", emotion=None, gesture=None),
                ensure_ascii=False)
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "脖子疼",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertIn("摔倒或扭伤", answer["reply"])
        self.assertNotRegex(answer["reply"], r"[？?]")
        self.assertIn("若没有受伤", answer["reply"])

    def test_second_health_turn_gets_one_caring_ending(self):
        ctx = {**ModelDialogue().context(), "interview_active": True, "health_rounds": 1}
        draft = dict(intent="health", action="close", reply="颈部避免久持一个姿势。", emotion=None, gesture=None)
        finished = ensure_interview_closing(draft, ctx)
        self.assertIn("有需要再叫我", finished["reply"])
        self.assertEqual(ensure_interview_closing(finished, ctx), finished)
        self.assertEqual(ensure_interview_closing({**draft, "intent": "other", "action": "continue"}, ctx),
                         {**draft, "intent": "other", "action": "continue"})
        urgent = {**draft, "reply": "请现在联系现场医护。"}
        self.assertEqual(ensure_interview_closing(urgent, ctx), urgent)

    async def test_second_health_turn_closing_reaches_generated_reply(self):
        memory = ModelDialogue()
        memory.begin()
        memory.health_rounds = 1
        async def stream(*args, **kwargs):
            yield "text", json.dumps(dict(intent="health", action="close",
                                          reply="颈部避免久持一个姿势。", emotion=None, gesture=None))
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "没摔倒，脖子有点酸",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertIn("有需要再叫我", answer["reply"])

    async def test_fatigue_prompt_avoids_assuming_sleep_cause(self):
        memory = ModelDialogue()
        memory.begin()
        prompts = []
        async def stream(prompt, *args, **kwargs):
            prompts.append(prompt)
            yield "text", json.dumps(dict(intent="health", action="followup",
                reply="听起来今天有些疲惫，先按自己的节奏活动。最近这种疲惫持续多久了？",
                emotion=None, gesture=None), ensure_ascii=False)
        await generate_dialogue(SimpleNamespace(stream=stream), "我今天有点累",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertIn("不能认定没睡好", prompts[0])

    def test_questions_retain_following_quote_without_inference(self):
        turns = [{"user": "腰疼", "assistant": "近期有没有摔倒或扭伤？"},
                 {"user": "怎么缓解", "assistant": "信息尚不够。"}]
        self.assertEqual(question_history(turns), [{"question": "近期有没有摔倒或扭伤？", "following_user_quote": "怎么缓解"}])
        self.assertTrue(repeated_question("请问您最近是否摔倒或扭伤呢？", turns))
        self.assertTrue(repeated_question("您好，请问您近期有没有摔倒、扭伤过，或者是否出现双腿无力、麻木等其他不适呢？", turns))
        self.assertFalse(repeated_question("您想查今天的安排吗？", turns))

    def test_severity_trigger_is_not_a_claim_classifier(self):
        self.assertIn("check_severity_against_user_quotes", review_flags(result("您的腰突然加重。"), []))
        for text in ("如果突然剧痛请及时就医。", "您说不是突然剧痛。", "您的不适有没有在加重呢？"):
            self.assertNotIn("check_severity_against_user_quotes", review_flags(result(text), []))
        self.assertEqual(review_flags(dict(intent="reminder", reply="[[REMINDER_TODAY]]"), []), [])

    def test_repeated_advice_with_new_duration_is_reviewed(self):
        turns = [{"user": "腰和脖子酸，没有摔倒，也没有扭伤",
                  "assistant": "别长时间保持同一姿势，在不加重疼痛的范围内维持日常活动。"}]
        draft = result("不要长时间保持同一姿势，在不加重疼痛的范围内维持日常活动。持续多久了？")
        self.assertIn("repeated_advice_ignores_new_information", review_flags(draft, turns, "一两天吧"))
        self.assertNotIn("repeated_advice_ignores_new_information", review_flags(draft, turns, "再说一遍怎么缓解"))
        cleaned = suppress_repeated_advice(result("腰酸和脖子难受持续一两天了，避免长时间保持同一姿势，在不加重疼痛范围内维持日常活动。还有加重吗？"), turns, "一两天吧")
        self.assertIn("一两天", cleaned["reply"])
        self.assertNotIn("保持同一姿势", cleaned["reply"])
        self.assertNotIn("维持日常活动", cleaned["reply"])
        variants = [{"user": "腰和脖子难受", "assistant": "腰酸如果能活动，就别久卧，在不加重疼痛的范围内维持日常活动。"}]
        next_reply = result("您可以在不加重疼痛的范围内维持日常活动，避免久卧。")
        self.assertIn("repeated_advice_ignores_new_information", review_flags(next_reply, variants, "一两天吧"))
        fatigue = [{"user": "疲惫", "assistant": "保持规律的睡眠时间，睡前安排些放松活动。"}]
        next_reply = result("疲惫已有一点影响，建议保持规律作息，睡前做点放松的事。")
        self.assertIn("repeated_advice_ignores_new_information", review_flags(next_reply, fatigue, "有一点影响日常活动"))

    def test_repeated_sleep_advice_after_duration_is_reviewed(self):
        turns = [{"user": "现在感觉有点疲惫", "assistant": "可以保持规律的睡眠时间，营造安静昏暗的睡眠环境。请问这种疲惫持续多久了？"}]
        draft = dict(intent="health", action="close",
                     reply="可以保持规律的睡眠时间，营造安静昏暗的睡眠环境。今天先照顾好自己，有需要再叫我。")
        self.assertIn("repeated_advice_ignores_new_information", review_flags(draft, turns, "一两天吧"))
        cleaned = suppress_repeated_advice(draft, turns, "一两天吧")
        self.assertIn("一两天", cleaned["reply"])
        self.assertNotIn("睡眠环境", cleaned["reply"])

    def test_short_duration_is_not_spread_to_older_fatigue(self):
        turns = [{"user": "疲惫", "assistant": "昨晚睡得怎么样？"},
                 {"user": "腰酸和脖子难受", "assistant": "最近有没有摔倒？"}]
        self.assertIn("duration_spread_to_older_symptom",
                      review_flags(result("您的疲惫和颈腰不适才一两天。"), turns, "一两天吧"))
        self.assertNotIn("duration_spread_to_older_symptom",
                         review_flags(result("您说腰和脖子不适有一两天了。"), turns, "一两天吧"))

    def test_short_cleaned_fatigue_close_uses_complete_grounded_reply(self):
        turns = [{"user": "我有点疲惫", "assistant": "可以保持规律的睡眠时间，睡前安排放松活动，比如阅读或听音乐。"}]
        draft = dict(intent="health", action="close", reply="疲惫影响日常活动的话，可以保持规律的睡眠时间，睡前安排放松活动，比如阅读或听音乐。", emotion=None, gesture=None)
        cleaned = suppress_repeated_advice(draft, turns, "有一点影响日常活动")
        self.assertIn("影响日常活动", cleaned["reply"])
        self.assertIn("医护", cleaned["reply"])
        self.assertIn("有需要", cleaned["reply"])
        self.assertNotIn("的话。", cleaned["reply"])

    async def test_failed_style_review_keeps_new_fact_without_apology_or_repeated_advice(self):
        turns = [{"user": "腰和脖子酸，没有摔倒，也没有扭伤",
                  "assistant": "别长时间保持同一姿势，在不加重疼痛的范围内维持日常活动。"}]
        calls = []
        async def stream(*args, **kwargs):
            calls.append(1)
            draft = (result("腰酸和脖子难受有一两天了，别长时间保持同一姿势，在不加重疼痛的范围内维持日常活动。有没有加重？")
                     if len(calls) == 1 else dict(intent="bad", action="continue", reply="无效", emotion=None, gesture=None))
            yield "text", json.dumps(draft, ensure_ascii=False)
        ctx = {**ModelDialogue().context(), "capabilities": capabilities(), "verbatim_turns": turns}
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "一两天吧", ctx, "m", "k")
        self.assertEqual(len(calls), 3)
        self.assertIn("一两天", answer["reply"])
        self.assertNotIn("保持同一姿势", answer["reply"])
        self.assertNotIn("抱歉", answer["reply"])

    def test_fatigue_question_only_triggers_practical_reply_review(self):
        draft = dict(intent="health", reply="您的疲惫影响日常活动了吗？")
        self.assertIn("fatigue_question_without_practical_tip", review_flags(draft, [], "我有点疲惫"))
        draft["reply"] = "睡前可听点轻松的音乐。您的疲惫影响日常活动了吗？"
        self.assertNotIn("fatigue_question_without_practical_tip", review_flags(draft, [], "我有点疲惫"))

    async def test_fatigue_opening_keeps_interview_active_without_retry(self):
        memory = ModelDialogue()
        memory.begin()
        calls = []
        async def stream(prompt, *args, **kwargs):
            calls.append(prompt)
            reply = (dict(intent="health", action="followup", reply="疲惫影响日常活动了吗？", emotion=None, gesture=None)
                     if len(calls) == 1 else
                     dict(intent="health", action="followup", reply="睡前可以听些轻松的音乐。疲惫影响日常活动了吗？", emotion=None, gesture=None))
            yield "text", json.dumps(reply, ensure_ascii=False)
        answer = await generate_dialogue(SimpleNamespace(stream=stream), "我有点疲惫",
            {**memory.context(), "capabilities": capabilities()}, "m", "k")
        self.assertEqual(len(calls), 1)
        self.assertIn("开场第一轮", calls[0])
        self.assertEqual(answer["intent"], "health")
        self.assertIn("保持规律的作息", answer["reply"])

    def test_post_review_repetition_is_removed_without_dropping_safety(self):
        turns = [{"user": "腰疼", "assistant": "近期有没有摔倒或扭伤？"}]
        for draft in ("请问您近期有摔倒或扭伤的情况吗？", "请您告知近期是否有摔倒或者扭伤的情况，以便进一步判断。"):
            revised = suppress_repeated_question(result(draft), turns, "怎么缓解")
            self.assertNotIn("摔倒", revised["reply"])
            self.assertNotIn("？", revised["reply"])
        revised = suppress_repeated_question(result("请现在联系现场医护。近期有没有摔倒或扭伤？"), turns, "加重了")
        self.assertEqual(revised["reply"], "请现在联系现场医护。")
        revised = suppress_repeated_question(result("暂时信息不足。请您告知近期是否有摔倒或扭伤，或是其他不适，以便判断。"), turns, "不想回答")
        self.assertEqual(revised["reply"], "暂时信息不足。")

    def test_explicit_repeat_request_and_unrelated_questions_are_allowed(self):
        turns = [{"user": "腰疼", "assistant": "近期有没有摔倒或扭伤？"}]
        draft = result("近期有没有摔倒或扭伤？")
        self.assertEqual(suppress_repeated_question(draft, turns, "没听清，请再问一遍"), draft)
        draft = result("哪种药品？")
        self.assertEqual(suppress_repeated_question(draft, turns, "药怎么吃"), draft)

    async def run_review(self, user, draft, revised, turns):
        calls = []
        async def stream(prompt, messages, *args, **kwargs):
            calls.append((prompt, json.loads(messages[0]["content"])))
            yield "text", json.dumps(result(draft if len(calls) == 1 else revised))
        ctx = {**ModelDialogue().context(), "capabilities": capabilities(), "verbatim_turns": turns}
        reply = await generate_dialogue(SimpleNamespace(stream=stream), user, ctx, "m", "k")
        self.assertEqual(len(calls), 2)
        self.assertEqual(reply["reply"], revised)
        self.assertNotIn("draft", calls[1][1]["quality_review"])
        self.assertNotIn(draft, [t["user"] for t in calls[1][1]["verbatim_turns"]])
        self.assertIn("速度和程度仍未知", calls[1][0])
        return calls

    async def test_repeated_question_revised_before_delivery(self):
        calls = []
        advice = "腰背不适有时与久坐有关，但无法确定原因。若没有受伤且活动不加重疼痛，可以换个舒服的姿势。若近期摔倒或扭伤，请联系医护。"
        async def stream(prompt, messages, *args, **kwargs):
            calls.append(prompt)
            yield "text", json.dumps(result("请问您近期有没有摔倒或扭伤？" if len(calls) == 1 else advice))
        ctx = {**ModelDialogue().context(), "capabilities": capabilities(),
               "verbatim_turns": [{"user": "腰疼", "assistant": "近期有没有摔倒或扭伤？"}]}
        reply = await generate_dialogue(SimpleNamespace(stream=stream), "怎么缓解", ctx, "m", "k")
        self.assertEqual(len(calls), 2)
        self.assertIn("不要询问是否摔倒或扭伤", calls[1])
        self.assertEqual(reply["reply"], advice)

    async def test_worsening_does_not_authorize_sudden_or_multiple_sites(self):
        await self.run_review("腰比刚才更酸", "您的腰和脖子突然剧烈加重。",
            "腰比刚才更酸，脖子是否有变化还不清楚。",
            [{"user": "脖子也疼", "assistant": "近期有受伤吗？"}])

    async def test_correction_and_genuine_urgent_case_can_survive_review(self):
        await self.run_review("不是突然，只是酸一点", "您突然加重。",
            "不是突然发生，只是比之前酸一些。", [])
        await self.run_review("现在腰突然疼得很厉害", "突然剧痛请及时就医。",
            "请现在联系现场医护或及时就医。", [])
