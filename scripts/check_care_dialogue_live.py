"""Opt-in paid text-only acceptance check. No TTS, gateway or robot connection.

Run from example/x2_agent: python scripts/check_care_dialogue_live.py --live
Uses existing .env in memory; never prints credentials or raw provider errors.
Outputs synthetic dialogue, not real patients' data. Human review is required.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from x2_agent.agent_config import AgentConfig
from x2_agent.llm import LlmClient
from x2_agent.model_dialogue import ModelDialogue, generate_dialogue
from x2_agent.presentation import capabilities
from x2_agent.life_assistance import load_context, LOCAL_TIME


async def main(scenario="care"):
    config = AgentConfig.from_env()
    if not config.ark_key:
        raise SystemExit("Missing ARK_API_KEY")
    llm = LlmClient(config.ark_api_url)
    memory = ModelDialogue()
    memory.begin()
    try:
        greeting_trials = 3 if scenario == "care" else 1
        for index in range(greeting_trials):
            answer = await generate_dialogue(llm, "来访者唤醒", {
                **ModelDialogue().context(), "turn_kind": "greeting", "capabilities": capabilities()
            }, config.llm_model, config.ark_key)
            print(json.dumps({"greeting_trial": index + 1, "answer": answer}, ensure_ascii=False))
            if index == greeting_trials - 1 and answer:
                memory.remember("语音唤醒", answer["reply"])
        utterances = (("我今天感觉有点疲惫。", "睡眠不太好。",
                          "你知道我为什么睡眠不好吗？",
                          "我脖子不舒服，我腰不舒服，我肚子不舒服。",
                          "你不能给我一些建议吗？", "怎么缓解脖子疼？") if scenario == "care" else
                      ("我今天感觉有点疲惫。", "昨天睡得不太好。", "我今天腰有点酸痛。",
                       "好的，灵犀。", "好的。", "我没有什么问题了。", "你好，灵犀。",
                       "灵犀灵犀", "好的，不过腰更疼了。", "好的，你还记得我刚才哪里不舒服吗？"))
        if scenario == "presentation":
            utterances = ("睡眠不太好，有什么生活上的建议吗？", "好的。",
                          "不要做动作，只用语言解释怎样改善睡眠环境。",
                          "现在可以配合动作，给我讲讲怎样安排睡前的放松吧。")
        if scenario == "proactive":
            utterances = ("今天脖子有点酸，没有受伤，也没有手臂麻木或发冷。",
                          "腰也有点酸，没有摔倒，没有腿麻无力或大小便变化，正常走路不加重。",
                          "好的。", "现在肚子突然疼得很厉害。")
        if scenario == "services":
            utterances = ("今天脖子有点酸。", "降压药怎么吃？", "药名我也记不清了。",
                          "今天还有什么安排？", "下一项是什么时候？", "你还记得我哪里不舒服吗？")
        if scenario == "medicines":
            utterances = ("降压药怎么吃？", "苯磺酸氨氯地平片。", "宁夏康亚药业的苯磺酸氨氯地平片，5毫克普通片，想了解资料中的吃法。",
                          "有什么注意事项？", "不对，我刚才说错了，是二甲双胍缓释片。", "那我该吃多少？")
        if scenario == "healthy_transition":
            utterances = ("我今天还好。", "我今天挺好的。", "降压药怎么吃？", "苯磺酸氨氯地平片。")
        if scenario in {"reminders", "reminder_natural"}:
            print("Synthetic test clock; no timers or robot connection")
            utterances = ("今天还有什么安排？", "下一项具体几点？", "好的。", "现在该吃药了吗？", "把喝水提醒改到十一点。")
        if scenario == "regression_oct23":
            utterances = ("今天感觉有点疲惫。", "持续好几天了。", "感觉我的腰疼，脖子酸。",
                          "不舒服感觉加重了。", "该怎么缓解腰酸和脖子痛呢？", "有什么好的缓解办法吗？",
                          "今天还有什么要做的？", "需要。", "我让你说一下今天的安排。",
                          "该吃药了吗？", "吃过了。", "那现在还要吃药吗？")
        if scenario == "safe_relief":
            utterances = ("今天脖子有点酸，没有受伤，也没有手臂麻木或发冷。",
                          "腰也有点酸，没有摔倒，没有腿麻无力或大小便变化，正常走路不加重。",
                          "脖子睡觉的时候怎么照顾一下？", "刚才没有加重，现在突然疼得很厉害。")
        if scenario == "quality_repeat":
            utterances = ("腰有点酸，脖子也疼。", "怎么缓解呢？", "你先说说怎么缓解，不想回答那个问题。",
                          "没有摔倒扭伤，没有腿麻无力或大小便变化，也没有手臂麻木发冷，日常活动不加重。",
                          "那脖子睡觉时怎么照顾？")
        if scenario == "quality_severity":
            utterances = ("腰有点酸，脖子也疼。", "腰比刚才更酸了。", "怎么缓解？",
                          "不是突然疼，也不剧烈，只是腰比刚才酸一点，脖子没变。",
                          "你总结一下我现在的情况。", "现在腰突然疼得很厉害。")
        if scenario == "regression_oct24":
            utterances = ("我今日感觉有点疲惫。", "一个星期。", "我腰和脖子不舒服。",
                          "没有摔倒，就是不舒服，酸痛。", "你怎么不给我一些缓解的建议呢？",
                          "降压药怎么吃？", "今天还有什么要做的？", "该吃药了吗？",
                          "我已经吃过药了。", "我什么时候去复诊？", "喝水提醒是什么时候？")
        if scenario == "regression_latest":
            utterances = ("我今天感觉有点疲惫。", "有一点影响日常活动。", "我是因为腰酸和脖子难受睡不好。",
                          "一两天吧。", "没有，目前没有加重。", "降压药怎么吃？", "感冒药怎么吃？",
                          "止泻药怎么吃？", "今天有什么安排？", "该吃药了吗？")
        if scenario == "regression_stage1_latest":
            utterances = ("我今天感觉有点疲惫。", "有一点影响日常活动。", "我是因为腰酸和脖子难受睡不好。",
                          "一两天吧。", "没有，目前没有加重。")
        for utterance in utterances:
            answer = await generate_dialogue(llm, utterance, {
                **memory.context(), "turn_kind": "dialogue", "capabilities": capabilities(),
                **({"life_assistance": load_context()} if scenario in {"services", "medicines", "healthy_transition"} else {}),
                **({"life_assistance": load_context(now=datetime(2026, 10, 23, 9, 45, tzinfo=LOCAL_TIME))} if scenario == "reminders" else {}),
                **({"life_assistance": load_context(now=datetime(2026, 10, 24, 11, 1, tzinfo=LOCAL_TIME))} if scenario in {"regression_oct24", "regression_latest", "regression_stage1_latest"} else {}),
                **({"life_assistance": load_context(now=datetime(2026, 10, 23, 15, 33, tzinfo=LOCAL_TIME))} if scenario in {"reminder_natural", "regression_oct23", "safe_relief", "quality_repeat", "quality_severity"} else {})
            }, config.llm_model, config.ark_key)
            print(json.dumps({"user": utterance, "answer": answer}, ensure_ascii=False))
            if answer:
                memory.commit(utterance, answer)
            else:
                memory.remember_unanswered(utterance)
    finally:
        await llm.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow paid model calls (care: up to 18; conversation: up to 22; presentation/proactive: up to 10; services: up to 14)")
    parser.add_argument("--scenario", choices=("care", "conversation", "presentation", "proactive", "services", "medicines", "healthy_transition", "reminders", "reminder_natural", "regression_oct23", "regression_oct24", "regression_latest", "regression_stage1_latest", "safe_relief", "quality_repeat", "quality_severity"), default="care")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this uses the configured API account")
    asyncio.run(main(args.scenario))
