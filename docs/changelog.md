# 📜 更新日志

## v2 主要变化

v2 在 v1 的基础上把「生存沙盒」做成了可长期运行、可复盘、可调参、可下场的完整观赛系统。

文档索引：

- 玩家操作与机制 → [usage.md](usage.md)
- 开发者架构与细节 → [technical.md](technical.md)
- 配置字段参考 → [config.md](config.md)
- 接口协议 → [protocol.md](protocol.md)
- 工具详细说明 → [tools.md](tools.md)

---

## 🌍 世界机制

### 视野限制

- 代理只能看到白天 6 格、夜晚 3 格（曼哈顿距离）内的存活者。
- 视野外的人不出现在感知里，也无法 `inspect`。
- 相关代码：`agent.py:72-74`、`tools.py:179-181`。
- 详细说明 → [usage.md#视野](usage.md#视野)

### 昼夜循环

- 24 回合一个周期：前 16 白天、后 8 夜晚。
- 夜晚地图叠加暗色蒙版，系统公告切换。
- 相关代码：`engine.py:19-20`、`engine.py:582-586`、`app.js:190-195`。
- 详细说明 → [usage.md#昼夜循环](usage.md#昼夜循环)

### 资源再生

- 现存矿脉每回合 15% 概率 +1，上限 6。
- 被采空格子 2% 概率重新长出同类型矿脉，储量 2~4。
- 相关代码：`world.py:95-111`。
- 详细说明 → [usage.md#资源再生](usage.md#资源再生)

### 武器耐久

- 武器耐久 6，每次攻击 -1，归零碎裂并播报。
- 相关代码：`tools.py:121-126`、`tools.py:202-210`。
- 详细说明 → [usage.md#武器耐久](usage.md#武器耐久)、[tools.md#craft--打造武器](tools.md#craft--打造武器)

### 随机世界事件

- 每回合按 `event_prob` 概率触发：暴雨、兽群来袭、丰收季。
- 事件公告并写进所有存活者记忆。
- 相关代码：`engine.py:527-556`。
- 详细说明 → [usage.md#随机世界事件](usage.md#随机世界事件)

---

## 🤖 模型层

### 重试与托管降级

- 模型调用失败隔 2 秒重试 1 次；仍失败则本回合由演示规则代打并标注。
- 相关代码：`engine.py:612-640`。
- 详细说明 → [technical.md#并行决策](technical.md#并行决策)

### Token 用量与费用

- 按 provider 配置的单价累计费用，显示在选手卡片。
- 相关代码：`engine.py:354-376`。
- 详细说明 → [usage.md#费用怎么估算](usage.md#费用怎么估算)、[config.md#price_input--price_output](config.md#price_input--price_output)

### 缓存命中率

- DeepSeek 返回真实缓存命中/未命中 token。
- 其他 provider 不返回时，按相邻回合提示词公共前缀占比估算。
- 相关代码：`llm.py:85-91`、`engine.py:621-626`。
- 详细说明 → [technical.md#本地缓存命中率估算](technical.md#本地缓存命中率估算)

---

## 🏆 战绩与回放

### ELO 排行榜

- 每局结束按 `名字|模型` 累计 games/wins/kills/elo。
- 初始 1000，K=24，胜者对每个败者结算，全灭平局不调 ELO。
- 相关代码：`engine.py:426-471`、`main.py:162-171`。
- 详细说明 → [usage.md#排行榜](usage.md#排行榜)、[technical.md#elo-结算与-statsjson](technical.md#elo-结算与-statsjson)

### 回放录制

- 每局自动录制到 `replays/match_*.jsonl`。
- 首行 meta，之后每条广播消息一行。
- 相关代码：`engine.py:70-103`。
- 详细说明 → [usage.md#回放](usage.md#回放)、[protocol.md#replaysjsonl](protocol.md#replaysjsonl)

### 比赛日志落盘

- 每局日志实时追加到 `logs/match_*.log`。
- 游戏结束补一行总结。
- 相关代码：`engine.py:106-133`。
- 详细说明 → [protocol.md#logslog](protocol.md#logslog)

### 一键导出

- 导出当前这局 JSON：meta + 选手终态 + 完整日志。
- 优先以 log 文件为准补全被截断的内存历史。
- 相关代码：`engine.py:474-524`、`main.py:140-146`。
- 详细说明 → [usage.md#导出](usage.md#导出)、[protocol.md#get-apiexport](protocol.md#get-apiexport)

---

## 🎮 前端与交互

### 关系图

- 圆周布局展示选手，|关系分|≥3 画线。
- 绿=盟友，红=敌对，线旁标分数，死者置灰。
- 相关代码：`app.js:651-714`。
- 详细说明 → [usage.md#关系图](usage.md#关系图)

### 上帝传话

- 支持单人/多人/全体传话，可附带挑拨。
- 挑拨时两两关系 -5 且不公开内容。
- 相关代码：`engine.py:199-236`、`app.js:399-454`。
- 详细说明 → [usage.md#上帝传话](usage.md#上帝传话)

### 开局设置面板

- 可编辑选手、增删选手、换 provider/model、调 5 项难度。
- 「应用」重开一局，「保存到文件」写回 `config.json`。
- 运行中只读。
- 相关代码：`engine.py:238-351`、`app.js:472-627`。
- 详细说明 → [usage.md#开局设置](usage.md#开局设置)

### UI 升级

- 深色电竞风全新样式。
- 地图、顶栏、卡片、日志、面板全部重设计。
- SVG 图标库替代 emoji，统一 stroke 风格。
- 相关代码：`web/style.css`、`web/icons.js`。
- 详细说明 → [technical.md#svg-图标库](technical.md#svg-图标库)

### 高 DPI 与响应式

- canvas 按 `devicePixelRatio` 缩放，HiDPI 屏幕清晰。
- 地图格子尺寸按窗口自适应 clamp 在 20~56 px。
- 相关代码：`app.js:71-78`、`app.js:95-104`。
- 详细说明 → [technical.md#dpr-适配](technical.md#dpr-适配)

### 动画效果

- 选手移动插值、受击闪红、死亡 skull 放大淡入。
- 击杀/死亡顶部全屏播报横幅。
- 夜晚蒙版渐变过渡。
- 相关代码：`app.js:176-245`、`app.js:376-385`。
- 详细说明 → [usage.md#地图区](usage.md#地图区)

### 可拖拽分隔条

- 选手卡片区与日志区之间可上下调整高度。
- 相关代码：`app.js:824-848`。
- 详细说明 → [usage.md#可拖拽分隔条](usage.md#可拖拽分隔条)

---

## ⚡ 性能优化

### 增量快照

- `world_version` 机制：地形未变化时不重复推送 `grid`。
- 前端沿用缓存，减少带宽与重绘。
- 相关代码：`engine.py:378-383`、`app.js:38-50`。
- 详细说明 → [technical.md#增量快照缓存合并](technical.md#增量快照缓存合并)

### 提示词前缀稳定

- `perceive()` 按稳定性重排 user 消息，把规则段放最前、回合号放最后。
- 提升 DeepSeek 硬盘缓存命中率。
- 相关代码：`agent.py:148-181`。
- 详细说明 → [technical.md#前缀稳定性重排](technical.md#前缀稳定性重排)

### 广播优化

- WebSocket 发送改为并行，失败连接自动剔除。
- 相关代码：`main.py:27-43`。
- 详细说明 → [technical.md#广播流程](technical.md#广播流程)

---

## 🐛 Bug 修复与安全

### 核心竞态

- 决策等待期间被 `reset` 时，旧回合直接作废，避免用新世界结算旧决策。
- 相关代码：`engine.py:644-645`、`tests/test_regressions.py:69-83`。
- 详细说明 → [technical.md#reset-竞态防护](technical.md#reset-竞态防护)

### 结算健壮性

- 攻击/交易/密谋自己时返回错误。
- `accept_trade` 复核距离，报价后走开则取消。
- `accept_trade` 发现报价方死亡时清空挂单。
- `gather` 防御地形是矿脉但无储量记录的情况。
- 移动增加能量校验。
- 相关代码：`tools.py:37-42`、`tools.py:241-261`、`tools.py:63-89`、`tools.py:47-60`。
- 详细说明 → [tools.md](tools.md)

### 配置清洗

- setup 提交的选手字段会被清洗并钳位，traits 为 0 不会被吞成 0.5。
- 相关代码：`engine.py:278-299`、`tests/test_regressions.py:87-98`。
- 详细说明 → [config.md#agents-节](config.md#agents-节)

### 安全

- 前端 `/api/setup` 返回的 providers 不含 `api_key`。
- `export_data` 绝不包含 `api_key`。
- `/api/replays/{name}` 做目录穿越校验。
- 相关代码：`main.py:149-159`、`engine.py:474-524`、`main.py:192-200`。
- 详细说明 → [config.md#安全注意事项](config.md#安全注意事项)、[protocol.md#get-apireplaysname](protocol.md#get-apireplaysname)

---

## 🆕 新增功能（本次迭代）

### 1. 赠送工具 `give`

- 可单方面把 food/ore 赠送给 4 格内其他存活代理，受赠者对赠送者关系 +2。
- 相关代码：`tools.py`、`agent.py`、`engine.py`。
- 详细说明 → [tools.md#give--赠送](tools.md#give--赠送)

### 2. 夜晚偷袭加成

- 夜晚攻击在 `damage_mult` 后再 +3，日志与反馈均标注「夜晚偷袭+3」。
- 感知规则段夜晚时动态提示该加成。
- 相关代码：`tools.py`、`agent.py`。
- 详细说明 → [tools.md#attack--攻击](tools.md#attack--攻击)、[usage.md#攻击与关系](usage.md#攻击与关系)

### 3. AI 解说员

- 每 `commentary_interval` 回合（默认 5）非阻塞调用 LLM 生成局势点评，以 `kind=commentary` 广播。
- 前端新增「📣 解说」滚动条与 🔊 浏览器语音开关。
- 演示模式自动关闭；可在 `config.json` 顶层配置 `commentator` 节指定 provider/model。
- 相关代码：`engine.py`、`llm.py`、`web/app.js`、`web/icons.js`、`web/index.html`、`web/style.css`。
- 详细说明 → [config.md#解说员专属配置-commentator](config.md#解说员专属配置-commentator)、[usage.md#解说滚动条与语音开关](usage.md#解说滚动条与语音开关)

### 4. 定期反思

- 每 `reflect_interval` 回合（默认 10）为每个有真实模型的存活代理生成一句反思，写入 `notes` 并以 `think` 日志广播。
- 失败静默，演示模式跳过。
- 相关代码：`engine.py`、`llm.py`。

### 5. 设置面板头像选择器

- emoji 输入改为 SVG 头像按钮 + 自定义 emoji 文本框，选中头像高亮，协议仍存 emoji。
- 相关代码：`web/icons.js`（导出 `AVATAR_CHOICES`）、`web/app.js`、`web/style.css`。
- 详细说明 → [usage.md#开局设置](usage.md#开局设置)

---

## 📁 目录变化

v2 新增/变化：

- `replays/`：自动录制 JSONL
- `logs/`：自动落盘文本日志
- `stats.json`：跨局战绩
- `web/icons.js`：SVG 图标库
- `tests/`：完整 pytest 测试套件
- `docs/`：本文档集
