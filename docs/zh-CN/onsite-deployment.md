# 赛方统一机器人现场部署方案

参赛手册第 3 页要求省赛在赛方提供的灵犀 X2 真机上部署和演示，并提前准备最终代码、配置文件及现场调试文件；具体安排以组委会后续通知为准。手册没有承诺机器人固件版本，也没有明确禁止或允许现场安装依赖。

## 离线运行包

`智慧养老_X2真机离线运行包_aarch64_py310.zip` 包含同一份 Agent 业务代码和针对 Linux aarch64 / CPython 3.10 下载的依赖文件，已直接放在 `vendor/` 下。现场解压后由启动入口引入，不调用 `pip install`，不依赖现场联网下载 Python 依赖。包不含 API Key、`.env`、个人录音和食堂反馈记录。

该包的**语音适配层**目前支持机载 AimDK v1.0.0（内置麦流编号 1）和 v1.1.0（编号 0），由版本文件自动选取，并在创建 ROS 节点前核查消息与服务字段。表情动作后端仍须按赛方机器的实际接口单独验证，先以 `--presentation-backend none` 测语音。如果赛方机器的 SDK 或 Python 架构不在已知范围内，预检会停止运行。`robot_preflight.py` 是只读检查，不调用动作、播放或模式切换。

## 现场顺序

1. 核对赛方允许的部署途径、网络、机型和交互模式切换权限。获取现场机器人参数后，在电脑上针对该版本提前生成对应离线包。
2. 将离线包复制至 PC2 的用户目录并解压，执行 `source /home/agi/aimdk/install/local_setup.bash`，然后在解压目录运行 `python3 scripts/robot_preflight.py`。预检通过才继续。不要覆盖机载 SDK 或向 PC1 安装程序。
3. 通过赛方允许的安全方式将 API Key 提供给进程；演示和提交材料中均不得包含明文密钥。
4. 按与现场固件匹配的官方说明切换到 `only_voice`，并准备恢复 `normal` 的操作。`scripts/run_robot_agent.py` 还要求会话环境变量 `X2_ONLY_VOICE_CONFIRMED=1`，防止未确认模式时误启动。这个变量是人工确认标记，不会自动核实机器人状态。
5. 先以 `--presentation-backend none` 做语音链路测试，再验证 AimDK 表情与预设动作。发现冲突或异常应停止自研 Agent，按官方流程恢复原生模式。完整真机演示尚未验收。

## 当前机器人上的下一步：只读 ASR 联调

手头 X2 已确认可收到完整 VAD PCM，但尚未确认这段音频能被项目使用的豆包 ASR 正确识别。可先在**手头机器人**上运行离线包中的 ASR 探针。此步骤只订阅麦克风话题并请求云端识别，不申请音频焦点、不播放、不切换交互模式，也不保存录音。`scripts/aimdk_asr_probe.py` 会从包内 `vendor/` 加载依赖，无需向系统 Python 安装 `websockets`。

在电脑 PowerShell 中先进入本仓库根目录，再输入当前机器人的地址并复制上一级目录中的离线包；比赛现场须使用赛方给出的地址：

```powershell
$RobotIp = Read-Host '输入机器人 IP'
scp '..\智慧养老_X2真机离线运行包_aarch64_py310.zip' "agi@${RobotIp}:/home/agi/eldercare-probe/"
```

在机器人 SSH 终端中执行；解压到用户目录后，不覆盖 `/home/agi/aimdk`：

```bash
cd /home/agi/eldercare-probe
unzip -q -o 智慧养老_X2真机离线运行包_aarch64_py310.zip
source /home/agi/aimdk/install/local_setup.bash
cd eldercare_x2
python3 scripts/robot_preflight.py
read -r -s -p '豆包语音 API Key: ' DOUBAO_SPEECH_API_KEY; echo
export DOUBAO_SPEECH_API_KEY
python3 scripts/aimdk_asr_probe.py --duration 60 --stream-id 1
unset DOUBAO_SPEECH_API_KEY
```

`read -s` 不会回显密钥，也不会将密钥写入命令历史；不要把密钥或带密钥的终端截图发到聊天或仓库。若预检失败，先记录不含密钥的报错并停止。探针打印识别文字时，核对是否与实际说话一致；不要把真实长者的语音或健康信息用于公开测试。识别成功只说明输入与云端 ASR 这两段联通，仍不代表模型回答、TTS 播放、表情动作及 `only_voice` 已在真机验证。

## 当前限制

目前已在一台机载 AimDK v1.0.0 的 X2 上只读验证 VAD PCM 输入；v1.1.0 只依据官方文档和接口字段做了静态适配，赛方统一机器人尚未拿到。云端 ASR、真机播放、音频焦点、`only_voice` 模式和多环节连续演示均未实测。离线包解决“现场不联网装 Python 包”的问题，**不保证不同固件零配置直接运行**。业务逻辑通过传输适配器保持一致，但环境和接口适配必须按现场机器验证。
