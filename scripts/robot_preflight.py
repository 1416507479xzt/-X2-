"""Read-only compatibility check for a competition-provided X2 PC2."""

import importlib
import platform
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))


def main():
    problems = []
    if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
        problems.append("requires Linux aarch64")
    if sys.version_info[:2] != (3, 10):
        problems.append("requires CPython 3.10")
    version_path = Path("/home/agi/aimdk/version")
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "missing"
    try:
        from x2_agent.aimdk_runtime import profile_from_version, verify_audio_interfaces
        profile = profile_from_version(version)
        print("Known audio profile=%s, built-in mic stream_id=%s" %
              (profile.version, profile.built_in_mic_stream_id))
    except ValueError as exc:
        problems.append(str(exc))
    print("OS=%s machine=%s Python=%s AimDK=%s" %
          (platform.system(), platform.machine(), platform.python_version(), version))
    for module in ("rclpy", "aimdk_msgs", "websockets", "httpx", "httpcore",
                   "anyio", "sniffio", "exceptiongroup", "typing_extensions",
                   "yaml", "pypinyin"):
        try:
            imported = importlib.import_module(module)
            print(module, getattr(imported, "__version__", "import OK"))
        except Exception as exc:
            problems.append(module + ": " + type(exc).__name__ + ": " + str(exc))
    if not problems:
        try:
            from aimdk_msgs.msg import ProcessedAudioOutput, AudioPlayback, FocusResponse
            from aimdk_msgs.srv import RequestAudioFocus, AbandonAudioFocus
            verify_audio_interfaces(ProcessedAudioOutput, AudioPlayback,
                                    RequestAudioFocus, AbandonAudioFocus)
            focus_fields = set(FocusResponse.get_fields_and_field_types())
            if not {"pkg_name", "focus_gain"} <= focus_fields:
                raise ValueError("ROS FocusResponse 缺少 pkg_name 或 focus_gain")
            print("ROS audio message/service fields OK")
        except Exception as exc:
            problems.append("ROS audio interface: " + str(exc))
    if problems:
        print("不兼容：" + "; ".join(problems))
        return 1
    print("依赖和版本预检通过；没有测试 ROS 音频、网络服务或机器人动作。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
