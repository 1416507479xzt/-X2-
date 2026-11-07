"""Run the same synthetic competition conversation against one Ark model.

Usage (from this repository's root directory):
    python docs/zh-CN/model-evaluation/2026-11-08/compare_models.py --model doubao-seed-2-0-mini-260428 --output result.json

The existing .env is read in memory. Credentials are never written to output.
The dining record goes to a separate test file next to the output file.
"""
import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time


sys.path.insert(0, os.getcwd())

from x2_agent.config import load_env
from x2_agent.life_assistance import LOCAL_TIME, load_context
from x2_agent.llm import ARK_API_URL, LlmClient
from x2_agent.model_dialogue import ModelDialogue, generate_dialogue
from x2_agent.presentation import capabilities


TEST_TIME = datetime(2026, 10, 24, 11, 1, tzinfo=LOCAL_TIME)
UTTERANCES = [
    ("stage1", "我今天有点疲惫。"),
    ("stage1", "最近没睡好，脖子和腰都有点酸。"),
    ("memory", "刚才我说哪里不舒服？"),
    ("medicine", "降压药怎么吃？"),
    ("reminder", "今天还有什么安排？"),
    ("reminder", "现在该吃药了吗？"),
    ("dining", "我想给食堂提个意见，今天的菜太咸了，下次想吃清淡一点的。"),
    ("dining", "确认提交"),
]


async def run(model: str, output: Path):
    load_env()
    ark_key = os.environ.get("ARK_API_KEY", "")
    if not ark_key:
        raise SystemExit("ARK_API_KEY is missing")
    memory = ModelDialogue()
    memory.begin()
    llm = LlmClient(os.environ.get("ARK_API_URL", ARK_API_URL))
    result = {"model": model, "test_time": TEST_TIME.isoformat(), "turns": []}
    records = output.with_suffix(".dining.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        started = time.perf_counter()
        greeting = await generate_dialogue(
            llm, "来访者已语音唤醒，请开始问候。",
            {**memory.context(), "turn_kind": "greeting", "capabilities": capabilities()},
            model, ark_key, timeout=3.0,
        )
        result["turns"].append({"section": "greeting", "user": "语音唤醒",
                                "answer": greeting, "model_ms": round((time.perf_counter()-started)*1000)})
        memory.remember("语音唤醒", greeting["reply"] if greeting else "您好，我是灵犀。您今天感觉怎么样？")
        for section, utterance in UTTERANCES:
            context = {**memory.context(), "turn_kind": "dialogue", "capabilities": capabilities(),
                       "life_assistance": load_context(now=TEST_TIME)}
            started = time.perf_counter()
            answer = await generate_dialogue(llm, utterance, context, model, ark_key)
            duration = round((time.perf_counter()-started)*1000)
            result["turns"].append({"section": section, "user": utterance,
                                    "answer": answer, "model_ms": duration})
            if answer:
                memory.commit(utterance, answer, dining_records_path=records)
            else:
                memory.remember_unanswered(utterance)
        result["dining_record_saved"] = records.exists() and records.stat().st_size > 0
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await llm.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.model, args.output))
