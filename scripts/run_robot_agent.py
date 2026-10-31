"""Load bundled Linux dependencies and start the shared Agent on X2 PC2.

Requires deliberate confirmation that native interaction has been switched
to only_voice. This file never changes that mode itself.
"""

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get("X2_ONLY_VOICE_CONFIRMED") != "1":
        raise SystemExit("未确认机器人已按官方流程切换到 only_voice；拒绝启动真机语音输出")
    if "--transport" not in sys.argv or "aimdk" not in sys.argv:
        raise SystemExit("此入口只用于 --transport aimdk")
    from x2_agent.agent import main as agent_main
    agent_main()


if __name__ == "__main__":
    main()
