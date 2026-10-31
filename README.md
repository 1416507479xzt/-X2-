# X2 语音 Agent / Voice agent / Agent vocal

**使用指南 / User guide / Guide d’utilisation**

[简体中文](docs/zh-CN/README.md) · [English](docs/en/README.md) · [Français](docs/fr/README.md)

Python 客户端通过 WebSocket 连接 X2 模拟器。`agent.py` 使用豆包语音服务和火山方舟处理语音对话与技能调用；`demo.py` 使用固定文字和录音检查连接。


Python clients for the X2 simulator. `agent.py` provides voice conversations and skill calls through Doubao and Volcengine Ark; `demo.py` checks connections with fixed text and recordings.

竞赛迎宾与健康问询（可选，不改变普通模式）：在模拟器运行时，于本目录执行 `python agent.py --competition-mode --health-semantic model`。默认model模式由大模型统一决定语言、表情和动作；普通回答共用8秒时限，语音唤醒开场最多等待模型3秒，超时则使用固定问候继续问询。本地规则负责唤醒、协议校验、最多两轮问询约束、安全拦截和故障兜底。不可用的表情/动作取消执行，不因此丢弃合规回答。首包语音准备好时下发表现。拒绝回答、改口和新请求由模型理解；失败原话保留为未回答记录。状态只保存在当前进程内，重启后不保留，不是跨日健康档案。

使用 `python agent.py --competition-mode` 同样默认进入model模式。可以说“灵犀”“你好灵犀”或连续叫“灵犀灵犀”唤醒，不预设来访者姓名；旧参数 `--elder-name` 不用于称呼。会话保存最近64轮原话及最近24条模型识别为健康描述的原话；不是无限或跨日记忆。模型判断与自然语言质量仍需真实对话验收。

唤醒按拼音匹配，兼容 `ling xi` / `lin xi` 的不同汉字转写（如“凌曦”“林夕”“琳熙”），整句须为呼叫形式。新增了 pypinyin 依赖，更新后请在运行 Agent 的环境执行 `python -m pip install -r requirements.txt`；拼音转换本身在本机完成，不调用大模型。

问询结束后可以继续追问或回顾，模型依据原话记忆回答，不自动重新开启健康问询。生活协助使用本地核对资料和预设提醒；不能承诺已连接外部医疗或社区平台，也不能给出未经资料支持的个人用药方案。

默认 `--health-semantic model`：常见说法和明确动作请求都走模型统一决策，超时或非法输出只播故障提示，不自动降级到关键词健康话术。`auto`（旧混合模式）和`rules`（旧规则模式）仅保留作回归对照；两者不是完全离线模式。新模式与AimDK接口映射、启动参数和验证边界见[模型统一决策与真机表现接入](docs/zh-CN/model-presentation.md)。

启动、仿真验收用例与当前边界见 [环节一验收指南](docs/zh-CN/stage1-acceptance.md)。环节四的食堂意见收集、确认入表和本机反馈表见 [食堂意见收集指南](docs/zh-CN/stage4-dining-feedback.md)。此版本不包含自动定时推送提醒、向外部社区平台同步数据或灵创舞蹈；仿真效果及真实首音延迟需实际验收，真机适配尚需单独验证。

Clients Python pour le simulateur X2. `agent.py` utilise Doubao et Volcengine Ark pour le dialogue vocal et les actions ; `demo.py` vérifie la connexion avec du texte fixe et des enregistrements.

## 启动 / Run / Lancement

先启动模拟器，再在本目录中执行以下命令。需要 Python 3.10+，demo 无需云服务密钥。

Start the simulator first, then run these commands in this directory. Python 3.10+ is required; the demo needs no cloud keys.

Démarrez le simulateur, puis exécutez ces commandes dans ce dossier. Python 3.10+ est requis ; la démo ne nécessite aucune clé cloud.

```powershell
python -m pip install -r requirements.txt
python demo.py
```

语音凭据、参数、技能和排障见上方三语指南。/ See the guides above for voice credentials, options, skills and troubleshooting. / Consultez les guides pour les identifiants vocaux, paramètres, actions et dépannage.

## 目录 / Layout / Organisation

```text
x2_agent/
├── agent.py            # Voice agent entry
├── demo.py             # Offline demo entry
├── .env.example        # Configuration template
├── requirements.txt
├── x2_agent/           # Implementation
├── tests/
└── docs/
    ├── zh-CN/README.md
    ├── en/README.md
    └── fr/README.md
```
