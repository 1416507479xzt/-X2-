"""Check cloud TTS separately from optional X2 speaker playback.

Default mode only synthesizes a fixed short sentence in memory. --play also
requests AimDK audio focus and plays it, after only_voice is confirmed.
No recordings or credentials are written to disk.
"""

import argparse
import asyncio
from contextlib import aclosing
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from x2_agent.aimdk_audio import PCM_BYTES_PER_SECOND
from x2_agent.tts import BidiTtsClient


TEST_SENTENCE = "您好，我是灵犀，今天感觉怎么样？"
MAX_PCM_BYTES = 20 * PCM_BYTES_PER_SECOND


async def synthesize(key, speaker):
    client = BidiTtsClient(key, speaker)

    async def texts():
        yield TEST_SENTENCE

    audio = bytearray()
    started = time.monotonic()
    first_audio = None
    try:
        async with aclosing(client.stream(texts())) as stream:
            async for chunk in stream:
                if first_audio is None:
                    first_audio = time.monotonic() - started
                if len(audio) + len(chunk) > MAX_PCM_BYTES:
                    raise ValueError("TTS PCM 超过 20 秒探针上限")
                audio.extend(chunk)
    finally:
        await client.close()
    if not audio or len(audio) % 2:
        raise ValueError("TTS 没有返回完整的 S16LE PCM")
    print("TTS 成功：首包 %.2fs，PCM %.2fs；未保存音频。" %
          (first_audio, len(audio) / PCM_BYTES_PER_SECOND), flush=True)
    return bytes(audio)


async def play(pcm):
    from x2_agent.aimdk_playback import AimdkPcmPlayer

    player = AimdkPcmPlayer()
    try:
        await player.begin()
        try:
            await player.write(pcm)
        finally:
            await player.end()
        print("已发布测试语音并释放音频焦点；请核对机器人是否实际发声。", flush=True)
    finally:
        player.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--play", action="store_true",
                        help="向机器人扬声器播放；必须先确认 only_voice 生效")
    parser.add_argument("--speaker", default=os.environ.get(
        "DOUBAO_TTS_SPEAKER", "zh_female_vv_uranus_bigtts"))
    args = parser.parse_args(argv)
    key = os.environ.get("DOUBAO_SPEECH_API_KEY", "")
    if not key:
        parser.error("缺少 DOUBAO_SPEECH_API_KEY")
    if key.startswith("ark-"):
        parser.error("这里输入了火山方舟 LLM Key；请使用豆包语音控制台的 API Key")
    if args.play and os.environ.get("X2_ONLY_VOICE_CONFIRMED") != "1":
        parser.error("播放前须确认 only_voice 已生效，并设置 X2_ONLY_VOICE_CONFIRMED=1")
    try:
        pcm = asyncio.run(synthesize(key, args.speaker))
        if args.play:
            asyncio.run(play(pcm))
        else:
            print("本次只验证云端 TTS，没有请求机器人音频焦点或扬声器。")
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            raise SystemExit("云 TTS 握手 HTTP %s；请核对豆包语音 Key 和 TTS 服务权限" %
                             status) from exc
        raise SystemExit("TTS/播放探针失败：%s: %s" %
                         (type(exc).__name__, exc)) from exc


if __name__ == "__main__":
    main()
