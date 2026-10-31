"""Read one AimDK VAD utterance and send only that PCM to the existing ASR.

No robot service calls, audio playback, mode changes, or audio file writes.
The speech API key is read from the process environment and never printed.
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from x2_agent.aimdk_audio import VadAssembler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--stream-id", type=int, default=1)
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.stream_id < 0:
        parser.error("duration must be positive and stream-id nonnegative")
    speech_key = os.environ.get("DOUBAO_SPEECH_API_KEY", "")
    if not speech_key:
        raise SystemExit("缺少 DOUBAO_SPEECH_API_KEY 环境变量；没有调用机器人或云端")
    resource_id = os.environ.get("DOUBAO_ASR_RESOURCE_ID", "volc.seedasr.sauc.duration")

    try:
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from aimdk_msgs.msg import ProcessedAudioOutput
        from x2_agent.asr import asr_transcribe
    except ImportError as exc:
        raise SystemExit("缺少机载 AimDK 环境或 Python websockets 依赖：%s" % exc) from exc

    rclpy.init()
    node = rclpy.create_node("eldercare_asr_probe")
    collector = VadAssembler(stream_id=args.stream_id)
    utterance = None
    qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.VOLATILE)

    def on_audio(msg):
        nonlocal utterance
        if utterance is not None:
            return
        segment = collector.feed(msg.stream_id, msg.audio_vad_state.value, msg.audio_data)
        if segment is not None and segment.pcm:
            utterance = segment

    node.create_subscription(ProcessedAudioOutput, "/agent/process_audio_output",
                             on_audio, qos)
    print("等待一段完整语音，最多 %.0f 秒；请使用原生唤醒词后说话。" % args.duration,
          flush=True)
    deadline = time.monotonic() + args.duration
    try:
        while rclpy.ok() and utterance is None and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    if utterance is None:
        print("没有收到完整非空语音；未请求云端 ASR。")
        return
    print("收到 %.2f 秒 PCM，正在调用现有 ASR；不会保存录音。" %
          utterance.audio_seconds, flush=True)
    try:
        recognized = asyncio.run(asr_transcribe(utterance.pcm, speech_key, resource_id))
    except Exception as exc:
        raise SystemExit("ASR 失败：%s: %s" % (type(exc).__name__, exc)) from exc
    print("ASR 识别结果：%s" % (recognized or "<空>"))


if __name__ == "__main__":
    main()
