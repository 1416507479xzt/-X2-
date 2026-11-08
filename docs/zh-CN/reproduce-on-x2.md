# 从新电脑复现 X2 自研语音 Agent

本文对应仓库当前源码。目标是让同一套对话业务逻辑在灵犀 X2 上处理语音唤醒、连续问询、生活协助和食堂意见，并通过 AimDK 播报与表现。**截至 2026-11-08，手头 X2 已实测麦克风 PCM、单句 ASR、云端 TTS、机器人扬声器和焦点释放；完整 Agent 已接收音频，但唤醒词尚未被准确识别，完整真机对话未验收。**各环节事实见[当前验收状态](aimdk-v1-robot-audio.md)和[当天联调记录](2026-11-08-x2-real-robot-integration.md)。

## 0. 先确认目标机器

需要 X2 Ultra 的开发计算单元 PC2、可用的 SSH 账号、允许把程序复制到 PC2 并运行的权限、机载 AimDK 与 ROS 2、允许二次开发的操作权限，以及能访问豆包语音和火山方舟服务的网络。当前离线包适配 **Linux aarch64、CPython 3.10、AimDK v1.0.0/v1.1.0 的已知音频字段**；其他版本先检查接口再适配。v1.1.0 的麦流编号仅按官方文档准备，尚未实测。赛方统一机器人的配置不能根据手头 X2 推定；其他获准部署方式见[现场部署决策](onsite-deployment.md)。

## 1. 在另一台 Windows 电脑取得源码并构建

安装 Git 和 Python 3.10 或更新版本，在 PowerShell 执行：
如果仓库仍为私有，先在新电脑上完成 GitHub 登录或配置具有读取权限的 Git 凭据。

```powershell
git clone https://github.com/1416507479xzt/-X2-.git
Set-Location .\-X2-
python -m pip --version
python scripts/build_robot_bundle.py --download-wheels
python -m zipfile -t .\dist\eldercare_x2_aarch64_py310.zip
```

构建脚本在**开发电脑**下载 `requirements-lock.txt` 固定版本的 Linux aarch64 / CPython 3.10 wheel，核对名称与版本，再把运行源码和依赖放进 `dist/eldercare_x2_aarch64_py310.zip`。这一步需要开发电脑联网；真机解压后不用联网安装 Python 依赖。云端 ASR、LLM、TTS 在**运行时仍需网络**。如果 wheel 下载失败，不要把 Windows wheel 放进包里。

源码仓库不包含 `.env`、API Key、真实录音、食堂意见历史记录或 Unity 模拟器。运行时在机器人终端临时输入密钥；不要把密钥放进 Git 提交或 ZIP。

## 2. 复制到手头机器人

机器人的 Wi-Fi 地址可能在重新联网后改变。**每次部署或重新建立 SSH 连接前**，先从机器人信息页面查看当前 IP；若已经能进入机器人终端，也可运行 `ip -4 -br addr show wifi0` 核对。不要沿用历史联调记录中的地址。

在**电脑 PowerShell，仓库根目录**执行，按提示输入当次查到的地址。下面的 `agi` 和 `/home/agi` 适用于手头这台机器人，赛方机器以现场账号为准：

```powershell
$RobotIp = Read-Host '输入机器人当前 IP（每次连接前重新核对）'
if ([string]::IsNullOrWhiteSpace($RobotIp)) { throw '机器人 IP 不能为空' }
ssh "agi@${RobotIp}" 'mkdir -p /home/agi/eldercare-x2'
scp .\dist\eldercare_x2_aarch64_py310.zip "agi@${RobotIp}:/home/agi/eldercare-x2/"
ssh "agi@${RobotIp}"
```

此后提示符应为**机器人 SSH 终端**。执行：

```bash
cd /home/agi/eldercare-x2
python3 -m zipfile -e eldercare_x2_aarch64_py310.zip .
source /home/agi/aimdk/install/local_setup.bash
cd eldercare_x2
python3 scripts/robot_preflight.py
```

预检只读。它核查系统架构、Python、机载 AimDK 版本、`rclpy`、`aimdk_msgs`、离线依赖和音频字段。出现“不兼容”就记录报错并停止，不改机载 SDK。`source` 只影响当前 SSH 会话；新开终端需再次执行。

## 3. 逐层验证，保留每层结果

| 顺序 | 命令或操作 | 通过的证据 |
|---|---|---|
| 麦克风 | `python3 scripts/aimdk_mic_probe.py --duration 60 --stream-id 1`（仅已验证的 v1.0.0） | 有完整非空 PCM；这一步已在手头 X2 实测 |
| 云端识别 | 按下面的临时密钥步骤执行 `aimdk_asr_probe.py` | 手头 X2 已一次识别为“你好啊。”；更多语句准确率待测 |
| 云端合成 | `python3 scripts/aimdk_tts_probe.py`，默认不播放 | 开发电脑和手头 X2 PC2 均已得到约 3 秒 PCM |
| 自研对话 | 按第 4 节切换模式后运行完整 Agent | 能完成唤醒、上下文、回答；尚未真机实测 |
| 扬声器 | AimDK 焦点优先级 6 + PCM 话题 | 手头 X2 已完整播出探针短句并确认自动释放焦点；完整 Agent 待测 |
| 表情动作 | 语音验收后启用 AimDK 表现后端 | 表情和预设动作与回答配合、执行安全；尚未真机实测 |

单句 ASR 探针不会控制机器人模式或扬声器。在**机器人 SSH 终端**中输入密钥，输入时无回显：

```bash
read -r -s -p '豆包语音 API Key: ' DOUBAO_SPEECH_API_KEY; echo
export DOUBAO_SPEECH_API_KEY
python3 scripts/aimdk_asr_probe.py --duration 60 --stream-id 1
unset DOUBAO_SPEECH_API_KEY
```

上面的 `--stream-id 1` 仅适用于已验证的 v1.0.0；其他版本先依据预检打印的内置麦克风编号与现场消息确认后再运行。

不要把实际 API Key、带密钥的截图或真实长者的健康信息发到公开仓库。若 ASR 转写不对，先核对 PCM 流编号、说话时机、语音资源和云端错误，再进入模型联调。

若已收到 PCM，但云端 WebSocket 握手返回 `HTTP 401`，说明尚未进入识别阶段。先确认输入的是**豆包语音** API Key（不是方舟 Key），且该 Key 非空；再在豆包语音控制台核对已开通的流式语音识别版本和计费类型。本探针默认请求 2.0 小时版 `volc.seedasr.sauc.duration`。仅当控制台实际开通 1.0 小时版时，在机器人当前终端执行 `export DOUBAO_ASR_RESOURCE_ID=volc.bigasr.sauc.duration` 后重试；若开通并发版，应使用对应版本的 `*.concurrent` 资源 ID。不要通过猜测版本或更改机器人 SDK 来处理鉴权失败。结束后执行 `unset DOUBAO_ASR_RESOURCE_ID`。资源 ID 列表见[豆包语音官方接口说明](https://docs.volcengine.com/docs/doubao-voice/unidirectional-streaming-automatic-speech-recognition-websocket?lang=zh)。

2026-11-06 使用本地保存的豆包语音 Key 做**仅握手、不发送音频**的核对：`volc.seedasr.sauc.duration`（2.0 小时版）成功，`volc.bigasr.sauc.duration`（1.0 小时版）返回 `HTTP 403` 和 `requested resource not granted`。因此手头账号在当前 Key 下应使用默认的 2.0 小时版资源 ID。随后机载探针收到 1.70 秒 PCM，成功识别为“你好啊。”。

## 4. 运行完整 Agent 与恢复原生交互

自研语音系统与 X2 Ultra 原生交互会争用音频。按照**机载版本对应的官方说明**，在获得当前机器人操作权限并确认恢复流程后，切换 `only_voice`，再运行 Agent。手头 AimDK v1.0.0 机器已完成 PC2 模式设置和 PC3 `agent` 重启，并通过原生问答停止验证切换生效；恢复 `normal` 的实际行为仍待验证。官方[过渡方案](https://x2-aimdk.agibot.com/zh-cn/latest/faq/temp_works.html)给出的参考命令如下；**仅适用于 X2 Ultra，且现场机器仍须核对固件与服务定义**：

```bash
source /home/agi/aimdk/install/local_setup.bash
ros2 service call /aimdk_5Fmsgs/srv/SetAgentPropertiesRequest aimdk_msgs/srv/SetAgentPropertiesRequest "{contents: {properties: [{key: {value: 2}, value: 'only_voice'}]}}"
```

以上两行在 PC2 执行。接着登录 PC3 执行：

```bash
aima em stop-app agent
aima em start-app agent
```

`only_voice` 已在手头机器人上完成切换：PC3 重启 `agent` 成功，原生问答不再回应。恢复 `normal` 尚未实测。若切换后的收音行为不符合官方说明，先恢复原生模式并记录结果。停止自研程序后，官方恢复步骤为：

手头 v1.0.0 的 `only_voice` 设置请求曾返回 `header.code=0`、`status.value=0 (UNKNOWN)`；ROS 图虽有 `GetAgentPropertiesRequest` 服务，机载 SDK 却没有该服务的 `.idl` 和 Python 类型。因此不要仅凭返回码或脚本中的手动确认变量宣称模式已切换，需在重启后用真实收音与原生交互行为核对。下方恢复命令应在操作前备好。

**手头真机位置核对（2026-11-08）：**PC2 的 `aima em` 应用列表没有 `agent`，但从 PC2 通过机器人内部网络 SSH 到 PC3 后，`aima em list-apps` 能列出 `agent`。因此，属性服务请求在已 source AimDK 的 PC2 调用；`aima em stop-app agent` 和 `start-app agent` 应登录 PC3 执行，不能在 PC2 直接运行。PC3 内部地址与会变化的机器人 Wi-Fi 地址不同，不要把 Wi-Fi 地址写死在部署命令里。每次新开 PC2 SSH 会话，先运行 `source /home/agi/aimdk/install/local_setup.bash`，否则 `ros2 service call` 会报服务类型无效。`normal` 恢复仍待实际验证。

```bash
source /home/agi/aimdk/install/local_setup.bash
ros2 service call /aimdk_5Fmsgs/srv/SetAgentPropertiesRequest aimdk_msgs/srv/SetAgentPropertiesRequest "{contents: {properties: [{key: {value: 2}, value: 'normal'}]}}"
```

以上两行在 PC2 执行。接着登录 PC3 执行：

```bash
aima em stop-app agent
aima em start-app agent
```

在切换模式之前，也可先只验证云端 TTS，不触碰扬声器：在已导出 `DOUBAO_SPEECH_API_KEY` 的终端运行 `python3 scripts/aimdk_tts_probe.py`。仅当交互模块重启、`only_voice` 已通过实际行为确认，且已备好恢复流程时，才运行 `X2_ONLY_VOICE_CONFIRMED=1 python3 scripts/aimdk_tts_probe.py --play` 验证音频焦点与扬声器。这个标志只是人工确认，不会代替真实模式检查。

在机器人 SSH 终端、已加载 AimDK 环境并完成模式切换后，临时提供**两把**密钥：

```bash
read -r -s -p '豆包语音 API Key: ' DOUBAO_SPEECH_API_KEY; echo
read -r -s -p '火山方舟 API Key: ' ARK_API_KEY; echo
export DOUBAO_SPEECH_API_KEY ARK_API_KEY
export X2_ONLY_VOICE_CONFIRMED=1
python3 scripts/run_robot_agent.py --transport aimdk --enable-robot-audio --competition-mode --health-semantic model --llm-model doubao-seed-2-0-mini-260428 --presentation-backend none
```

先只测语音。确认机器人稳定站立、动作服务字段与机载版本匹配且现场安全后，才把最后两个参数换成 `--presentation-backend aimdk --enable-robot-presentation` 进行表情动作验收。模型只选择预设的表情和动作名称，代码负责参数映射与安全约束。停止程序后，在同一终端执行 `unset DOUBAO_SPEECH_API_KEY ARK_API_KEY X2_ONLY_VOICE_CONFIRMED`，并按官方流程恢复 `normal`。程序不会自动切换或恢复机器人模式。

## 5. 验收与迁移边界

用与仿真相同的话术按顺序测试：唤醒后问候；“有点累”后的针对性建议与收尾；先说脖子不适、再说腰酸后回顾两项；笼统用药咨询；查询今天提醒；提交一条食堂意见并核对本机记录。每轮记下转写、回答、首音延迟、表情动作、是否完成及异常恢复。真机的麦克风、扬声器、系统模式、AimDK 版本和现场网络需要逐项实测，完成后才能判断仿真效果是否在赛方机器人上复现。
