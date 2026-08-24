# 📡 接口协议

本文档描述前后端通信协议：WebSocket 消息、HTTP API、文件格式。目标是让只读文档的开发者能独立实现客户端或扩展服务端。

---

## 🔌 WebSocket

连接地址：`ws://host:port/ws`（`main.py:62`）。

连接建立后，服务端会依次发送：

1. 一条 `snapshot`（`full=True`，含完整 `grid`）。
2. 一条 `status`。
3. 按顺序补发内存中最近最多 800 条 `log`。

### 客户端 → 服务端

#### 1. 播放控制 `cmd`

##### `start`

```json
{ "type": "cmd", "action": "start" }
```

- 行为：若当前未分胜负，设置 `running=True` 并广播 `status`。
- 边界：若 `winner is not None`，拒绝重复结算，返回 `status` 时 `running=False`（`main.py:77-83`）。

##### `pause`

```json
{ "type": "cmd", "action": "pause" }
```

- 行为：设置 `running=False` 并广播 `status`。
- 边界：即使已结束也生效，但无实际影响。

##### `step`

```json
{ "type": "cmd", "action": "step" }
```

- 行为：推进一个完整回合，然后自动暂停。
- 边界：已分胜负时无效（`main.py:87-93`）。

##### `reset`

```json
{ "type": "cmd", "action": "reset" }
```

- 行为：先停表，再调用 `engine.reset()`，发送全量 snapshot，清空胜者。
- 边界：随时可用。

##### `speed`

```json
{ "type": "cmd", "action": "speed", "value": 1.5 }
```

- 行为：设置 `engine.speed = value`。
- 范围：0.1~5.0；非法值会被忽略（`main.py:100-104`）。

#### 2. 开局设置 `setup` / `setup_save`

##### `setup`：应用配置并重开一局

```json
{
  "type": "setup",
  "agents": [
    {
      "name": "甲",
      "emoji": "🤖",
      "role": "幸存者",
      "provider": "deepseek",
      "model": "deepseek-v4-flash",
      "backstory": "",
      "personality": "",
      "strategy": "",
      "traits": { "aggression": 0.5, "sociability": 0.5, "greed": 0.5, "paranoia": 0.5 }
    }
  ],
  "world": {
    "energy_drain": 2,
    "hp_drain": 3,
    "damage_mult": 1.0,
    "event_prob": 0.08,
    "gather_mult": 1.0
  }
}
```

- 行为：校验 → 清洗 → 替换内存配置 → `engine.reset()` → 返回 `setup_result` → 广播全量 snapshot + status。
- 错误情况：运行中、少于 2 人、重名、缺必要字段等会返回 `ok=false`。

##### `setup_save`：保存到文件再应用

```json
{
  "type": "setup_save",
  "agents": [ ... ],
  "world": { ... }
}
```

- 行为：先原子写回 `config.json`，写成功后再执行与 `setup` 相同的应用逻辑。
- 关键：写文件失败则整体不生效（`engine.py:319-351`）。

#### 3. 上帝传话 `god_msg`

##### 单人/多人

```json
{ "type": "god_msg", "targets": ["陈默"], "text": "白夜在打听你", "sow": false }
```

##### 全体广播

```json
{ "type": "god_msg", "targets": "all", "text": "风暴将至", "sow": false }
```

##### 挑拨

```json
{ "type": "god_msg", "targets": ["陈默", "松鼠"], "text": "有人要独吞矿脉", "sow": true }
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `targets` | string 或 string[] | 是 | `"all"` 表示全体；数组表示具体选手名单 |
| `text` | string | 是 | 消息内容，会被截断到 200 字符 |
| `sow` | bool | 否 | 是否挑拨；仅当收件人 ≥2 时生效 |

#### 4. 上帝广播 `god`

```json
{ "type": "god", "text": "全体注意" }
```

- 行为：等效于 `targets: "all"`、`sow: false`，调用 `god_say()`。
- 与 `god_msg` 的区别：这是更简单的广播接口（`main.py:130-133`）。

---

### 服务端 → 客户端

#### 1. 全量快照 `snapshot`

##### 完整示例

```json
{
  "type": "snapshot",
  "turn": 12,
  "running": true,
  "winner": null,
  "speed": 0.6,
  "demo": false,
  "day_night": "night",
  "cycle_turn": 12,
  "world_version": 34,
  "world": {
    "w": 20,
    "h": 16,
    "grid": [
      [".", "F", "~", ".", "..."],
      ["..."]
    ],
    "deposits": {
      "5,3": 4,
      "11,7": 2
    }
  },
  "providers": {
    "deepseek": {
      "name": "DeepSeek",
      "models": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"]
    },
    "siliconflow": {
      "name": "硅基流动",
      "models": ["Qwen/Qwen3.5-35B-A3B", "Qwen/Qwen3-32B"]
    }
  },
  "agents": [
    {
      "id": 0,
      "name": "陈默",
      "emoji": "🕸️",
      "role": "被害妄想症患者",
      "provider": "deepseek",
      "model": "deepseek-v4-flash",
      "alive": true,
      "state": "存活",
      "hp": 67,
      "energy": 54,
      "pos": [9, 3],
      "items": { "food": 4, "ore": 1 },
      "weapon": true,
      "weapon_durability": 3,
      "kills": 1,
      "usage": {
        "prompt": 15420,
        "completion": 2180,
        "cost": 0.0482,
        "cache_hit": 10240,
        "cache_miss": 5180,
        "cache_rate": 0.66,
        "cache_est": false
      },
      "relations": { "白夜": -8, "屠夫": -6, "陛下": 0, "松鼠": 3, "藤蔓": -2 },
      "thought": "白夜又靠近了，先移动到森林边缘避开直线。",
      "notes": ["[T5] 白夜连续两回合接近", "[T9] 松鼠愿意交易"]
    }
  ]
}
```

##### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"snapshot"` |
| `turn` | int | 当前总回合数 |
| `running` | bool | 是否连续运行 |
| `winner` | string\|null | 胜者名字；未结束为 `null` |
| `speed` | float | 当前速度 |
| `demo` | bool | 是否全局演示模式 |
| `day_night` | string | `"day"` 或 `"night"` |
| `cycle_turn` | int | 当前周期内回合 1~24 |
| `world_version` | int | 世界版本号 |

##### `world` 字段

| 字段 | 类型 | 增量推送时是否可能缺失 | 说明 |
|------|------|------------------------|------|
| `w` | int | 否 | 地图宽度 |
| `h` | int | 否 | 地图高度 |
| `grid` | list[list[str]] | 是 | 二维地形数组；`world_version` 未变时不带 |
| `deposits` | dict[str,int] | 是 | 矿脉储量；`world_version` 未变时不带 |

增量规则：前端若收到不带 `world.grid` 的 snapshot，应沿用上一次的 `grid` 和 `deposits`（`app.js:41-44`）。

##### `agents` 元素字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 选手索引 |
| `name` | string | 名字 |
| `emoji` | string | emoji 头像键 |
| `role` | string | 角色 |
| `provider` | string | provider 键 |
| `model` | string | 模型名 |
| `alive` | bool | 是否存活 |
| `state` | string | `"存活"` / `"死亡"` |
| `hp` | int | 生命值 |
| `energy` | int | 能量值 |
| `pos` | [int,int] | 坐标 `[x,y]` |
| `items` | object | `{"food": int, "ore": int}` |
| `weapon` | bool | 是否有武器 |
| `weapon_durability` | int | 武器耐久 |
| `kills` | int | 本局击杀数 |
| `usage` | object | 见下方 usage 子字段表 |
| `relations` | object[str,int] | 名字 → 关系分 |
| `thought` | string | 本回合想法 |
| `notes` | string[] | 长期笔记 |

##### `usage` 子字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `prompt` | int | 累计 prompt token |
| `completion` | int | 累计 completion token |
| `cost` | float\|null | 估算费用（元）；未配单价时为 `null` |
| `cache_hit` | int | 累计缓存命中 token |
| `cache_miss` | int | 累计缓存未命中 token |
| `cache_rate` | float\|null | 缓存命中率；无数据时为 `null` |
| `cache_est` | bool | 是否为本地估算 |

#### 2. 日志 `log`

```json
{ "type": "log", "turn": 12, "kind": "fight", "text": "⚔️ 陈默 攻击 白夜，造成 17 点伤害（白夜 剩余 HP 48）" }
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 固定 `"log"` |
| `turn` | int | 发生回合 |
| `kind` | string | 日志类型，见下表 |
| `text` | string | 日志文本 |

`kind` 取值与前端过滤：

| kind | 含义 | 前端标签归类 |
|------|------|--------------|
| `talk` | 对话 | 对话 |
| `think` | 选手想法 | 思考 |
| `fight` | 战斗（未致死） | 战斗 |
| `death` | 死亡/击杀 | 战斗 |
| `trade` | 交易 | 交易 |
| `item` | 物品获得/使用 | 系统 |
| `move` | 移动/休息/待命 | 系统 |
| `sys` | 系统公告 | 系统 |
| `god` | 上帝消息 | 系统 |
| `event` | 世界事件 | 系统 |

#### 3. 状态 `status`

```json
{ "type": "status", "running": true, "winner": null }
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `running` | bool | 当前运行状态 |
| `winner` | string\|null | 胜者名字 |

触发时机：播放控制响应、胜负产生时。

#### 4. 设置结果 `setup_result`

```json
{ "type": "setup_result", "ok": true, "saved": true, "error": null }
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | 是否成功 |
| `saved` | bool | 是否为 `setup_save` 且保存成功 |
| `error` | string\|null | 失败原因 |

错误示例：

```json
{ "type": "setup_result", "ok": false, "saved": false, "error": "至少保留 2 名选手" }
```

---

## 🌐 HTTP API

### GET /api/export

下载当前这局的完整 JSON。

请求：

```http
GET /api/export HTTP/1.1
Host: 127.0.0.1:8080
```

响应头：

```http
Content-Disposition: attachment; filename="match_export.json"
Content-Type: application/json
```

响应体示例：

```json
{
  "meta": {
    "exported_at": "2026-08-24T12:00:00",
    "turn": 47,
    "finished": true,
    "winner": "屠夫",
    "demo": false
  },
  "agents": [
    {
      "name": "陈默",
      "emoji": "🕸️",
      "role": "被害妄想症患者",
      "provider": "deepseek",
      "model": "deepseek-v4-flash",
      "backstory": "...",
      "personality": "...",
      "strategy": "...",
      "traits": { "aggression": 0.6, "sociability": 0.1, "greed": 0.5, "paranoia": 0.98 },
      "alive": false,
      "hp": 0,
      "energy": 0,
      "items": { "food": 3, "ore": 0 },
      "weapon": false,
      "kills": 1,
      "relations": { "白夜": -8, "屠夫": -12 },
      "usage": { "prompt": 15420, "completion": 2180, "cost": 0.0482, "cache_hit": 10240, "cache_miss": 5180, "cache_rate": 0.66, "cache_est": false },
      "notes": ["[T5] 白夜连续两回合接近"]
    }
  ],
  "logs": [
    "[T0] [sys] 🔄 世界已重置，新的生存游戏开始！",
    "[T1] [move] 🚶 陈默 移动到 (10,3)",
    "...",
    "===== 本局结束：胜者 屠夫，共 47 回合 ====="
  ]
}
```

实现见 `engine.py:474-524`、`main.py:140-146`。

### GET /api/setup

返回设置面板所需数据（不含 `api_key`）。

请求：

```http
GET /api/setup HTTP/1.1
```

响应体示例：

```json
{
  "agents": [
    {
      "name": "陈默",
      "emoji": "🕸️",
      "role": "被害妄想症患者",
      "provider": "deepseek",
      "model": "deepseek-v4-flash",
      "backstory": "...",
      "personality": "...",
      "strategy": "...",
      "traits": { "aggression": 0.6, "sociability": 0.1, "greed": 0.5, "paranoia": 0.98 }
    }
  ],
  "providers": {
    "deepseek": { "name": "DeepSeek", "models": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"] },
    "siliconflow": { "name": "硅基流动", "models": ["Qwen/Qwen3.5-35B-A3B"] }
  },
  "world": {
    "energy_drain": 2,
    "hp_drain": 3,
    "damage_mult": 1.0,
    "event_prob": 0.08,
    "gather_mult": 1.0
  }
}
```

实现见 `main.py:149-159`。

### GET /api/stats

返回 `stats.json` 中的跨局战绩。

请求：

```http
GET /api/stats HTTP/1.1
```

响应体示例：

```json
{
  "陈默|deepseek-v4-flash": {
    "name": "陈默",
    "model": "deepseek-v4-flash",
    "games": 5,
    "wins": 1,
    "kills": 3,
    "elo": 1012
  },
  "屠夫|deepseek-v4-flash": {
    "name": "屠夫",
    "model": "deepseek-v4-flash",
    "games": 5,
    "wins": 2,
    "kills": 7,
    "elo": 1035
  }
}
```

- 若 `stats.json` 不存在或读取失败，返回 `{}`。
- 实现见 `main.py:162-171`。

### GET /api/replays

返回回放文件列表，按修改时间新→旧排列。

请求：

```http
GET /api/replays HTTP/1.1
```

响应体示例：

```json
[
  { "name": "match_20260824_120000.jsonl", "size": 15234, "mtime": 1758619200.0 },
  { "name": "match_20260824_115500.jsonl", "size": 28760, "mtime": 1758618900.0 }
]
```

- 只返回 `.jsonl` 文件。
- 若 `replays/` 目录不存在，返回 `[]`。
- 实现见 `main.py:174-189`。

### GET /api/replays/{name}

返回指定 JSONL 回放文件的完整文本。

请求示例：

```http
GET /api/replays/match_20260824_120000.jsonl HTTP/1.1
```

响应头：

```http
Content-Type: text/plain; charset=utf-8
```

响应体：文件原始内容，每行一条 JSON。

错误情况：

| 情况 | HTTP 状态码 | 响应体 |
|------|-------------|--------|
| 文件名不以 `.jsonl` 结尾 | 404 | `{"detail":"回放不存在"}` |
| 路径穿越（如 `../config.json`） | 404 | `{"detail":"回放不存在"}` |
| 文件不存在 | 404 | `{"detail":"回放不存在"}` |

校验逻辑见 `main.py:192-200`。

---

## 📁 文件格式

### replays/*.jsonl

每局录制一个 JSONL 文件，文件名 `match_YYYYMMDD_HHMMSS.jsonl`，同一秒重名时追加 `_2`、`_3`（`engine.py:78-83`）。

首行 meta：

```json
{
  "type": "meta",
  "config_agents": [
    { "name": "陈默", "emoji": "🕸️", "role": "被害妄想症患者", "provider": "deepseek", "model": "deepseek-v4-flash" },
    { "name": "白夜", "emoji": "🎭", "role": "病理性说谎者", "provider": "siliconflow", "model": "Qwen/Qwen3.5-35B-A3B" }
  ]
}
```

后续每行一条广播消息：

```json
{ "type": "status", "running": true, "winner": null }
{ "type": "log", "turn": 1, "kind": "sys", "text": "🌞 天亮了，视野恢复。" }
{ "type": "snapshot", "turn": 1, "running": true, "winner": null, "speed": 0.6, "demo": false, "day_night": "day", "cycle_turn": 1, "world_version": 1, "world": { "w": 20, "h": 16, "grid": [ ... ], "deposits": { ... } }, "providers": { ... }, "agents": [ ... ] }
```

### logs/*.log

每局一个纯文本日志文件，文件名 `match_YYYYMMDD_HHMMSS.log`。

示例内容：

```
[T0] [sys] 🔄 世界已重置，新的生存游戏开始！
[T0] [sys] 📢 公告：这片土地上有 6 名幸存者。生存不易，合作或对抗，由你们自己决定。
[T1] [sys] 🌞 天亮了，视野恢复。
[T1] [move] 🚶 陈默 移动到 (10,3)
[T1] [item] 🍞 白夜 捡到食物
[T1] [think] 💭 屠夫 想：先移动探路，摸清地形
[T2] [fight] ⚔️ 屠夫 攻击 陈默，造成 15 点伤害（陈默 剩余 HP 85）
[T5] [death] 💀 白夜 被 陛下 杀死！掉落了 {'food': 4, 'ore': 1}
...
===== 本局结束：胜者 屠夫，共 47 回合 =====
```

### stats.json

跨局累计战绩，键为 `名字|模型`：

```json
{
  "陈默|deepseek-v4-flash": {
    "name": "陈默",
    "model": "deepseek-v4-flash",
    "games": 5,
    "wins": 1,
    "kills": 3,
    "elo": 1012
  },
  "白夜|Qwen/Qwen3.5-35B-A3B": {
    "name": "白夜",
    "model": "Qwen/Qwen3.5-35B-A3B",
    "games": 5,
    "wins": 0,
    "kills": 2,
    "elo": 988
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 选手名字 |
| `model` | string | 模型名 |
| `games` | int | 参赛场次 |
| `wins` | int | 胜利场次 |
| `kills` | int | 累计击杀 |
| `elo` | int | ELO 积分（初始 1000，K=24） |

---

## 🔄 新连接同步流程

1. 服务端发送 `snapshot`（`full=True`，含完整 `grid`）。
2. 服务端发送 `status`。
3. 服务端按顺序补发内存中最近最多 800 条 `log`。

实现见 `main.py:64-70`。
