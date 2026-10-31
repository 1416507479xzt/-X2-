"""Read-only AimDK v1.0.0 microphone probe. No audio files or robot writes."""

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from x2_agent.aimdk_audio import VadAssembler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60,
                        help="Seconds to listen, default 60")
    parser.add_argument("--stream-id", type=int, default=1,
                        help="AimDK v1.0.0 onboard microphone ID, default 1")
    args = parser.parse_args(argv)
    if args.duration <= 0:
        parser.error("--duration must be positive")

    try:
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from aimdk_msgs.msg import ProcessedAudioOutput
    except ImportError as exc:
        raise SystemExit("请先 source /home/agi/aimdk/install/local_setup.bash") from exc

    assembler = VadAssembler(stream_id=args.stream_id)
    counters = {"begin": 0, "processing": 0, "end": 0, "complete": 0,
                "nonempty": 0, "other_stream": 0}
    rclpy.init()
    node = rclpy.create_node("eldercare_aimdk_mic_probe")
    qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.VOLATILE)

    def on_audio(msg):
        if msg.stream_id != args.stream_id:
            counters["other_stream"] += 1
            return
        state = msg.audio_vad_state.value
        if state == 1:
            counters["begin"] += 1
            print("VAD BEGIN", flush=True)
        elif state == 2:
            counters["processing"] += 1
        elif state == 3:
            counters["end"] += 1
        if msg.audio_data:
            counters["nonempty"] += 1
        utterance = assembler.feed(msg.stream_id, state, msg.audio_data)
        if utterance is not None:
            counters["complete"] += 1
            print("VAD END: packets=%d, pcm_bytes=%d, audio=%.2fs, wall=%.2fs" %
                  (utterance.packet_count, len(utterance.pcm),
                   utterance.audio_seconds, utterance.elapsed_seconds), flush=True)

    node.create_subscription(ProcessedAudioOutput, "/agent/process_audio_output",
                             on_audio, qos)
    print("只读监听 %ss，stream_id=%s；请使用机器人原生唤醒词后说一句话。" %
          (args.duration, args.stream_id), flush=True)
    deadline = time.monotonic() + args.duration
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=min(0.2, max(0.0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    print("统计：%s；超长丢弃=%d" % (counters, assembler.discarded))
    if counters["complete"] and counters["nonempty"]:
        print("已验证收到完整非空 PCM；未测试 ASR、扬声器或对话链路。")
    else:
        print("尚未验证完整非空 PCM；检查原生唤醒、stream_id 和 ROS 环境。")


if __name__ == "__main__":
    main()
