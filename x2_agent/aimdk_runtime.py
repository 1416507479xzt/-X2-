"""Known AimDK audio profiles; reject unverified SDK versions safely."""

from dataclasses import dataclass
from pathlib import Path
import re


VERSION_FILE = Path("/home/agi/aimdk/version")


@dataclass(frozen=True)
class AudioProfile:
    version: str
    built_in_mic_stream_id: int


PROFILES = {
    "1.0.0": AudioProfile("1.0.0", 1),
    "1.1.0": AudioProfile("1.1.0", 0),
}


def profile_from_version(version_text):
    match = re.search(r"\baimdk\s+v(\d+\.\d+\.\d+)\b", version_text, re.I)
    if not match:
        raise ValueError("无法从机载 version 文件识别 AimDK 版本")
    version = match.group(1)
    if version not in PROFILES:
        raise ValueError("未验证的 AimDK %s；停止真机音频，先核对现场接口" % version)
    return PROFILES[version]


def detect_profile(version_file=VERSION_FILE):
    try:
        text = Path(version_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("找不到机载 AimDK version 文件") from exc
    return profile_from_version(text)


def verify_audio_interfaces(processed_audio_type, playback_type,
                            request_focus_type, abandon_focus_type):
    """Read-only message shape check before making a ROS publisher or client."""
    checks = [
        (processed_audio_type, {"stream_id", "audio_vad_state", "audio_data"}),
        (playback_type, {"stamps", "info", "data", "pkg_name", "token_id"}),
        (request_focus_type.Request, {"request", "focus_requester"}),
        (request_focus_type.Response, {"reponse", "focus_response"}),
        (abandon_focus_type.Request, {"request", "focus_requester"}),
        (abandon_focus_type.Response, {"reponse", "focus_response"}),
    ]
    for ros_type, required in checks:
        actual = set(ros_type.get_fields_and_field_types())
        missing = required - actual
        if missing:
            raise ValueError("ROS 接口 %s 缺字段：%s" %
                             (ros_type.__name__, ", ".join(sorted(missing))))
