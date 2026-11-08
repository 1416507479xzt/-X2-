"""Compare several real X2 VAD segments without saving or playing audio.

Run only on the robot PC2 after loading its AimDK ROS environment. This
diagnostic does not change interaction mode or call robot control services.
"""

import argparse
import array
import asyncio
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from x2_agent.aimdk_audio import VadAssembler


def pcm_levels(pcm):
    samples = array.array("h")
    samples.frombytes(pcm[:len(pcm) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0, 0
    peak = max(abs(value) for value in samples)
    rms = int((sum(value * value for value in samples) / len(samples)) ** 0.5)
    return rms, peak


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60,
                        help="overall listening limit in seconds")
    parser.add_argument("--count", type=int, default=4,
                        help="maximum VAD segments to inspect")
    parser.add_argument("--stream-id", type=int, default=1)
    args = parser.parse_args(argv)
    if args.duration <= 0 or args.count < 1 or args.count > 10 or args.stream_id < 0:
        parser.error("duration must be positive; count 1..10; stream-id nonnegative")
    speech_key = os.environ.get("DOUBAO_SPEECH_API_KEY", "")
    if not speech_key:
        raise SystemExit("缺少 DOUBAO_SPEECH_API_KEY；未订阅麦克风")

    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from aimdk_msgs.msg import ProcessedAudioOutput
    from x2_agent.asr import asr_transcribe

    collector = VadAssembler(stream_id=args.stream_id)
    pending = []
    rclpy.init()
    node = rclpy.create_node("eldercare_asr_diagnostic")
    qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.VOLATILE)

    def on_audio(msg):
        segment = collector.feed(msg.stream_id, msg.audio_vad_state.value, msg.audio_data)
        if segment is not None and segment.pcm:
            pending.append(segment)

    node.create_subscription(ProcessedAudioOutput, "/agent/process_audio_output",
                             on_audio, qos)
    resource_id = os.environ.get("DOUBAO_ASR_RESOURCE_ID",
                                 "volc.seedasr.sauc.duration")
    deadline = time.monotonic() + args.duration
    print("只读监听最多 %.0f 秒、最多 %d 段；不保存录音。" %
          (args.duration, args.count), flush=True)
    try:
        for index in range(1, args.count + 1):
            print("等待第 %d 段语音；看到此行后再说话。" % index, flush=True)
            while rclpy.ok() and not pending and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
            if not pending:
                print("到时或 ROS 已停止；本次没有更多完整 VAD 片段。", flush=True)
                break
            segment = pending.pop(0)
            rms, peak = pcm_levels(segment.pcm)
            print("第 %d 段：%.2f 秒，%d 包，RMS=%d，峰值=%d" %
                  (index, segment.audio_seconds, segment.packet_count, rms, peak),
                  flush=True)
            try:
                result = asyncio.run(asr_transcribe(segment.pcm, speech_key, resource_id))
                print("第 %d 段 ASR：%s" % (index, result or "<空>"), flush=True)
            except Exception as exc:
                print("第 %d 段 ASR 错误：%s: %s" %
                      (index, type(exc).__name__, exc), flush=True)
    except KeyboardInterrupt:
        print("用户停止诊断。", flush=True)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
