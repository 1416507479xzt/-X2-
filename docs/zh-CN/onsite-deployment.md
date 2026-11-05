# 赛方统一 X2 的现场部署要点

完整可复制的电脑构建、SSH 部署、机器人终端联调与验收步骤见[从新电脑复现 X2 自研语音 Agent](reproduce-on-x2.md)。本页记录比赛现场相对手头机器人新增的不确定项。

参赛手册要求在赛方提供的灵犀 X2 真机上部署和演示，并提前准备最终代码、配置文件与调试文件；具体安排以组委会后续通知为准。赛方机器的固件、AimDK 版本、Python 环境、账号和网络策略尚未确认。

## 到场先核对

1. 确认机型是否为 X2 Ultra，以及赛方允许的 SSH、文件复制、原生交互模式切换和恢复方式。官方 [`only_voice` 过渡方案](https://x2-aimdk.agibot.com/zh-cn/latest/faq/temp_works.html)明确限定 X2 Ultra。
2. 在 PC2 上只读检查 `uname -m`、`python3 --version`、机载 AimDK `version` 文件和 `ros2 interface`；再运行包内 `scripts/robot_preflight.py`。已知离线包只针对 Linux aarch64、CPython 3.10 和 AimDK v1.0.0/v1.1.0 的音频接口。其他版本先适配再演示。
3. 确认机器人运行时能连接豆包语音和火山方舟服务，并获准使用自备 API Key。离线包免去真机上下载 Python 依赖，不能替代云端服务网络。
4. 先做只读 PCM 和 ASR 转写，再按官方流程切换与恢复 `only_voice`，依次测模型回答、TTS 音频焦点、表情动作及环节一、二、四的连续对话。每一项均需保存不含密钥和真实长者隐私的结果。

当前只有手头 X2 的 VAD PCM 输入完成真机实测。省赛机器上是否能零修改运行，取决于上述现场接口与环境核对结果；未通过预检时不要绕过检查启动完整 Agent。
