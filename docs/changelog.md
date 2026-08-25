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
- 相关代码：`engine.py:43-44`、`engine.py:978-981`、`app.js:193-198`。
- 详细说明 → [usage.md#昼夜循环](usage.md#昼夜循环)

### 资源再生

- 现存矿脉每回合 15% 概率 +1，上限 6。
- 被采空格子 2% 概率重新长出同类型矿脉，储量 2~4。
- 相关代码：`world.py:95-111`。
- 详细说明 → [usage.md#资源再生](usage.md#资源再生)

### 武器耐久

- 武器耐久 6，每次攻击 -1，归零碎裂并播报。
- 相关代码：`tools.py:151-156`、`tools.py:263-271`。
- 详细说明 → [usage.md#武器耐久](usage.md#武器耐久)、[tools.md#craft--打造武器](tools.md#craft--打造武器)

### 随机世界事件

- 每回合按 `event_prob` 概率触发：暴雨、兽群来袭、丰收季。
- 事件公告并写进所有存活者记忆。
- 相关代码：`engine.py:690-732`。
- 详细说明 → [usage.md#随机世界事件](usage.md#随机世界事件)

---

## 🤖 模型层

### 重试与托管降级

- 模型调用失败隔 2 秒重试 1 次；仍失败则本回合由演示规则代打并标注。
- 相关代码：`engine.py:988-1035`。
- 详细说明 → [technical.md#并行决策](technical.md#并行决策)

### Token 用量与费用

- 按 provider 配置的单价累计费用，显示在选手卡片。
- 相关代码：`engine.py:432-454`。
- 详细说明 → [usage.md#费用怎么估算](usage.md#费用怎么估算)、[config.md#price_input--price_output](config.md#price_input--price_output)

### 缓存命中率

- DeepSeek 返回真实缓存命中/未命中 token。
- 其他 provider 不返回时，按相邻回合提示词公共前缀占比估算。
- 相关代码：`llm.py:87-113`、`engine.py:1000-1023`。
- 详细说明 → [technical.md#本地缓存命中率估算](technical.md#本地缓存命中率估算)

---

## 🏆 战绩与回放

### ELO 排行榜

- 每局结束按 `名字|模型` 累计 games/wins/kills/elo。
- 初始 1000，K=24，胜者对每个败者结算，全灭平局不调 ELO。
- 相关代码：`engine.py:573-626`、`main.py:171-180`。
- 详细说明 → [usage.md#排行榜](usage.md#排行榜)、[technical.md#elo-结算与-statsjson](technical.md#elo-结算与-statsjson)

### 回放录制

- 每局自动录制到 `replays/match_*.jsonl`。
- 首行 meta，之后每条广播消息一行。
- 相关代码：`engine.py:111-145`。
- 详细说明 → [usage.md#回放](usage.md#回放)、[protocol.md#replaysjsonl](protocol.md#replaysjsonl)

### 比赛日志落盘

- 每局日志实时追加到 `logs/match_*.log`。
- 游戏结束补一行总结。
- 相关代码：`engine.py:147-174`。
- 详细说明 → [protocol.md#logslog](protocol.md#logslog)

### 一键导出

- 导出当前这局 JSON：meta + 选手终态 + 完整日志。
- 优先以 log 文件为准补全被截断的内存历史。
- 相关代码：`engine.py:628-687`、`main.py:145-151`。
- 详细说明 → [usage.md#导出](usage.md#导出)、[protocol.md#get-apiexport](protocol.md#get-apiexport)

---

## 🎮 前端与交互

### 关系图

- 圆周布局展示选手，|关系分|≥3 画线。
- 绿=盟友，红=敌对，线旁标分数，死者置灰。
- 相关代码：`app.js:818-855`。
- 详细说明 → [usage.md#关系图](usage.md#关系图)

### 上帝传话

- 支持单人/多人/全体传话，可附带挑拨。
- 挑拨时两两关系 -5 且不公开内容。
- 相关代码：`engine.py:249-300`、`app.js:544-593`。
- 详细说明 → [usage.md#上帝传话](usage.md#上帝传话)

### 开局设置面板

- 可编辑选手、增删选手、换 provider/model、调 5 项难度。
- 「应用」重开一局，「保存到文件」写回 `config.json`。
- 运行中只读。
- 相关代码：`engine.py:302-429`、`app.js:634-752`。
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
- 相关代码：`app.js:78-80`、`app.js:102-111`。
- 详细说明 → [technical.md#dpr-适配](technical.md#dpr-适配)

### 动画效果

- 选手移动插值、受击闪红、死亡 skull 放大淡入。
- 击杀/死亡顶部全屏播报横幅。
- 夜晚蒙版渐变过渡。
- 相关代码：`app.js:183-268`、`app.js:515-523`。
- 详细说明 → [usage.md#地图区](usage.md#地图区)

### 可拖拽分隔条

- 选手卡片区与日志区之间可上下调整高度。
- 相关代码：`app.js:985-1009`。
- 详细说明 → [usage.md#可拖拽分隔条](usage.md#可拖拽分隔条)

---

## ⚡ 性能优化

### 增量快照

- `world_version` 机制：地形未变化时不重复推送 `grid`。
- 前端沿用缓存，减少带宽与重绘。
- 相关代码：`engine.py:456-461`、`app.js:41-65`。
- 详细说明 → [technical.md#增量快照缓存合并](technical.md#增量快照缓存合并)

### 提示词前缀稳定

- `perceive()` 按稳定性重排 user 消息，把规则段放最前、回合号放最后。
- 提升 DeepSeek 硬盘缓存命中率。
- 相关代码：`agent.py:148-181`。
- 详细说明 → [technical.md#前缀稳定性重排](technical.md#前缀稳定性重排)

### 广播优化

- WebSocket 发送改为并行，失败连接自动剔除。
- 相关代码：`main.py:27-48`。
- 详细说明 → [technical.md#广播流程](technical.md#广播流程)

---

## 🐛 Bug 修复与安全

### 核心竞态

- 决策等待期间被 `reset` 时，旧回合直接作废，避免用新世界结算旧决策。
- 相关代码：`engine.py:1039-1040`、`tests/test_regressions.py:69-83`。
- 详细说明 → [technical.md#reset-竞态防护](technical.md#reset-竞态防护)

### 结算健壮性

- 攻击/交易/密谋自己时返回错误。
- `accept_trade` 复核距离，报价后走开则取消。
- `accept_trade` 发现报价方死亡时清空挂单。
- `gather` 防御地形是矿脉但无储量记录的情况。
- 移动增加能量校验。
- 相关代码：`tools.py:37-42`、`tools.py:333-366`、`tools.py:80-110`、`tools.py:46-56`。
- 详细说明 → [tools.md](tools.md)

### 配置清洗

- setup 提交的选手字段会被清洗并钳位，traits 为 0 不会被吞成 0.5。
- 相关代码：`engine.py:349-371`、`tests/test_regressions.py:87-98`。
- 详细说明 → [config.md#agents-节](config.md#agents-节)

### 安全

- 前端 `/api/setup` 返回的 providers 不含 `api_key`。
- `export_data` 绝不包含 `api_key`。
- `/api/replays/{name}` 做目录穿越校验。
- 相关代码：`main.py:154-168`、`engine.py:628-687`、`main.py:201-209`。
- 详细说明 → [config.md#安全注意事项](config.md#安全注意事项)、[protocol.md#get-apireplaysname](protocol.md#get-apireplaysname)

---

## 🆕 新增功能（本次迭代）

### 1. 日志事件结构化

- 所有 `log` 条目在保留 `text` 渲染文本的同时，按事件类型附带结构化字段：`move`/`item`/`fight`/`death`/`trade`/`think`/`god`/`event`/`sys` 均有对应字段。
- 前端、日志文件、导出文本行保持不变；旧客户端可安全忽略新增字段。
- 一键导出 `/api/export` 新增 `events` 数组，含结构化字段，供程序化统计与复盘。
- 回放录制无需改动：录制的广播消息已自动携带结构化字段。
- 相关代码：`engine.py`、`tools.py`、`tests/test_tools.py`、`tests/test_log_export.py`。
- 详细说明 → [protocol.md#日志-log](protocol.md#日志-log)、[protocol.md#get-apiexport](protocol.md#get-apiexport)

### 2. 赠送工具 `give`

- 可单方面把 food/ore 赠送给 4 格内其他存活代理，受赠者对赠送者关系 +2。
- 相关代码：`tools.py`、`agent.py`、`engine.py`。
- 详细说明 → [tools.md#give--赠送](tools.md#give--赠送)

### 3. 夜晚偷袭加成

- 夜晚攻击在 `damage_mult` 后再 +3，日志与反馈均标注「夜晚偷袭+3」。
- 感知规则段夜晚时动态提示该加成。
- 相关代码：`tools.py`、`agent.py`。
- 详细说明 → [tools.md#attack--攻击](tools.md#attack--攻击)、[usage.md#攻击与关系](usage.md#攻击与关系)

### 4. AI 解说员

- 每 `commentary_interval` 回合（默认 5）非阻塞调用 LLM 生成局势点评，以 `kind=commentary` 广播。
- 前端新增「📣 解说」滚动条与 🔊 浏览器语音开关。
- 演示模式自动关闭；可在 `config.json` 顶层配置 `commentator` 节指定 provider/model。
- 相关代码：`engine.py`、`llm.py`、`web/app.js`、`web/icons.js`、`web/index.html`、`web/style.css`。
- 详细说明 → [config.md#解说员专属配置-commentator](config.md#解说员专属配置-commentator)、[usage.md#解说滚动条与语音开关](usage.md#解说滚动条与语音开关)

### 5. 定期反思

- 每 `reflect_interval` 回合（默认 10）为每个有真实模型的存活代理生成一句反思，写入 `notes` 并以 `think` 日志广播。
- 失败静默，演示模式跳过。
- 相关代码：`engine.py`、`llm.py`。

### 6. 设置面板头像选择器

- emoji 输入改为 SVG 头像按钮 + 自定义 emoji 文本框，选中头像高亮，协议仍存 emoji。
- 相关代码：`web/icons.js`（导出 `AVATAR_CHOICES`）、`web/app.js`、`web/style.css`。
- 详细说明 → [usage.md#开局设置](usage.md#开局设置)

---

## 🆕 新增功能（标准结局）

### 1. 回合上限与强制评分结算

- `world.max_turns` 默认 300，0=无上限；达到上限且未分出胜负时强制终局。
- 评分规则：`存活 > 击杀 > 资源分`；并列用关系总分/出场顺序 tie-break。
- 胜者对其他败者走标准 ELO 结算；歼灭结局保持原逻辑不变。
- 相关代码：`engine.py:337-343`、`engine.py:519-570`、`engine.py:1095-1141`。
- 详细说明 → [usage.md#结局规则与称号](usage.md#结局规则与称号)、[config.md#max_turns](config.md#max_turns)、[technical.md#评分与称号](technical.md#评分与称号)

### 2. 称号系统

- 任何结局都结算称号：🏆 生存冠军、⚔️ 霸主、💰 富翁、🤝 外交家。
- 称号获得者以 `sys` 日志逐条公告；累计进 `stats.json` 的 `titles` 字段。
- 相关代码：`engine.py:537-570`、`engine.py:611-616`。
- 详细说明 → [usage.md#结局规则与称号](usage.md#结局规则与称号)

### 3. 终局结算面板

- 胜者横幅升级为展示胜者 + 全部称号。
- 自动弹出「终局结算」面板：排名表 + 称号行；点击横幅可再次打开。
- 顶栏回合显示增加进度：`回合 45/300`（max_turns>0 时）。
- 排行榜新增「称号」统计列。
- 相关代码：`web/app.js:446-503`、`web/app.js:797-810`、`web/index.html:94-101`、`web/style.css:248-310`。
- 详细说明 → [usage.md#排行榜](usage.md#排行榜)、[protocol.md#game_over-子字段结束时](protocol.md#game_over-子字段结束时)

### 4. 测试补充

- 新增 `tests/test_game_over.py`：覆盖回合上限触发、评分排序、并列规则、称号计算、stats 累计、正常歼灭结局。
- 新增 `tests/test_review.py`：覆盖 LLM 复盘生成、演示模式降级、reset 清空、snapshot/export 携带。
- 全测试套件由 88 用例增至 91 用例。

### 5. AI 全局复盘

- 游戏结束（歼灭或回合上限）后，引擎非阻塞调用解说员 LLM 生成全局复盘。
- Prompt 要求约 200 字中文输出，结构含：一句话总结、局势回顾、转折点、MVP 点评、名场面/趣事。
- 无可用 API Key 时自动降级为模板化复盘，并标注「演示模式自动生成」。
- 复盘文本写入 `engine.match_review`，随 `snapshot.match_review` 携带，以独立 `type=review` WebSocket 消息广播，并以 `kind=review` 进入日志流与 `.log` 文件。
- 前端结算面板新增 AI 复盘区；复盘到达前显示「AI 复盘中…」。
- 一键导出 `/api/export` 的 `meta.review` 字段也携带复盘文本。
- 相关代码：`engine.py:821-895`、`main.py:27-48`、`web/app.js:56-60`、`web/app.js:489-503`、`web/index.html:99`、`web/style.css:354-372`。
- 详细说明 → [usage.md#结局规则与称号](usage.md#结局规则与称号)、[technical.md#全局复盘](technical.md#全局复盘)、[protocol.md#全局复盘-review](protocol.md#全局复盘-review)

---

## 🐛 Bug 修复（v2 维护批次）

### 1. WebSocket 发送失败时先 close 再剔除

- `Hub.send` 对发送失败的连接先 `await ws.close()`，再移出连接集合；close 本身也做 try/except 保护。
- 失败时打印简短日志说明剔除原因。
- 相关代码：`main.py:27-48`。

### 2. check_status.py 更友好

- 端口读取优先级：`sys.argv[1]` > 环境变量 `PORT` > 默认 `8080`。
- 连接失败打印友好错误并退出码 1，不再抛出未处理异常。
- 相关代码：`check_status.py:1-48`。

### 3. 演示模式不再反复撞墙

- `demo_decide` 决定 `move` 时把方向存入 `agent._demo_last_dir`。
- 下回合若最近 `[行动结果]` 含「过不去」或「无法移动」，则避开上次方向，用 `world.is_blocked` 预判四个方向；全堵则改为 `rest`。
- 相关代码：`llm.py:159-192`、`tools.py:48-65`。

### 4. history 改用 deque(maxlen=800)

- `self.history` 由 `list` 改为 `collections.deque(maxlen=800)`，删除手动 `pop(0)` 逻辑。
- 检查所有用法（clear / 迭代 / len / ws 重放 / commentary / review / export）均兼容 deque。
- 相关代码：`engine.py:94`、`engine.py:238-247`、`tests/test_log_export.py:1-96`。

### 5. reset 时自动清理旧回放与日志

- `engine.reset()` 顺手清理 `replays/` 和 `logs/`，各保留最近 50 个文件（按 mtime），更老的删除；清理失败静默。
- 相关代码：`engine.py:22-42`、`engine.py:177-179`。

### 6. 上帝消息统一截断 200 字符

- `engine.god_say` 与 `engine.god_message` 均统一截断 200 字符（与 `main.py` 的上帝广播处理一致），截断时不另加提示。
- 相关代码：`engine.py:222-229`、`main.py:128-134`。

### 7. /api/setup 更防御

- CONFIG 取值改 `.get()` 带默认值，`world` 字段异常时回退到默认难度，缺字段不返回 500。
- 相关代码：`main.py:154-168`。

### 8. 搜尸提示补全

- 自己已有武器、死者武器不继承时，反馈和日志补一句「死者的武器随尸体消失了」。
- 相关代码：`tools.py:233-260`。

### 9. 文档补充

- `docs/usage.md` 称号规则处补充：霸主可颁给已死亡的击杀王（战死也留名）。
- 相关代码：`docs/usage.md:575`。

### 10. 测试补充

- 新增回归用例覆盖：演示 AI 撞墙后换方向、history deque 上限、上帝消息截断、搜尸武器提示文案、日志/回放轮转。
- 全测试套件由 91 用例增至 99 用例。
- 相关代码：`tests/test_regressions.py`、`tests/test_god_setup.py`、`tests/test_tools.py`、`tests/test_log_export.py`。

---

## 🆕 近期优化与调整（v2 后续迭代）

### 1. 默认阵容更换为暴力六人组

- `config.example.json` 默认选手改为：屠夫 / 疯狗 / 毒蛇 / 暴君 / 军阀 / 血鸦，全部高攻击性，便于快速进入战斗节奏。
- 文档示例中若仍出现「陈默 / 白夜 / 陛下」等旧名字，仅作为格式演示，不代表当前默认阵容。
- 相关改动：`config.example.json:49-146`。

### 2. 回合上限默认调整

- 代码中 `max_turns` 默认值保持 `300`，但 `config.example.json` 已设为 `200`，新clone/复制配置后默认 200 回合强制评分结算。
- 设为 `0` 表示无上限。
- 相关代码：`engine.py:337-343`、`config.example.json:7`。

### 3. 掉落与搜尸广播文案可读化

- 死亡、搜尸日志不再使用 Python `repr`，统一改为 `食物xN 矿石xM [武器]` 的人类可读格式（`_items_str`）。
- 搜尸现在可以缴获死者武器（自己无武器时），相关反馈与日志文案同步补全。
- 相关代码：`tools.py:46-56`、`tools.py:151-176`、`tools.py:233-260`、`engine.py:1083-1093`。

### 4. 提示词前缀稳定率再优化

- `perceive()` 把「你的状态」段刻意后置（每回合必变），并把夜晚偷袭规则作为无条件静态文本写进规则段。
- 实测连续两回合前缀稳定率约 84%，昼夜切换约 79%。
- 相关代码：`agent.py:158-163`、`agent.py:179-181`。

### 5. Key 存储改为 `.env` 文件

- 新增零依赖 `_load_dotenv()`，模块导入时自动加载项目根目录 `.env`，不覆盖已有环境变量。
- 提供 `.env.example` 模板；`config.json` 中的 `api_key` 仍然有效，但推荐优先使用 `.env`。
- 相关代码：`llm.py:16-33`。

### 6. 解说条 ticker 化与位置调整

- 解说条从日志区上方移至地图区底部，采用新闻滚动条样式；文案较短时静止显示，较长时横向滚动。
- 重置或开新局时清空解说条与语音状态。
- 相关代码：`web/app.js:395-449`、`web/index.html:67`、`web/style.css:184-211`。

### 7. WINNER 横幅与浮层互斥

- 游戏结束后先弹出顶部金色 WINNER 横幅，约 0.9 秒后自动展开结算面板。
- 打开设置/排行/关系/回放/结算任一浮层时，横幅自动隐藏；关闭所有浮层后恢复横幅。
- 用户手动关闭结算面板后，本局复盘到达不再自动弹窗。
- 相关代码：`web/app.js:465-549`。

### 8. 解说员提示词约束加强

- 加强对解说长度与输出格式的约束，避免模型返回 JSON 或动作名。
- 相关代码：`engine.py:802-816`。

---

## 📁 目录变化

v2 新增/变化：

- `replays/`：自动录制 JSONL
- `logs/`：自动落盘文本日志
- `stats.json`：跨局战绩
- `web/icons.js`：SVG 图标库
- `tests/`：完整 pytest 测试套件
- `docs/`：本文档集
