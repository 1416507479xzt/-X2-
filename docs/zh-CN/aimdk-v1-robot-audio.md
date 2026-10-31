# 灵犀 X2 真机音频接入进度（机载 AimDK v1.0.0）

机上已核实 SDK 为 `aimdk v1.0.0-ga424add`。`/agent/process_audio_output` 的 VAD 状态 1、2、3 和非空 `audio_data` 已在实时订阅中出现，机器人原生交互也有回应。尚未将 ASR、模型、TTS 端到端接管真机。电脑上的 v1.1.0 SDK 不应覆盖机载 v1.0.0。

**2026-10-30 实测更新：**机上只读探针监听 60 秒，共收到 8 次 BEGIN、7 次 END、7 段完整非空 PCM，`other_stream=0`、`超长丢弃=0`。例如一段为 119040 字节（按 16 kHz 单声道 S16LE 约 3.72 秒）。一次 BEGIN 被下一次 BEGIN 取代，不能据此断言丢失了完整话语；需要结合 ASR 再确认。真机 PCM 输入已验证，云端识别、真机播报及连续对话仍未验证。

## 本次新增代码

- `x2_agent/aimdk_audio.py`：以机载 v1.0.0 的内置麦 `stream_id=1` 为默认值，按 BEGIN、PROCESSING、END 拼接有长度限制的 16 kHz 单声道 S16LE PCM；丢弃超长段时不把尾音误当下一句。
- `scripts/aimdk_mic_probe.py`：仅订阅 ROS 话题，打印 VAD 统计和字节长度，不保存或播出语音，不控制机器人模式。
- `x2_agent/aimdk_playback.py`：真机输出适配器。申请音频焦点，检查是否获准，然后按 16 kHz、单声道、S16LE PCM 向 `/aima/hal/audio/playback` 发布，结束后用相同的来源和优先级释放焦点。代码不会自动运行或切换 `only_voice`。
- `x2_agent/aimdk_transport.py`：把一段 ROS VAD PCM 转成现有 Agent 接受的 `start/append/commit` 帧，并将 Agent 的 TTS PCM 送至播放适配器。环节一、二、四共用原来的对话主流程。真机语音需显式选择 `--transport aimdk --enable-robot-audio --competition-mode`，表情动作可先设 `--presentation-backend none` 做语音测试；完整演示再设 `--presentation-backend aimdk --enable-robot-presentation`。默认仍是 Unity。这些组合尚未在真机运行，不等于已验收。
- `scripts/aimdk_asr_probe.py`：下一步只读联调。仅收一段完整语音，用现有 `asr_transcribe` 请求豆包语音识别；不在机器人上保存音频或密钥，不请求焦点、不播放、不切换模式。需要从当前 SSH 会话临时提供 `DOUBAO_SPEECH_API_KEY`，且 PC2 的 Python 环境要有 `websockets` 依赖。

机上实测 `python3 -c 'import websockets'` 返回 `ModuleNotFoundError`。项目的 `requirements-lock.txt` 固定 `websockets==14.1`。为避免改变机载系统 Python，可在 `/home/agi/eldercare-probe/.venv` 创建使用系统 ROS 包的独立虚拟环境，并仅向此环境安装 `websockets==14.1`：

```bash
source /home/agi/aimdk/install/local_setup.bash
python3 -m venv --system-site-packages /home/agi/eldercare-probe/.venv
/home/agi/eldercare-probe/.venv/bin/python -m pip install --no-cache-dir websockets==14.1
/home/agi/eldercare-probe/.venv/bin/python -c 'import rclpy, aimdk_msgs, websockets; print(websockets.__version__)'
```

此处只是准备环境，不会启动机器人节点。若 `venv`、`pip` 或网络连接失败，记录原始报错后再处理，不要改装机载 `/home/agi/aimdk`。

## 下一次只读机上验证

在电脑 PowerShell 进入参赛源码根目录后，将三个必要文件复制到 PC2。下面命令只在 `/home/agi/eldercare-probe` 下建目录和复制文件，不操作机载 SDK：

```powershell
ssh agi@192.168.0.111 'mkdir -p /home/agi/eldercare-probe/x2_agent /home/agi/eldercare-probe/scripts'
scp x2_agent/__init__.py x2_agent/aimdk_audio.py agi@192.168.0.111:/home/agi/eldercare-probe/x2_agent/
scp scripts/aimdk_mic_probe.py agi@192.168.0.111:/home/agi/eldercare-probe/scripts/
```

在机器人 SSH 终端执行：

```bash
source /home/agi/aimdk/install/local_setup.bash
cd /home/agi/eldercare-probe
python3 scripts/aimdk_mic_probe.py --duration 60 --stream-id 1
```

在 60 秒内使用机器人原生唤醒词并说一句完整的话。期望看到 `VAD BEGIN`，接着 `VAD END` 的 `pcm_bytes` 大于零，`complete` 和 `nonempty` 也大于零。此时只说明 PCM 接入正确；识别准确率、播放效果和对话连续性还需要另测。输出中不包含实际语音内容，可以直接反馈用于联调。

## 后续接入边界

仿真模式继续使用 Unity WebSocket 网关。真机音频输入输出将作为单独适配层接到同一套 ASR、模型、提醒资料和食堂意见业务逻辑。现场切换 `only_voice` 及恢复 `normal` 之前，先完成适配、测试和现场操作步骤核对。播放类已准备，但未在真机上调用；不能把“焦点服务存在”误写成“已播报成功”。

当前真机适配先缓存完整 VAD 语音片段，再送入现有 ASR，因而不是最低延迟方案。接下来应在不接管扬声器的条件下核对该 PCM 的 ASR 内容和唤醒词，再检查播放焦点及原生交互切换，最后评估流式收音优化。现阶段不要把上述完整 Agent 启动参数直接用于现场演示。
