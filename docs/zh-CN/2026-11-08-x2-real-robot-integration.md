# 2026-11-08 灵犀 X2 真机接入联调记录

本记录面向后续接手项目的同学，按实测顺序记下环境、操作、错误、修复和验收边界。测试对象是手头一台 **X2 Ultra**，并非省赛现场统一提供的机器人。当前机器人 Wi-Fi IP 会变化，本文不把某次连接地址写成固定配置；部署时从机器人信息页或 `ip -4 -br addr show wifi0` 获取当前地址。

## 当天目标与架构

目标是让真机使用仿真中同一套迎宾问询、生活协助和食堂意见对话逻辑。真机只替换输入输出适配层：PC2 上的 AimDK/ROS 话题提供内置麦 PCM，豆包语音服务完成 ASR 和 TTS，火山方舟的 `doubao-seed-2-0-mini-260428` 负责对话，AimDK 音频焦点和播放话题驱动机器人扬声器。表情和预设动作尚未进入今天的真机验收。灵创健康操属于独立的环节三作品。

`x2_agent/agent.py` 是共用对话调度；`aimdk_audio.py`、`aimdk_transport.py`、`aimdk_playback.py` 是真机音频适配层。不能把“仿真业务逻辑共用”写成“赛方机器人零修改运行已验证”。

## 环境与接口实测

| 项目 | 2026-11-08 实测 |
|---|---|
| 机器人 | X2 Ultra，PC2 为 Linux aarch64、Python 3.10.12、ROS 2 Humble |
| AimDK | `/home/agi/aimdk/version` 为 `aimdk v1.0.0-ga424add`；新 SSH 终端须先 `source /home/agi/aimdk/install/local_setup.bash` |
| 内置麦 | `/agent/process_audio_output`，`aimdk_msgs/msg/ProcessedAudioOutput`，内置麦 `stream_id=1`；VAD BEGIN=1、PROCESSING=2、END=3 |
| 麦克风订阅 | `BEST_EFFORT + VOLATILE`；只读探针曾在 60 秒内收取 7 段完整非空 PCM |
| 扬声器 | `/aima/hal/audio/playback`，`aimdk_msgs/msg/AudioPlayback`；订阅者存在，`RELIABLE + VOLATILE` |
| 音频焦点 | `RequestAudioFocus`、`AbandonAudioFocus` 服务存在；本机优先级 4 被拒，优先级 6 成功播放 |
| 交互模块 | PC2 的 `aima em list-apps` 没有 `agent`；从 PC2 通过机器人内部网络登录 PC3 后，`aima em list-apps` 有 `agent` |
| 云端 ASR | 单句探针曾把内置麦 PCM 识别为“你好啊。”；云端链路可用，但后续唤醒词识别质量未通过 |
| 云端 TTS | 正确语音 Key 下 PC2 合成约 3 秒 PCM，首包约 0.7–0.9 秒 |

官方接口说明：[音频播放与焦点](https://x2-aimdk.agibot.com/zh-cn/latest/Interface/interactor/voice.html)；[原生 Agent 的 `only_voice` 过渡方案](https://x2-aimdk.agibot.com/zh-cn/latest/faq/temp_works.html#agent-only-voice)。下面的模式操作均先在这台实机验证，不能直接推定赛方机器的权限与版本相同。

## 按顺序完成的操作和问题

### 1. 离线包和预检

在 Windows 开发电脑构建 Linux aarch64 / Python 3.10 离线包 `dist/eldercare_x2_aarch64_py310.zip`，通过 SSH/SCP 复制到机器人用户目录 `/home/agi/eldercare-x2/`，在 PC2 解压后运行 `scripts/robot_preflight.py`。包只写入用户目录，未安装进系统 Python，也未修改机载 AimDK。

第一次完整 Agent 启动虽然旧版预检通过，但 `httpx/httpcore` 报：

```text
RuntimeError: Running with asyncio requires installation of 'httpcore[asyncio]'.
```

原因是跨平台打包时漏掉了 Python 3.10 所需的 `exceptiongroup`、`typing-extensions`。修复：将两项固定在 `requirements-lock.txt`，加入离线包校验，并让预检显式导入 `httpcore`、`anyio`、`sniffio`、`exceptiongroup` 和 `typing_extensions`。重建、复制并解压后，**真机预检已通过**，显示 `httpcore 1.0.6`、`exceptiongroup 1.2.2` 和其余依赖可导入。此错误发生于模型请求前，不能解释为 Mini 模型回答失败。

### 2. 两把 Key 的用途

豆包语音 API Key 用于 ASR/TTS；方舟 API Key 用于 Mini 的 LLM。曾误把方舟 Key 输入 TTS 探针，得到 HTTP 401；改用正确语音 Key 后，云端 TTS 成功。ASR 探针也曾在显式设置不匹配资源 ID 时返回 HTTP 403；去掉覆盖、使用项目当前的 `volc.seedasr.sauc.duration` 后，单句 ASR 成功。**不要用字符长度当作授权校验，也不要把 Key、`.env` 或终端密钥输入记录提交到 Git。**

### 3. 原生交互模式和 PC3

切换前，不运行自研程序时机器人能用原生交互回答“现在几点”。先在已加载 AimDK 的 PC2 调用 `SetAgentPropertiesRequest`，将 `AGENT_PROPERTY_RUN_MODE=2` 的值设为 `only_voice`；然后从 PC2 登录内部 PC3，在 **PC3** 执行 `aima em stop-app agent`、`aima em start-app agent`，两条命令返回成功。切换后相同原生问答不再回答，说明本机行为符合预期。服务设置响应本身为 `code=0, status=0 (UNKNOWN)`，不能单凭它判定成功；必须核对行为。

PC2 的 `aima em stop-app agent` 不适用，因为该应用不在 PC2 列表。未加载 AimDK 的新 SSH 终端运行 `ros2 service call` 会显示服务类型无效，先 `source` 环境。**21:49 左右已实测恢复 `normal`：**停止自研程序后，在 PC2 设置 `normal`，PC3 的 `stop-app agent`、`start-app agent` 均成功；随后机器人重新用原生语音回答“现在几点”。当前机器人处于原生交互可用状态。以后再次切换仍须按完整流程操作并核对行为。

### 4. 云端 TTS、扬声器和音频焦点

`scripts/aimdk_tts_probe.py` 先只在内存中合成短句，确认云端成功后才在显式 `--play` 和 `X2_ONLY_VOICE_CONFIRMED=1` 条件下播音。优先级 4 的焦点请求被拒，不曾发布音频；按官方默认级别改为 **6** 后，机器人完整播出“您好，我是灵犀，今天感觉怎么样？”。

首次播出后程序在释放焦点时报错。实机发现第一次 `AbandonAudioFocus` 可能返回 `status=1, focus_gain=true`，同标识再请求一次才返回 `status=1, focus_gain=false`。因此实现最多一次同参数重试，直到收到确认释放；不以 `status=1` 单独推断焦点已释放。新建 ROS 客户端还遇到 DDS 服务发现短暂未就绪，加入最多 3 秒有限等待。修复后探针打印“已发布测试语音并释放音频焦点”，现场确认测试句**完整播出**。这只证明单句播音链路，不证明完整 Agent 已可对话。

### 5. 完整 Agent：依赖通过，唤醒未通过

更新离线包后，完整 Agent 在 PC2 启动，预检通过，显示 `AimDK 1.0.0 音频传输，麦流=1`、`state=online`、`audioActive=true`，并等待语音唤醒。多段内置麦 PCM 被提交到豆包 ASR，连接通常约 0.2 秒，整句识别约 0.7–1.9 秒。实际结果包括“今天张馨予有更新微博吗？”、“喝喝多少啊？”、“坏了，没反应啊。”及空文本；均未命中“灵犀”或“你好灵犀”的唤醒判定，因此 Agent **没有进入问候、Mini 推理或 TTS 播放**。用户观察到机器人没有反应，与日志一致。

隔离探针随后在用户**没有说话**时收到 1.96 秒 PCM，云端 ASR 返回空文本。这证明至少存在背景声或 VAD 误触发，先前无关转写也不能直接归因于用户说话或唤醒匹配规则。新增 `scripts/aimdk_asr_diagnostic.py`，在同一 ROS 订阅会话中依次打印多段音频时长、RMS/峰值和 ASR 文本，不保存录音；等待现场对照“安静→明确说话”的结果。不能把无关转写强行映射为唤醒词。唤醒准确后再测大模型与多轮对话。

### 6. Ctrl+C 退出异常

本轮 Agent 按 Ctrl+C 时，`rclpy` 已处理 SIGINT 并关闭 ROS 上下文；播放适配层又调用一次 `rclpy.shutdown()`，产生 `RCLError: rcl_shutdown already called`。已在 `AimdkPcmPlayer.close()` 加 `rclpy.ok()` 判断，并增加离线回归测试。**这项修复尚待复制到机器人后复测**；它与前述唤醒失败是两个独立问题。

## 当前验收结论与下一步

已实测：AimDK v1.0.0 内置麦 PCM、一次普通短句 ASR、PC2 云 TTS、优先级 6 的完整扬声器播报与焦点释放、修复版离线依赖预检、`only_voice` 行为切换，以及返回 `normal` 后的原生问答恢复。尚未实测通过：真机唤醒词、完整 ASR→Mini→TTS 对话、表情与动作、多环节连续演示、赛方统一机器兼容性。当前应保持原生交互，下一次自研语音联调前再按官方步骤切换。

完整从新电脑部署步骤见[复现指南](reproduce-on-x2.md)；实时状态摘要见[真机音频验收表](aimdk-v1-robot-audio.md)。历史 IP、SSH 密码和 API Key 均不属于可复现配置，交接时应由新操作者在现场获取。
