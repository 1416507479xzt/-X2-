# 灵犀 X2 真机音频验收状态

更新于 2026-11-08。以下只适用于手头一台 X2 Ultra，不代表赛方统一提供的机器人已通过验收。当天完整操作、错误与解决办法见[真机联调记录](2026-11-08-x2-real-robot-integration.md)；从新电脑部署见[复现指南](reproduce-on-x2.md)。

| 环节 | 本机结果 | 证据或边界 |
|---|---|---|
| PC2 环境 | 已通过 | Linux aarch64、Python 3.10.12、ROS 2 Humble、AimDK `v1.0.0-ga424add`；加载 `/home/agi/aimdk/install/local_setup.bash` 后接口可用 |
| 内置麦 PCM | 已通过 | `/agent/process_audio_output`、`stream_id=1`；60 秒探针收到 7 段完整非空语音，VAD 为 1/2/3 |
| 云端 ASR | 链路通过，唤醒未通过 | 普通短句曾识别为“你好啊。”；完整 Agent 的多段 ASR 返回无关文本或空文本。另一次隔离探针在用户未说话时收到了 1.96 秒 PCM，ASR 为空，提示存在背景声或 VAD 误触发 |
| 离线依赖 | 已通过 | 补齐 Python 3.10 的 `exceptiongroup`、`typing-extensions` 后，真机 `robot_preflight.py` 通过 |
| 云端 TTS | 已通过 | PC2 生成约 3 秒 PCM，首包约 0.7–0.9 秒；必须使用豆包语音 Key |
| 扬声器和焦点 | 单句已通过 | 焦点优先级 6；实机完整播出测试句，程序确认释放焦点。优先级 4 被拒 |
| `only_voice` 与 `normal` | 两个方向均通过行为核对 | PC2 设置模式，PC3 重启 `agent`；切换后原生问答停止，恢复后重新回答“现在几点”。当前为 `normal` |
| 完整自研对话 | 未通过 | Agent 已运行并处理麦克风 ASR，但唤醒词没有被准确转写；因此未进入 Mini 推理或回答 |
| 表情、动作、赛方机器人 | 未验收 | 今天没有完成相关真机测试；v1.1.0 仅做静态适配 |

当前首要工作是在**下一次获准切换 `only_voice` 后**，用 `scripts/aimdk_asr_diagnostic.py` 对照安静环境与明确说话的 VAD 音频时长、音量和转写，辨别收音、VAD 与云端识别问题。不能把这次的“机器人没反应”归因于 Mini 回答质量。随后验证完整语音链路、表情动作，并在赛方机器上重新预检。

真机入口 `scripts/run_robot_agent.py` 复用 `x2_agent/agent.py` 的对话逻辑；`aimdk_audio.py`、`aimdk_transport.py`、`aimdk_playback.py` 负责输入、事件适配和播音。离线包只解压在用户目录，不修改机载 AimDK 或系统 Python。IP 随 Wi-Fi 变化，API Key 不进入 Git 或离线包。
