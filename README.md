# ⚔️ AI 大战 · 多模型生存沙盒

把多个大模型（DeepSeek / 硅基流动 / OpenRouter…）放进同一张地图，让它们自己决定怎么活：
**采集、休息、交易、结盟、偷袭、掠夺、报仇**……一切行为由模型自主决策，你只负责提供工具和旁观。

网页实时观看：世界地图、每个选手的血条/能量/物品、全部言行日志，还能用「上帝广播」下场搅局。

---

## 🚀 快速开始

```bash
# 安装依赖（需要 Python 3.9+）
python -m pip install -r requirements.txt
# 本机默认 python 无 pip 时，改用你的 Anaconda 解释器：
# F:\anaconda\python.exe -m pip install -r requirements.txt

python main.py
# 浏览器打开 http://127.0.0.1:8080
# 端口被占用时：set PORT=9000 && python main.py
```

> 没填 API Key 也能跑：引擎自动进入「演示模式」，用规则 AI 模拟选手行为，先把整套戏看明白。
> 填了 Key 的选手用真实模型，没填的选手继续用规则模拟，可以混搭。
>
> 🔑 **API Key 配置**：复制 `.env.example` 为 `.env` 填入 Key（推荐，`.env` 已在 `.gitignore` 中）；
> 或用系统环境变量（`DEEPSEEK_API_KEY` / `SILICONFLOW_API_KEY` / `OPENROUTER_API_KEY`）；
> 也可以复制 `config.example.json` 为 `config.json` 后在 `api_key` 字段填写（`config.json` 同样不会被提交）。

跑单元测试（纯逻辑，不需要 API key）：

```bash
python -m pytest tests -q
```

---

## 📚 文档索引

| 文档 | 面向读者 | 内容 |
|------|----------|------|
| [docs/usage.md](docs/usage.md) | 玩家 / 观战者 | 安装启动、界面导览、操作手册、世界机制、FAQ |
| [docs/technical.md](docs/technical.md) | 开发者 | 架构总览、主循环、提示词工程、工具系统、世界生成、ELO、前端渲染 |
| [docs/tools.md](docs/tools.md) | 玩家 / 开发者 | 18 个代理工具完整参考：参数、消耗、效果、关系影响、新增工具指南 |
| [docs/config.md](docs/config.md) | 配置者 | `config.json` 全字段说明、traits 含义、安全建议 |
| [docs/protocol.md](docs/protocol.md) | 前后端开发者 | WebSocket / HTTP 接口协议、文件格式 |
| [docs/changelog.md](docs/changelog.md) | 所有人 | v1 → v2 全部变化汇总 |

---

## ✨ v2  highlights

- 🌍 **视野与昼夜**：白天 6 格 / 夜晚 3 格视野，24 回合昼夜循环
- 🌱 **资源再生**：矿脉会枯竭也会重新生长
- 🗡️ **武器耐久**：3 矿石造武器，用多了会碎
- 🎲 **随机事件**：暴雨、兽群、丰收季
- 🤖 **重试降级**：模型失败自动重试，仍失败由托管 AI 代打
- 💰 **费用统计**：按 provider 单价累计 token 费用
- 🏆 **ELO 排行榜**：跨局累计战绩
- 🎬 **自动回放**：每局录制 JSONL，支持进度条与倍速
- 📝 **日志落盘**：每局生成 `.log` 文本文件
- ⬇️ **一键导出**：下载当前对局完整 JSON
- 🕸️ **关系图谱**：圆周布局可视化盟友/敌对
- 👁 **上帝传话**：单人/多人/全体，可挑拨
- ⚙️ **开局设置**：在线编辑选手、难度，应用或保存到文件
- 🎁 **单方面赠送**：`give` 工具可送礼/进贡拉拢关系
- 🌙 **夜晚偷袭加成**：夜晚攻击额外 +3
- 📣 **AI 解说员**：LLM 非阻塞点评局势，前端滚动条 + 浏览器语音
- 🧠 **定期反思**：每 M 回合让真实模型代理总结局势并写入 notes
- 🎨 **头像选择器**：设置面板可视化选择 SVG 头像

---

## 📁 目录结构

```
config.json      选手 / 模型 / 世界配置
main.py          FastAPI + WebSocket 服务器
engine.py        主循环：感知→决策→结算；昼夜/事件/ELO/录制
agent.py         代理：状态、关系、记忆、视野感知
world.py         地图生成、资源再生、版本号
tools.py         工具定义与行动结算
llm.py           多模型客户端 + 演示模式
web/             网页前端
  index.html     页面结构
  style.css      深色电竞风样式
  icons.js       SVG 图标库
  app.js         前端逻辑
tests/           pytest 单元测试
replays/         每局自动录制的 JSONL 回放（运行时生成）
logs/            每局的比赛日志文本（运行时生成）
stats.json       跨局战绩（一局结束时生成/更新）
docs/            项目文档
```

---

## 💡 小贴士

- 想让戏更刺激：把 `turns_per_second` 调快，或给掠夺者型选手提高 `aggression`
- 模型报错会在日志里标 `⚠️`，不影响其他选手
- 每回合每个选手的提示词约 1.5k tokens，长跑请留意 API 费用
