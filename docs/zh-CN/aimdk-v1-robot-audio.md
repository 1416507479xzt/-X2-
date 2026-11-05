# 灵犀 X2 真机接入：已验证事实与待验收项

本记录汇总截至 2026-11-06 在**手头的一台 X2** 上得到的结果。省赛使用组委会统一提供的机器人，其固件、SDK 版本及网络条件尚未知。记录不包含设备序列号、局域网地址或密钥。完整现场部署步骤见[赛方机器人部署方案](onsite-deployment.md)。

## 已在手头真机确认

| 项目 | 实测结果 | 能说明什么 |
|---|---|---|
| 系统 | Linux aarch64、Python 3.10.12、ROS 2 Humble | 当前离线包的架构和解释器目标与这台机器一致 |
| AimDK | `/home/agi/aimdk/version` 为 `aimdk v1.0.0-ga424add` | 必须先加载机载 `install/local_setup.bash` 才能使用 `aimdk_msgs` |
| 麦克风话题 | `/agent/process_audio_output`，类型 `aimdk_msgs/msg/ProcessedAudioOutput` | 消息有 `stream_id`、`audio_vad_state.value` 和 `audio_data` |
| 实时收音 | 内置麦 `stream_id=1`；VAD 1=BEGIN、2=PROCESSING、3=END | 只读探针能收到非空 PCM；订阅用 `BEST_EFFORT` + `VOLATILE` 避免将缓存消息当作实时结果 |
| 60 秒只读探针 | BEGIN 8 次、END 7 次、完整非空片段 7 段；其他流 0、超长丢弃 0 | 证实 PC2 可收取完整语音片段；其中一段 119040 字节，按 16 kHz 单声道 S16LE 约 3.72 秒 |
| 单句云端 ASR | 2.0 小时版 `volc.seedasr.sauc.duration`；收到 1.70 秒 PCM，WebSocket 连接约 204 ms，识别结果为“你好啊。” | 当前机载麦克风到豆包语音识别的链路可用；仍需更多语句核对准确率 |
| 播放接口 | `/aima/hal/audio/playback` 类型为 `aimdk_msgs/msg/AudioPlayback`；音频焦点服务存在 | 仅确认消息与服务定义，尚未验证声音实际播出 |
| 原生交互模式接口 | `/aimdk_5Fmsgs/srv/SetAgentPropertiesRequest` 存在；`contents.properties[].key.value` 中 `AGENT_PROPERTY_RUN_MODE=0x02`，值为字符串 | 机载 v1.0.0 字段与官方 `only_voice` 过渡步骤吻合；尚未实际切换或恢复 |
| 模式设置响应与查询 | 已发送 `only_voice` 请求，响应 `header.code=0`、`status.value=0 (UNKNOWN)`；`GetAgentPropertiesRequest` 服务在 ROS 图中存在，但机载 SDK 缺少其 `.idl` 和 Python 类型 | 不能凭该响应断言模式已生效，也无法用现有 ROS CLI 直接读取；下一步重启后按实际行为核对，并准备 `normal` 恢复 |

一次 BEGIN 后又收到 BEGIN，不能据此断言完整话语丢失。单句 ASR 已能返回文本；尚未系统测试不同说话方式的准确率。机上系统 Python 缺少 `websockets`；当前离线包把所需版本放在 `vendor/`，不修改系统 Python 或机载 AimDK。

## 代码对应关系

- `x2_agent/aimdk_audio.py`：将 VAD 消息拼成有限长的 PCM 片段。
- `x2_agent/aimdk_transport.py`：把 AimDK 音频接到仿真时共用的 Agent 对话事件接口。
- `x2_agent/aimdk_playback.py`：申请音频焦点、发布 PCM、释放焦点；仅完成代码与离线测试，未真机播放。
- `x2_agent/aimdk_runtime.py`：按机载版本选择内置麦编号并核对音频接口。v1.0.0 的编号 1 已实测；v1.1.0 的编号 0 只依据官方文档静态适配。
- `scripts/aimdk_mic_probe.py`、`scripts/aimdk_asr_probe.py`：分别做只读 PCM 检查和单句云端转写，两者均已在手头真机运行。
- `scripts/robot_preflight.py`：只读检查系统、依赖和 ROS 音频字段。

## 仍需逐项验证

1. 按已核对的机载 `SetAgentPropertiesRequest` 字段与官方步骤重启 agent，通过实际收音和原生交互行为测试 `only_voice`，并测试恢复 `normal`；再测试音频焦点和扬声器。当前只发送了设置请求，尚未重启或测试恢复。
2. 测试同一套业务代码的 ASR→大模型→TTS 完整语音对话，再测试表情和预设动作及异常恢复。
3. 获取赛方机器人后先运行预检。未知版本、架构或字段不兼容时停止，不绕过检查直接运行。

**当前结论：**已实测手头真机的麦克风 PCM 输入和一次豆包语音 ASR 成功转写；模型、TTS、表情动作及多环节连续演示尚未完成真机验收。仿真与真机共用业务逻辑，但还不能宣称赛方机器人零修改运行已得到验证。
