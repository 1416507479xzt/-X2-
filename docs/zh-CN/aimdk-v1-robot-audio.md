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
| 单句云端 TTS | 2026-11-08 开发电脑首包约 0.84 秒、机器人 PC2 首包约 0.77 秒，均收到约 3.00 秒的 16 kHz PCM | 已验证 PC2 到豆包 TTS 的云端链路；尚未在真机验证音频焦点或扬声器 |
| 真机 TTS 首次握手 | 首次在机器人终端误输入 46 位方舟 LLM Key，TTS 返回 HTTP 401；电脑端成功使用的豆包语音 Key 为 36 位 | 是凭据类别错误，不能据此判断机载网络或扬声器有故障；已在探针加入 `ark-` 前缀识别 |
| `only_voice` 真机切换 | PC2 设置模式后，登录 PC3 停止并启动 `agent` 均返回成功；切换前原生问时会回答，切换后不再回答 | 官方过渡流程在这台机器人上初步生效；恢复 `normal` 仍待实测 |
| 首次扬声器探针 | PC2 云 TTS 首包约 0.89 秒，PCM 约 3.01 秒；音频焦点优先级 4 被拒，未发布 PCM | 这不是 TTS 失败；需按[官方音频焦点规则](https://x2-aimdk.agibot.com/zh-cn/latest/Interface/interactor/voice.html)核对焦点响应并有限调整优先级，不能直接向话题推音频 |
| 优先级 6 播放 | 云 TTS 首包约 0.72 秒，PCM 约 2.99 秒；机器人完整播出测试句。探针结束时报告焦点关闭错误，手动调用同标识的 `AbandonAudioFocus` 得到 `status=1, focus_gain=false` | 播放链路已验证；程序自动释放焦点尚需修复和复测。正式 Agent 的播放优先级改为 6，未提高到系统安全播报等级 |
| 首次释放响应 | 更新诊断后重复短句探针，第一次 `AbandonAudioFocus` 返回 `status=1, focus_gain=true` | 不能仅凭 `status=1` 判定释放；已加入最多一次同参数重试，等待 `focus_gain=false` 的真机复测 |
| ROS 服务发现竞态 | 更新释放逻辑后的首次重测，在新建 ROS 客户端后立即报“音频焦点服务未就绪”，没有播音 | 服务在 ROS 图中存在；客户端启动时须有限等待 DDS 发现。代码已加入最长 3 秒等待，待真机复测 |
| 播放接口 | `/aima/hal/audio/playback` 类型为 `aimdk_msgs/msg/AudioPlayback`；音频焦点服务存在 | 仅确认消息与服务定义，尚未验证声音实际播出 |
| 原生交互模式接口 | `/aimdk_5Fmsgs/srv/SetAgentPropertiesRequest` 存在；`contents.properties[].key.value` 中 `AGENT_PROPERTY_RUN_MODE=0x02`，值为字符串 | 已分别发送 `only_voice` 和 `normal` 请求，但没有通过交互模块重启及实际行为证实模式生效或恢复 |
| 模式设置响应与查询 | 已发送 `only_voice` 请求，响应 `header.code=0`、`status.value=0 (UNKNOWN)`；`GetAgentPropertiesRequest` 服务在 ROS 图中存在，但机载 SDK 缺少其 `.idl` 和 Python 类型 | 不能凭该响应断言模式已生效，也无法用现有 ROS CLI 直接读取；下一步重启后按实际行为核对，并准备 `normal` 恢复 |
| PC2 与 PC3 的应用位置 | 新 SSH 会话未加载 AimDK 时 `ros2 service call` 返回 `The passed service type is invalid`；PC2 的 `aima em` 应用列表没有 `agent`。2026-11-08 从 PC2 经机器人内部网络 SSH 到 PC3，`aima em list-apps` 确认其中有 `agent` | 模式属性服务在已 source AimDK 的 PC2 调用；官方要求的 `agent` 重启应在 PC3 执行。重启和模式生效尚未实测 |
| 当前原生交互 | 2026-11-08 机器人重启后，不运行自研 Agent，原生唤醒并询问时间会语音回答 | 当前仍能使用原生交互；这是切换前的行为基线 |

一次 BEGIN 后又收到 BEGIN，不能据此断言完整话语丢失。单句 ASR 已能返回文本；尚未系统测试不同说话方式的准确率。机上系统 Python 缺少 `websockets`；当前离线包把所需版本放在 `vendor/`，不修改系统 Python 或机载 AimDK。

## 代码对应关系

- `x2_agent/aimdk_audio.py`：将 VAD 消息拼成有限长的 PCM 片段。
- `x2_agent/aimdk_transport.py`：把 AimDK 音频接到仿真时共用的 Agent 对话事件接口。
- `x2_agent/aimdk_playback.py`：申请音频焦点、发布 PCM、释放焦点；仅完成代码与离线测试，未真机播放。
- `x2_agent/aimdk_runtime.py`：按机载版本选择内置麦编号并核对音频接口。v1.0.0 的编号 1 已实测；v1.1.0 的编号 0 只依据官方文档静态适配。
- `scripts/aimdk_mic_probe.py`、`scripts/aimdk_asr_probe.py`：分别做只读 PCM 检查和单句云端转写，两者均已在手头真机运行。
- `scripts/aimdk_tts_probe.py`：默认只在内存中合成短句 PCM；显式 `--play` 且确认 `only_voice` 后才请求音频焦点并播出。云端合成已在开发电脑验证，真机播出待验收。
- `scripts/robot_preflight.py`：只读检查系统、依赖和 ROS 音频字段。

## 仍需逐项验证

1. `only_voice` 已在手头机器人上完成切换并通过原生问答停止的行为验证。停止自研程序后按官方顺序在 PC2 设置 `normal`，再到 PC3 重启 `agent`，以原生语音回答验证恢复；此恢复步骤待实测。
2. 测试同一套业务代码的 ASR→大模型→TTS 完整语音对话，再测试表情和预设动作及异常恢复。
3. 获取赛方机器人后先运行预检。未知版本、架构或字段不兼容时停止，不绕过检查直接运行。

**当前结论：**已实测手头真机的麦克风 PCM 输入、一次豆包语音 ASR 成功转写、云端 TTS 合成和优先级 6 的扬声器完整播报。播放后自动释放焦点、模型、表情动作及多环节连续演示尚未完成真机验收。仿真与真机共用业务逻辑，但还不能宣称赛方机器人零修改运行已得到验证。
