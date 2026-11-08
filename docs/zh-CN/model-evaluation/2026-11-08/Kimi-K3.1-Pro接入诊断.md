# Kimi-K3.1-Pro 接入诊断（2026-11-08）

模型 ID：`kimi-k3-1-pro-261024`。测试使用本项目原有火山方舟 Chat Completions 接口和本地密钥；未连接 Unity、麦克风或机器人。

## 发现与修复

- 原客户端固定发送 `temperature=0.7`。本账号调用该模型时，方舟返回 HTTP 400 `InvalidParameter`，提示此模型只接受 `0.6`。这会让竞赛对话生成失败，现场就会听到固定兜底回答。
- 已在 `x2_agent/llm.py` 针对 `kimi-k3-1-pro-*` 发送 `temperature=0.6`；Mini 和其他既有模型仍使用原值。修正后一次简短请求返回 HTTP 200 且有文本。
- 本项目竞赛模式默认开场只等 3 秒、普通回答只等 8 秒。修正参数后，一次开场在约 4.8 秒得到合规回答；另一次开场等 8 秒仍超时。一次健康问询在 8 秒内未完成合法输出和修正；放宽到 12 秒后，一次健康问询约 5.9 秒得到合规回答。这些样本不足以证明稳定性，也未包含 ASR/TTS 耗时。

## 仿真试运行

在有本地 `.env` 的 Windows 仿真项目 `example/x2_agent` 目录运行。先退出旧 Agent：

```powershell
python agent.py --competition-mode --health-semantic model --llm-model kimi-k3-1-pro-261024 --model-greeting-timeout 12 --model-reply-timeout 20
```

两项超时参数只是允许观察 Kimi 的完整回答，并不降低实际延迟；可能明显慢于 Mini。未传时仍为 3 秒和 8 秒，以保持既有 Mini 现场配置。若需按竞赛低延迟标准对比，应记录语音唤醒到开场播报、用户说完到首包播报，以及兜底次数，不能用放宽后的“有回答”代替低延迟评分。

当前没有对 Kimi 完成四环节的同题两轮评分，不应与《赛事评分对比》中的四个豆包模型数字直接比较。
