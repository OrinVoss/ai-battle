# 🛠 技术文档

本文档面向开发者与深度用户，涵盖系统架构、主循环、提示词工程、工具系统、世界生成、战绩结算、前端渲染管线与设计决策。阅读后应能在不反复翻源码的情况下理解系统全貌，并能安全地新增工具、调整配置或扩展前端。

---

## 🏗 架构总览

### 模块关系图

```
┌─────────────────────────────────────────────────────────────┐
│                        浏览器前端                             │
│  web/index.html  web/style.css  web/icons.js  web/app.js    │
│   (DOM 结构)      (样式)        (SVG 库)      (状态/渲染)    │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket / HTTP
┌──────────────────────────▼──────────────────────────────────┐
│                     FastAPI 服务器                            │
│                        main.py                                │
│   /ws  /api/export  /api/setup  /api/stats  /api/replays/*   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      Engine 主循环                            │
│                       engine.py                               │
│   reset → run_turn → loop → snapshot/log → Hub.broadcast      │
└──────┬──────────────┬──────────────┬──────────────────────────┘
       │              │              │
   agent.py      world.py      tools.py
   感知/记忆     地图/再生      行动结算
       │              │              │
   llm.py        (random)      (json schema)
   模型客户端
```

### 模块职责

| 文件 | 职责 | 核心类/函数 |
|------|------|-------------|
| `main.py` | FastAPI 入口、WebSocket 连接管理、HTTP API、静态文件挂载 | `Hub`, `ws_endpoint`, `api_*` |
| `engine.py` | 主循环、难度参数、世界事件、ELO、录制、日志、导出 | `Engine`, `TurnCtx` |
| `agent.py` | Agent 状态、关系、记忆、视野、感知提示词组装 | `Agent` |
| `world.py` | 地图生成、地形/矿脉、资源再生、版本号 | `World` |
| `tools.py` | TOOL_SCHEMAS 定义、RESOLVE 行动结算函数 | `TOOL_SCHEMAS`, `RESOLVE` |
| `llm.py` | AsyncOpenAI 客户端构建、模型调用、usage 解析、演示模式 | `build_client`, `llm_act`, `demo_decide` |
| `web/app.js` | 前端状态、渲染、控制、回放、关系图 | `state`, `applyMsg`, `render*` |
| `web/icons.js` | SVG 图标库与 canvas 绘制 | `icon`, `drawIcon`, `avatarIconName` |
| `tests/*` | pytest 单元测试 | `test_*.py` |

---

## 🧱 关键类与字段

### `Engine`（`engine.py:65-1118`）

`Engine` 是整个后端的控制中心，持有世界、选手、客户端、日志、回放等全部状态。

| 字段 | 类型 | 含义 |
|------|------|------|
| `config` | dict | 从 `config.json` 读取的完整配置 |
| `hub` | `Hub` | 广播与录制回调 |
| `speed` | float | 当前运行速度（回合/秒） |
| `world` | `World` | 当前世界实例 |
| `agents` | list[Agent] | 当前所有选手 |
| `clients` | dict[str, AsyncOpenAI\|None] | 名字 → 模型客户端；None 表示演示模式 |
| `demo_mode` | bool | 是否所有选手都无可用客户端 |
| `turn` | int | 当前回合数 |
| `running` | bool | 是否连续运行 |
| `step_flag` | bool | 单步标志，推进一回合后自动暂停 |
| `winner` | str\|None | 胜者名字；None 表示未结束 |
| `history` | list[dict] | 内存中最近最多 800 条日志 |
| `_rec_file` | file\|None | 当前回放 JSONL 文件句柄 |
| `_log_file` | file\|None | 当前比赛日志文件句柄 |
| `log_path` | str\|None | 当前日志文件路径 |
| `log_dir` | str | 日志目录，测试可覆盖 |
| `config_path` | str | `config.json` 路径，测试可覆盖 |
| `_stats_saved` | bool | 本局 ELO 是否已结算 |
| `_last_world_version` | int | 上次推送给前端的世界版本 |
| `max_turns` | int | 回合上限，0=无上限 |
| `game_over` | dict\|None | 终局结算信息（reason/rankings/titles） |
| `rain` | bool | 本回合是否暴雨 |
| `harvest_until` | int | 丰收季持续到的回合数（含） |

### `Agent`（`agent.py:6-181`）

每个选手对应一个 `Agent` 实例，保存状态、记忆、关系、感知逻辑。

| 字段 | 类型 | 含义 |
|------|------|------|
| `id` | int | 选手在 `config["agents"]` 中的索引 |
| `name` | str | 名字 |
| `emoji` | str | 头像映射键 |
| `provider` | str | provider 键 |
| `model` | str | 模型名 |
| `role` | str | 角色名 |
| `backstory` | str | 背景 |
| `personality` | str | 性格 |
| `strategy` | str | 策略 |
| `traits` | dict | {aggression, sociability, greed, paranoia} |
| `hp` | int | 生命值 0~100 |
| `energy` | int | 能量 0~100 |
| `pos` | tuple[int,int] | 坐标 (x,y) |
| `items` | dict | {"food": int, "ore": int} |
| `weapon` | bool | 是否有武器 |
| `weapon_durability` | int | 武器耐久 |
| `kills` | int | 本局击杀数 |
| `usage` | dict | prompt/completion/cache_hit/cache_miss/cache_est |
| `alive` | bool | 是否存活 |
| `state` | str | "存活" / "死亡" |
| `relation` | dict[str,int] | 名字 → 关系分 |
| `memory` | deque(maxlen=18) | 短期见闻 |
| `notes` | list[str] | 长期笔记，最多 10 条 |
| `pending_trade` | dict\|None | 待处理交易 |
| `last_attacker` | str\|None | 上次攻击自己的人 |
| `last_talk` | int | 上次说话回合 |
| `last_thought` | str | 本回合想法 |

### `World`（`world.py:9-164`）

| 字段 | 类型 | 含义 |
|------|------|------|
| `w`, `h` | int | 地图宽高 |
| `rng` | random.Random | 固定 seed 的随机数生成器 |
| `grid` | list[list[str]] | 二维地形数组 |
| `deposits` | dict[(x,y), int] | 矿脉剩余储量 |
| `depleted` | dict[(x,y), str] | 采空格子 → 原矿脉类型 |
| `agents` | list[Agent] | 由 engine 填充 |
| `pending_trades` | list[dict] | 当前挂单 |
| `version` | int | 地形/矿脉变化版本号 |
| `night` | bool | 是否夜晚 |
| `harvest` | bool | 是否丰收季 |
| `damage_mult` | float | 攻击伤害倍率 |
| `gather_mult` | float | 采集成功率倍率 |
| `energy_drain` | float | 每回合能量消耗（仅提示词用） |
| `hp_drain` | float | 能量归零后生命损耗（仅提示词用） |

### `TurnCtx`（`engine.py:56-63`）

轻量级上下文对象，每个回合创建一个，用于统一日志：

```python
class TurnCtx:
    def __init__(self, engine, turn):
        self.engine = engine
        self.turn = turn

    def log(self, kind, text):
        self.engine.emit(kind, text)
```

---

## 🔄 主循环详解

### 生命周期

服务器启动时（`main.py:51-57`）：

1. 读取 `config.json`。
2. 创建 `Engine(config, hub)`。
3. 在 FastAPI lifespan 中启动 `engine.loop()` 后台任务。
4. 服务器关闭时取消该任务。

`Engine.reset()` 初始化流程（`engine.py:153-203`）：

1. `self.world = World(self.config)` 生成地图。
2. `self.world.spawn_points(n)` 获取不重复出生点。
3. 为每个配置创建 `Agent`，分配位置。
4. 清空历史、胜者、事件状态。
5. 打开新的 `.log` 和 `.jsonl` 文件。
6. 为每个 agent 构建 LLM 客户端；无 Key 则为 `None`。
7. 判断 `demo_mode`。
8. 发送系统公告。

### 一回合完整时序

`run_turn()`（`engine.py:944-1118`）的完整流程：

#### 阶段 1：回合准备

```
turn += 1
world = self.world  # 保存本回合使用的 world 引用
ctx = TurnCtx(self, self.turn)
alive = [a for a in self.agents if a.alive]
```

- 保存 `world` 引用是为了阶段 4 的 reset 竞态防护。

#### 阶段 2：昼夜与事件

1. 计算 `night = (turn - 1) % CYCLE_LEN >= DAY_LEN`。
2. 若 `night` 变化，更新 `world.night` 并公告。
3. 设置 `world.harvest = self.turn <= self.harvest_until`。
4. 调用 `world.regen()` 进行资源再生。
5. 调用 `self.roll_world_event(ctx)` 触发世界事件。

#### 阶段 3：并行决策

对每个存活 agent 并发执行 `decide(a)`：

```python
async def decide(a):
    if self.clients.get(a.name) is None:
        act, args = demo_decide(a, world)
        return act, args, None, None
    # 否则调用 LLM
    msgs = [
        {"role": "system", "content": a.system_prompt()},
        {"role": "user", "content": a.perceive(world, self.turn)},
    ]
    # 重试 1 次
    for attempt in (0, 1):
        try:
            act, args, thinking, usage = await llm_act(...)
            # 累计 usage
            return act, args, thinking, usage
        except Exception:
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                # 日志报错，降级为 demo_decide
```

关键点：

- 所有真实模型调用是并发的（`asyncio.gather`，`engine.py:1010`）。
- 失败重试 1 次，间隔 2 秒。
- 仍失败则本回合由演示规则代打。

#### 阶段 4：reset 竞态防护

```python
if world is not self.world:
    return
```

- 并行决策期间，如果用户点击「重置」，`engine.reset()` 会替换 `self.world`。
- 旧回合拿到的是旧的 `world` 引用，与新 `self.world` 不一致时直接 `return`，避免用新世界结算旧决策。
- 这是 `tests/test_regressions.py:69-83` 验证的核心竞态防护。

#### 阶段 5：随机顺序结算

```python
order = alive[:]
random.shuffle(order)
for a in order:
    action, args, thinking, _ = decisions[alive.index(a)]
    # 规范化 action
    # 计算 thinking
    # 调用 tools.RESOLVE[action](a, world, args, ctx)
```

- 随机顺序消除先手优势。
- 未知/空 action fallback 为 `wait`。
- 每个行动的反馈写入该 agent 记忆，日志广播给所有前端。

#### 阶段 6：被动消耗

```python
drain = self.difficulty("energy_drain") + (3 if self.rain else 0)
hp_drain = self.difficulty("hp_drain")
for a in self.agents:
    if not a.alive: continue
    a.energy = max(0, a.energy - drain)
    if a.energy <= 0:
        a.hp -= hp_drain
    if a.hp <= 0 and a.alive:
        a.alive = False
        a.state = "死亡"
```

#### 阶段 7：结束判定

```python
alive_now = [a for a in self.agents if a.alive]
if len(alive_now) <= 1:
    self.winner = alive_now[0].name if alive_now else None
    self.running = False
    self.emit(...)
    self.update_stats()
```

### 阶段 8：解说、反思与全局复盘（非阻塞）

#### 全局复盘

游戏结束后，引擎会从最近约 100 条公开事件中挑选素材，调用解说员客户端生成一段中文全局复盘。成功后将文本写入 `match_review`，以独立 `review` 消息广播，并进入日志流；`reset()` 会取消未完成的任务并清空该字段。无可用 API Key 时自动使用模板化降级。

回合结算后、快照前，引擎会按配置触发三个可选的后台任务：

1. **AI 解说员**：每 `commentary_interval` 回合（默认 5，0=关闭），从最近公开日志中挑选战斗/死亡/交易/结盟/上帝/事件类记录，调用一个独立 LLM 生成 1-2 句中文点评，以 `kind=commentary` 广播。演示模式自动关闭（`engine.py:775-784`）。
2. **定期反思**：每 `reflect_interval` 回合（默认 10，0=关闭），为每个有真实模型的存活代理调用其自身模型，要求用一句话总结局势与打算；结果以 `[反思] ` 前缀写入 `notes`，并以 `think` 日志广播。演示模式跳过（`engine.py:808-840`）。
3. **AI 全局复盘**：游戏结束（歼灭或回合上限）后，挑选最近约 100 条公开事件，调用解说员客户端（或第一个可用 provider）生成约 200 字的中文复盘；无可用 Key 时使用模板化降级。结果写入 `match_review`，随 snapshot 携带，并以独立 `type=review` 消息广播，同时以 `kind=review` 进入日志流（`engine.py:846-866`）。

三者都通过 `asyncio.create_task` 非阻塞执行，且最多只允许一个同类任务在跑；调用失败静默跳过，不影响主循环。`reset()` 会取消未完成的复盘任务并清空 `match_review`。

相关代码：`engine.py:775-1118`。

### 广播流程

- `emit()` 同时做三件事：追加到内存 `history`、写 `.log` 文件、通过 `Hub.send()` 广播（`engine.py:212-226`）。
- `Hub.send()` 并行发送给所有连接，失败连接自动剔除（`main.py:27-44`）。
- 每回合结束发送 `snapshot`（`engine.py:939`）。

---

## ✍️ 提示词工程

### system / user 结构

每次模型调用由两条消息组成（`engine.py:968-971`）：

- `system`：固定人设模板（`agent.py:104-116`）。
- `user`：动态世界情报，按稳定性重排（`agent.py:118-181`）。

### 真实 system 消息示例

以 `config.json` 中的「陈默」为例，`system_prompt()` 生成：

```
你是「陈默 🕸️」，被害妄想症患者。
人物设定：曾经被人背叛到一无所有，从此坚信所有人靠近他都是别有用心。在他的世界里，没有路人，只有还没动手的敌人。
性格：极度多疑、神经质、过度解读一切：别人一句寒暄是'在套话'，一次偶遇是'在跟踪'，沉默是'在密谋'。会把自己的被迫害剧本讲得绘声绘色，先下手为强后还坚信自己是自卫。
处世策略：时刻记录每个人的'可疑行径'；谁靠近就警告谁，警告无效就先发制人；绝不背对任何人，绝不相信任何盟约——盟友只是更方便下手的敌人。
特质：攻击性 0.6 / 社交性 0.1 / 贪婪 0.5 / 多疑 0.98（0~1）

你正身处一个生存沙盒世界，和其他几个「模型代理」生活在一起。你可以自由决定：合作、交易、结盟、欺骗、掠夺、攻击……一切取决于你的判断。你的终极目标是：活下去，并尽可能发展壮大。扮演好你自己，像真人一样思考和行动。

【行动要求】
- 每回合调用一个工具。调用工具时，必须在参数里带上 reason 字段，用一句话写出你此刻的思考与行动理由（例如"南边好像有矿脉，先去占住"）。
- reason 会被观战者看到，但其他代理看不到你的内心想法，可以放心写。
- 说话（talk）完全免费，是了解他人、谈判、试探、挑衅的唯一手段。不要闷头当独行侠——情报就是生命。
```

来源字段：

| 内容片段 | 来源字段/代码 |
|----------|---------------|
| 名字 + emoji | `cfg["name"]` + `cfg["emoji"]`（`agent.py:9-10`） |
| 角色 | `cfg["role"]`（`agent.py:13`） |
| 人物设定 | `cfg["backstory"]`（`agent.py:14`、`agent.py:106`） |
| 性格 | `cfg["personality"]`（`agent.py:15`、`agent.py:107`） |
| 处世策略 | `cfg["strategy"]`（`agent.py:26`、`agent.py:108`） |
| 特质数值 | `self.traits`（`agent.py:17-25`、`agent.py:109`） |
| 行动要求 | 固定文本（`agent.py:113-116`） |

### 真实 user 消息示例

第 1 回合白天，陈默位于 (9,3)，附近只有陛下：

```
【世界规则】
- 每回合你必须且只能执行一个行动。回合不断循环：每回合能量自动-2；能量归零后每回合生命-3。
- 🍞 吃食物：生命+12。😴 休息：能量+20。采集：草地30%捡到食物，森林50%找到野果，f/o 矿脉直接采集（矿脉会耗尽）。
- ⚔️ 攻击：消耗5能量，伤害8-14（有武器+10），会结仇，被打的人会记住你。武器有耐久，用多了会碎。
- ⛏️ 3块矿石可打造武器（攻击+10）。你可以和其他人交易食物/矿石。
- 你只能看到视野内的人，看不到的人也无法 inspect；距离你4格内的人说话你能听到；全场大喊也能听到（但会暴露你的位置）。
- 你的选择完全自由：和平共处、结盟、垄断资源、见人就打、背后偷袭……都行。用工具执行行动；拿不定主意就用 wait。

【你的状态】
❤️ 生命 100/100 | ⚡ 能量 100/100 | 📍 位置 (9,3)
🍞 食物 x2 | ⛏️ 矿石 x0 | 🗡️ 武器 无

【你与所有代理的关系】白夜:中立(+0)；屠夫:中立(+0)；陛下:中立(+0)；松鼠:中立(+0)；藤蔓:中立(+0)
【你的长期笔记】无
【你视野内的人】（视野 6 格）陛下👑(4格)
【待处理交易】无

【你周围的环境】（5x5，你=你，f=食物矿，o=矿石矿，F=森林，~=水，M=山，?=视野外）
.MMo.
~....
FF你.~
~~..~
.F..F

【最近的见闻】
[T0] [公告] 这片土地上有 6 名幸存者，生存不易。合作或对抗，由你们自己决定。

当前：第 1 回合 · 🌞 白天
```

### 前缀稳定性重排

为适配 DeepSeek「前缀完整匹配」的硬盘缓存计费，`perceive()` 把 user 消息按「最稳定 → 最易变」排序（`agent.py:148-153`）：

| 顺序 | 段落 | 稳定性 | 说明 |
|------|------|--------|------|
| 1 | 【世界规则】 | 最高 | 整局恒定（含难度参数与夜晚偷袭规则，均无条件静态描述） |
| 2 | 【长期笔记】/ 关系 / 待处理交易 | 高 | 仅 remember / 冲突 / 报价时变化 |
| 3 | 【视野内的人 / 尸体】 | 中高 | 随位置变化 |
| 4 | 【你的状态】 | 低 | 能量每回合 -2，**每回合必变**，刻意靠后 |
| 5 | 【5x5 小地图】/【最近的见闻】/ 回合昼夜 | 最低 | 每回合都变，放最后 |

实测效果（含 system 消息）：连续两回合前缀稳定率约 84%，昼夜切换约 79%。

测试保证：

- `test_perceive_starts_with_rules`：user 消息以「【世界规则】」开头。
- `test_turn_number_only_at_end`：回合号只出现在最后一行。
- `test_prefix_stable_across_turns_when_state_unchanged`：状态不变时前 50% 字符完全相同。

### 缓存命中率统计

`llm.py:85-91` 读取响应 `usage`：

- `prompt_tokens`
- `completion_tokens`
- `prompt_cache_hit_tokens`（DeepSeek 特有）
- `prompt_cache_miss_tokens`（DeepSeek 特有）

### 本地缓存命中率估算

当 provider 不返回缓存字段时（如硅基流动），引擎按相邻两回合提示词的公共前缀占比估算：

```python
prompt_text = msgs[0]["content"] + "\n" + msgs[1]["content"]
prev_prompt = getattr(a, "_last_prompt", "")
common = os.path.commonprefix([prompt_text, prev_prompt])
ch = round(len(common) / max(1, len(prompt_text)) * usage["prompt"])
cm = max(0, usage["prompt"] - ch)
```

（`engine.py:961-1008`）

算法逻辑：

1. 把当前 system + user 拼接成完整提示词文本。
2. 与上一回合的完整提示词文本取最长公共前缀。
3. 公共前缀长度 / 当前总长度 ≈ 缓存占比。
4. 用该占比 × 当前 prompt token 数，得到估算的 cache hit token。

局限性：

- 这只是字符级前缀匹配，不是真实 token 级缓存匹配。
- 若模型实际按 token 切分与字符边界不一致，估算会偏差。
- 不适用于 system 消息变化（如换选手人设）的情况。
- 对短提示词误差更大。

前端在 `cache_est=True` 时显示 `~缓存 XX%`（`engine.py:426`、`app.js:289`）。

---

## 🔧 工具系统

### Schema 定义

`tools.TOOL_SCHEMAS`（`tools.py:7-26`）是一个 OpenAI function calling 格式的 schema 列表，共 19 个工具：

`move`、`gather`、`rest`、`eat`、`attack`、`talk`、`shout`、`whisper`、`inspect`、`loot`、`craft`、`give`、`propose_trade`、`accept_trade`、`decline_trade`、`remember`、`mark_ally`、`mark_enemy`、`wait`。

每个 schema 最后会被注入可选的 `reason` 字段（`tools.py:29-34`）。

### RESOLVE 注册机制

`tools.RESOLVE`（`tools.py:314-333`）是 `action_name → 结算函数` 的字典。

新增工具步骤：

1. 在 `TOOL_SCHEMAS` 中增加 schema。
2. 实现 `resolve_xxx(a, world, args, ctx)`，返回 `(feedback_string, logs_list)`。
3. 在 `RESOLVE` 中注册 `"xxx": resolve_xxx`。
4. 在 `agent.py` 的【世界规则】段补一句说明（否则模型不知道能用）。
5. 在 `engine.CANNED_THINKING` 中补充兜底想法。
6. 补测试。

### 结算返回值约定

每个 `resolve_*` 函数必须返回一个二元组：

```python
(feedback: str, logs: list[tuple[str, str]])
```

- `feedback`：写入该 agent 记忆的文本，前缀为 `[行动结果] ...`。
- `logs`：每条日志是 `(kind, text)`，会被 `ctx.log(kind, text)` 广播。

若执行过程抛异常，外层会捕获并生成 `(f"行动执行出错：{e}", [])`（`engine.py:1016-1017`）。

### 日志 kind 一览表

| kind | 含义 | 前端过滤归类 | 典型触发 |
|------|------|--------------|----------|
| `talk` | 对话 | 对话 | `talk` / `shout` / `whisper` |
| `think` | 选手想法 | 思考 | 每回合决策后 |
| `fight` | 战斗 | 战斗 | `attack`（未致死）/ 武器碎裂 |
| `death` | 死亡/击杀 | 战斗 | `attack` 致死 / 兽群 / 精疲力竭 |
| `trade` | 交易 | 交易 | `propose_trade` / `accept_trade` / `decline_trade` |
| `item` | 物品获得/使用 | 系统 | `gather` / `eat` / `loot` / `craft` |
| `move` | 移动/休息/待命 | 系统 | `move` / `rest` / `wait` |
| `sys` | 系统公告 | 系统 | 重置、昼夜切换、结盟/敌对宣言 |
| `god` | 上帝消息 | 系统 | `god_msg` / `god` |
| `event` | 世界事件 | 系统 | 暴雨 / 兽群 / 丰收季 |

前端过滤映射（`app.js:336-343`），其中 `review` 归入「系统」标签：

```js
const KIND_FILTER = {
  all: null,
  talk: ["talk"],
  think: ["think"],
  fight: ["fight", "death"],
  trade: ["trade"],
  sys: ["sys", "move", "item", "god", "event"],
};
```

### 结算示例

`resolve_attack`（`tools.py:105-132`）：

- 校验目标存活、距离 ≤2、自身能量 ≥5。
- 消耗 5 能量。
- 计算伤害 `(random.randint(8,14) + (10 if weapon else 0)) * damage_mult`。
- 扣目标 HP，更新关系（攻击者 -4，目标 -6）。
- 若持武器，耐久 -1，归零则碎裂。
- 若目标 HP ≤0，死亡，攻击者 kills +1。
- 返回反馈与日志。

`resolve_propose_trade` / `resolve_accept_trade` / `resolve_decline_trade`（`tools.py:213-281`）：

- 提出：距离 ≤4，物品为 food/ore，数量 ≥1，自己有足够出价物，对方无待处理交易。
- 接受：复核对方存活、距离 ≤4、双方物品充足；成功后物品互换，关系各 +3。
- 拒绝：取消挂单，不影响关系。

---

## 🌍 世界生成与再生

### 地图生成

`World._generate()`（`world.py:35-50`）在固定 seed 下随机生成：

| 地形 | 生成方式 | 大致占比 |
|------|----------|----------|
| 水域 `~` | blob 随机游走 | 约 5% |
| 山地 `M` | blob 随机游走 | 约 5% |
| 森林 `F` | blob 随机游走 | 约 12% |
| 食物矿 `f` | 随机空地，储量 3~6 | 约 3% |
| 矿石矿 `o` | 随机空地，储量 3~6 | 至少 2 个，约 1.5% |
| 平地 `.` | 默认填充 | 其余 |

出生点通过 `_free_spot()` 随机寻找空地（`world.py:112-118`）。

### 版本号与增量

`world.version` 初始 0。变化时 +1：

- `consume()` 采矿时 +1（`world.py:89`）。
- `regen()` 有变化时 +1（`world.py:110`）。

引擎通过比较 `world.version != _last_world_version` 决定是否携带完整 `grid` 推送（`engine.py:429-432`）。

### 昼夜与事件

- `world.night` 由 engine 每回合维护（`engine.py:963-965`）。
- `world.harvest` 标志用于丰收季产出翻倍（`engine.py:967`、`tools.py:66`）。
- 事件触发概率由难度参数 `event_prob` 控制（`engine.py:663`）。

### 难度参数表

`Engine.DIFFICULTY`（`engine.py:294-302`）：

| 键 | 默认 | 最小 | 最大 | 作用位置 |
|----|------|------|------|----------|
| `energy_drain` | 2 | 0 | 5 | 每回合被动扣能量（`engine.py:1054`） |
| `hp_drain` | 3 | 0 | 10 | 能量为 0 时扣血（`engine.py:1057`） |
| `damage_mult` | 1.0 | 0.5 | 2.0 | 最终伤害乘数（`tools.py:115`） |
| `event_prob` | 0.08 | 0 | 0.3 | 世界事件触发概率（`engine.py:663`） |
| `gather_mult` | 1.0 | 0.5 | 2.0 | 草地/森林采集成功率乘数（`tools.py:67`） |

`max_turns` 单独读取，默认 300、0=无上限（`engine.py:310`）。

---

## 🏅 ELO 结算与 stats.json

### 结算时机

一局结束时 `update_stats()` 被调用（`engine.py:1113`），只执行一次（`engine.py:546-550`）。

### 键

以 `名字|模型` 作为唯一键（`engine.py:560-561`）。

### 字段

```json
{
  "陈默|deepseek-v4-flash": {
    "name": "陈默",
    "model": "deepseek-v4-flash",
    "games": 1,
    "wins": 1,
    "kills": 0,
    "elo": 1000
  }
}
```

### 规则

- 所有参赛者 `games + 1`，`kills` 累加本局击杀（`engine.py:563-569`）。
- 若有唯一胜者，胜者对每个败者按标准 ELO 公式结算（`engine.py:577-583`）：
  - `e = 1 / (1 + 10 ** ((ls["elo"] - ws["elo"]) / 400))`
  - 胜者：`elo += ELO_K * (1 - e)`
  - 败者：`elo -= ELO_K * (1 - e)`
- `K = 24`，初始 `elo = 1000`（`engine.py:21-22`）。
- 全员覆灭不算胜，不调 ELO（`engine.py:570` 因 `self.winner is None` 跳过）。
- 称号从 `game_over.titles` 累计到每个选手的 `titles` 字段（`engine.py:583-589`）。
- 写入为原子操作：先写 `.tmp` 再 `os.replace`（`engine.py:592-596`）。

### 评分与称号

上限终局时调用 `_compute_rankings()`（`engine.py:492-508`）排序：

```python
key = (alive, kills, resource_score, relation_total, -id)
```

- `resource_score = food + ore*2 + (weapon ? 10 : 0)`
- 全部相同时用关系总分 tie-break，再相同按 `config` 出场顺序（id 小者优先）。

称号由 `_compute_titles()`（`engine.py:510-543`）计算：

| 称号 | 规则 |
|------|------|
| 生存冠军 | 评分/排序第一名 |
| 霸主 | 击杀最多且 >0；并列按关系总分/出场顺序 |
| 富翁 | 存活者中资源分最高，无存活则全体中取 |
| 外交家 | 正关系总分最高且 >0 |

`update_stats()` 把这些称号累计进 `stats.json` 每个选手的 `titles` 字段。

---

## 📦 增量快照、回放、日志与导出

### 增量快照

`snapshot()`（`engine.py:429-471`）返回字段：

- `turn`, `running`, `winner`, `speed`, `demo`
- `max_turns`: 回合上限
- `game_over`: 终局结算信息（未结束为 `null`）
- `match_review`: AI 全局复盘文本（未生成或重置后为 `null`）
- `day_night`, `cycle_turn`
- `world_version`
- `world`: 始终含 `w`/`h`；仅当 `full=True` 或 `world.version` 变化时才含 `grid` 与 `deposits`
- `providers`: 展示信息，不含 `api_key`
- `agents`: 完整状态数组

前端在 `applyMsg()` 中：若 snapshot 没带 `grid`，则沿用上一份缓存（`app.js:41-65`）；若收到 `type=review` 消息，则更新结算面板并写入日志流（`app.js:56-60`、`app.js:495-503`）。

### 回放录制

`_open_recorder()`（`engine.py:87-120`）每局创建新的 JSONL 文件：

- 首行 `type: meta`，含选手摘要。
- 之后每行一条广播消息（`log`、`status`、`snapshot`）。

`Hub.send()` 在广播时同步调用 `recorder` 回调落盘（`main.py:29-34`）。

### 日志落盘

`_open_logfile()` / `_write_log()`（`engine.py:123-150`）把每条 `emit` 的日志追加到 `logs/match_*.log`：

```
[T0] [sys] 🔄 世界已重置...
[T1] [fight] ⚔️ 甲 攻击 乙...
...
===== 本局结束：胜者 甲，共 23 回合 =====
```

### 一键导出

`export_data()`（`engine.py:601-657`）返回 JSON：

- 优先使用 `logs/*.log` 文件中的完整日志；若内存 `history` 更长则用内存。
- 包含 `meta`、`agents`、`logs`、`events`。
- `meta.review` 携带本局 AI 复盘文本（未生成则为 `null`）。
- 绝不包含 `api_key`。

---

## 🎨 前端架构

### 渲染管线

前端渲染分为三层：

1. **DOM 层**：顶栏、卡片、日志、浮层面板。
2. **离屏地形缓存层**：`terrainCv` canvas，按 `world_version` 重建（`app.js:90-93`）。
3. **rAF 动画层**：`drawFrame()` 在 `requestAnimationFrame` 循环中绘制（`app.js:183-268`）。

#### 离屏地形缓存

```js
const terrainCv = document.createElement("canvas");
let terrainVer = -1;
```

- 当 `s.world_version !== terrainVer` 时，调用 `buildTerrain(s)` 重建缓存（`app.js:135`）。
- 重建内容包括：每个格子的底色、圆角、地形图标、矿脉储量数字。
- 窗口 resize 或 DPR 变化时，`terrainVer` 置 -1 强制重建（`app.js:113`、`app.js:133`）。

#### rAF 动画层

`drawFrame()`（`app.js:183-268`）每帧执行：

1. 清空主 canvas。
2. 绘制离屏地形（按逻辑尺寸 `logicalW × logicalH`）。
3. 叠加夜晚蒙版（透明度渐变过渡）。
4. 对每个 agent：
   - 插值当前显示坐标到目标坐标（lerp 因子 0.22）。
   - 若刚掉血，绘制红色受击圆环。
   - 若死亡，绘制 skull 放大淡入动画。
   - 否则绘制头像圆圈和名字。

#### DPR 适配

`setupDPR(cv, logicalW, logicalH)`（`app.js:102-111`）：

```js
const dpr = window.devicePixelRatio || 1;
cv.width = Math.floor(logicalW * dpr);
cv.height = Math.floor(logicalH * dpr);
cv.style.width = logicalW + "px";
cv.style.height = logicalH + "px";
const ctx = cv.getContext("2d");
ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
```

- 内部像素 = 逻辑尺寸 × DPR，保证 HiDPI 清晰。
- CSS 尺寸保持逻辑像素，后续绘制代码全按逻辑坐标调用。
- `drawImage` 时必须指定逻辑目标尺寸，否则 dpr>1 时会放大 dpr 倍（`app.js:195`）。

### SVG 图标库

`icons.js` 暴露三个 API：

#### `icon(name, size = 16)`

返回内联 SVG 字符串，用于 DOM 拼接。例如：

```js
icon("heart", 11)
// 返回：<svg class="icon" width="11" height="11" viewBox="0 0 24 24" ...>...</svg>
```

#### `drawIcon(ctx, name, cx, cy, size, color, alpha)`

用 `Path2D` 把图标画到 canvas。内部使用 24×24 坐标系，通过 `scale(size/24)` 等比缩放。

#### `avatarIconName(emoji)`

把 config 里的选手 emoji 映射为头像图标名（`web/icons.js:51-62`）：

| emoji | 图标 |
|-------|------|
| 🕸️ | `web` |
| 🎭 | `mask` |
| 🔪 | `knife` |
| 👑 | `crown` |
| 🐿️ | `acorn` |
| 🥀 | `rose` |
| 🤖 | `robot` |
| 其他 | 兜底 `robot` |

HTML 中 `<i class="ic" data-icon="play" data-size="14"></i>` 在水合时被替换为 SVG（`web/icons.js:94-98`）。

### 增量快照缓存合并

前端收到 snapshot 时（`app.js:41-65`）：

1. 若 `m.world` 存在但没有 `grid`，从 `state.snapshot.world` 复用 `grid` 和 `deposits`。
2. 更新 `state.snapshot`。
3. 同步 `state.running` 与胜者横幅。
4. 触发 `render()`：重建地形缓存（若 version 变）、更新选手卡片、同步状态。

回放模式下通过从头顺序 apply 到目标索引，保证增量缓存正确（`app.js:936-941`）。

---

## 🧠 设计决策记录

### 为什么交易要复核距离？

`accept_trade` 在成交前重新检查双方距离 ≤4（`tools.py:255-257`）。这是为了防止：

- 报价后一方跑远，另一方仍接受，造成隔空交易。
- 报价方已移动到另一处继续战斗/采集，交易应自然作废。

如果复核失败，挂单会被取消，物品不交换（`tests/test_regressions.py:117-129`）。

### 为什么 `mark_ally` 是钳制到 ≥+3 而非累加？

```python
a.relation[t.name] = max(a.relation.get(t.name, 0), 3)
```

（`tools.py:298`）

原因：

- 结盟是一个明确的「状态跃迁」，不是慢慢堆好感。
- 避免模型反复 `mark_ally` 刷出极高正分。
- 与 `mark_enemy` 对称：后者直接钳制到 ≤-3（`tools.py:306`）。

### 为什么 `reason` 对其他代理不可见？

`reason` 字段只用于：

- 前端日志的 `think` 行（观战者可见）。
- 作为 `last_thought` 显示在选手卡片上。

它不会被写入任何其他 agent 的记忆，也不会进入 `talk`/`shout`/`whisper` 的消息内容。这样模型可以放心地写出真实策略，而不用担心被对手利用。

### 为什么攻击关系不对称（-4 / -6）？

- 攻击者扣目标 -4：表示主动攻击会降低自己对对方的好感。
- 目标对攻击者 -6：表示被打的人对攻击者更恨。
- 这种不对称让「先动手」在关系图中更快变成深仇，符合直觉。

### 为什么演示模式 AI 不会攻击盟友？

`_near_threat`（`llm.py:138-146`）只把关系 <0 或 `last_attacker` 匹配的人视为威胁。因此高 `aggression` 也不会让演示 AI 攻击盟友，除非对方先攻击过自己。

### 为什么 `history` 限制 800 条？

内存 `history` 限制 800 条（`engine.py:216-217`），新连接时只补发最近 800 条。原因：

- 避免内存无限增长。
- 完整日志已实时写入 `.log` 文件，导出时会优先以文件为准补全（`engine.py:607-617`）。

### 为什么上限结局用「关系总分」做并列 tie-break？

上限终局的排序主键是 `存活 > 击杀 > 资源分`。若多人在这三项上完全相同，则比较关系总分，再相同按出场顺序。

- 保留「必须有一个唯一胜者」的语义，避免多人并列第 1 时 ELO 结算复杂化。
- 关系总分是对选手外交影响力的量化，作为 tie-break 符合沙盒主题。
- 出场顺序是确定性的最后防线。

### 为什么 `world_version` 用整数而不是哈希？

- 整数比较足够判断「世界是否变化」。
- 增量推送只需要知道「变没变」，不需要知道「变成什么样」。
- 实现简单，无需计算 grid 哈希。
