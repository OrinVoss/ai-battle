# ⚙️ 配置参考

`config.json` 是项目唯一的运行时配置文件，包含世界参数、provider 接入信息、选手人设。服务器启动时读取一次（`main.py:15-17`），之后可以通过前端「开局设置」面板在线修改内存配置，或「保存到文件」写回磁盘。

> 文件路径：`D:/桌面/编程作品/ai大战-v2/config.json`

---

## 顶层结构

```json
{
  "world": { ... },
  "providers": { ... },
  "agents": [ ... ]
}
```

| 节 | 作用 |
|----|------|
| `world` | 地图尺寸、随机种子、运行速度、5 项难度参数 |
| `providers` | 各模型服务商的接入信息、模型列表、单价、思考模式开关 |
| `agents` | 参赛选手数组，至少 2 人 |

---

## 🌍 world 节

| 字段 | 类型 | 必填 | 默认值 | 取值范围 | 说明 |
|------|------|------|--------|----------|------|
| `width` | int | 否 | 20 | ≥2 | 地图宽度（格子数）（`world.py:11`） |
| `height` | int | 否 | 16 | ≥2 | 地图高度（格子数）（`world.py:12`） |
| `seed` | int / null | 否 | null | 任意整数或 null | 随机种子；为 null 时每次生成不同地图（`world.py:14`） |
| `turns_per_second` | float | 否 | 0.6 | >0 | 默认运行速度（`engine.py:69`） |
| `energy_drain` | float | 否 | 2 | 0~5 | 每回合能量消耗（`engine.py:295`） |
| `hp_drain` | float | 否 | 3 | 0~10 | 能量归零后每回合生命损耗（`engine.py:296`） |
| `damage_mult` | float | 否 | 1.0 | 0.5~2.0 | 攻击伤害倍率（`engine.py:297`） |
| `event_prob` | float | 否 | 0.08 | 0~0.3 | 世界事件触发概率（`engine.py:298`） |
| `gather_mult` | float | 否 | 1.0 | 0.5~2.0 | 采集成功率倍率（`engine.py:299`） |
| `commentary_interval` | int | 否 | 5 | 0 或 ≥1 | 每 N 回合触发一次 AI 解说（0=关闭）（`engine.py:763`） |
| `reflect_interval` | int | 否 | 10 | 0 或 ≥1 | 每 M 回合触发一次代理反思（0=关闭）（`engine.py:878`） |
| `max_turns` | int | 否 | 300 | 0 或 ≥1 | 回合上限，达到后强制评分结算（0=无上限）（`engine.py:310`） |

### 字段详解

#### `width` / `height`

- 决定地图总格子数 `w × h`。
- 也影响资源生成总量：水域/山地/森林/矿脉数量均按格子数比例计算（`world.py:36-50`）。
- 不建议设得太小（<8×6），否则出生点可能过于拥挤。

#### `seed`

- 设为一个固定整数时，每次重置都会生成完全相同的地图，便于复现 bug 或比赛。
- 设为 `null` 时，`random.Random(None)` 使用系统时间作为种子，每次不同。
- 只影响地图生成，不影响模型决策的随机性。

#### `turns_per_second`

- 控制连续运行时每回合之间的间隔。
- 实际间隔 = `1.0 / speed` 秒（`engine.py:939`）。
- 运行时可通过前端速度滑块实时修改。

#### `energy_drain`

- 每回合结束时，所有存活选手能量 -= 该值（暴雨时额外 -3）。
- 设为 0 时选手不会因为时间流逝而掉能量。
- 设为 5 时，能量压力极大：一名 100 能量的选手，不休息的话 20 回合就会耗尽。

#### `hp_drain`

- 能量为 0 时，每回合 HP -= 该值。
- 设为 0 时，能量耗尽不会导致死亡。
- 设为 10 时，能量耗尽后 10 回合内必死（从 100 HP 开始）。

#### `damage_mult`

- 最终伤害 = `(基础伤害 8~14 + 武器加成 10) × damage_mult`。
- 设为 0.5 时，有武器伤害 9~12，很难快速击杀。
- 设为 2.0 时，有武器伤害 36~48，可能一刀半血。

#### `event_prob`

- 每回合触发世界事件的概率。
- 设为 0 时完全关闭事件。
- 设为 0.3 时，平均每 3~4 回合就有一次事件。

#### `gather_mult`

- 只影响草地/森林采集成功率，不影响矿脉直接采集。
- 草地基础 30%，森林基础 50%。
- 设为 2.0 时，草地 60%、森林 100% 成功。
- 设为 0.5 时，草地 15%、森林 25% 成功。

#### `commentary_interval` / `reflect_interval`

- `commentary_interval`：每多少回合让解说员 LLM 点评一次局势，默认 5；设为 0 关闭。
- `reflect_interval`：每多少回合让有真实模型的存活代理做一次反思并写入 notes，默认 10；设为 0 关闭。
- 两者都是非阻塞调用，失败静默，不影响主循环。
- 演示模式（无可用 API Key）下解说与反思自动关闭。

### 难度参数对游戏节奏的影响

| 参数调高 | 效果 |
|----------|------|
| `energy_drain` | 选手更快疲惫，休息和食物价值上升，节奏更紧张 |
| `hp_drain` | 能量耗尽惩罚更重，慢性死亡更快 |
| `damage_mult` | 战斗更致命，游戏更快结束 |
| `event_prob` | 世界更动荡，随机性更强 |
| `gather_mult` | 资源更充裕，囤积型选手更强 |

难度参数在 `world.py:24-32` 和 `engine.py:294-302` 中均被钳位到合法范围，手写越界值不会崩溃。

#### `max_turns`

- 控制单局最多回合数。默认 `300`，设为 `0` 表示无上限。
- 达到上限且场上仍有 2 人及以上存活时，强制进入「评分结算」：按 `存活 > 击杀 > 资源分` 排序，第一名获胜。
- 该值只影响内存中的当前配置；前端「保存到文件」不会把它写回 `config.json`。
- 详情见 [usage.md#结局规则](usage.md#结局规则) 与 [technical.md#评分与称号](technical.md#评分与称号)。

---

## 🔌 providers 节

每个 provider 是一个对象，键名可自定义（选手通过 `provider` 字段引用）。

```json
"deepseek": {
  "name": "DeepSeek",
  "base_url": "https://api.deepseek.com",
  "api_key": "sk-...",
  "env_key": "DEEPSEEK_API_KEY",
  "thinking": "disabled",
  "price_input": 2,
  "price_output": 8,
  "models": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 显示名称（`main.py:155`） |
| `base_url` | string | 是 | OpenAI 兼容接口地址（`llm.py:28-30`） |
| `api_key` | string | 否 | 直接写 key；为空时尝试读 `env_key` 环境变量（`llm.py:17-27`） |
| `env_key` | string | 否 | 环境变量名（`llm.py:21-22`） |
| `thinking` | string | 否 | `"enabled"` / `"disabled"`，控制 DeepSeek 思考模式（`llm.py:79-80`） |
| `price_input` | float | 否 | 每百万 prompt token 单价（元），用于费用估算（`engine.py:411`） |
| `price_output` | float | 否 | 每百万 completion token 单价（元）（`engine.py:411`） |
| `models` | string[] | 否 | 该 provider 提供的模型列表，供前端下拉框使用（`main.py:155`） |

### 解说员专属配置 `commentator`

可在 `config.json` 顶层增加可选的 `commentator` 节，指定解说员使用的 provider 与模型；
不配置时，引擎会自动挑选第一个有可用 API Key 的 provider 的第一个模型。
该客户端同时用于每 `commentary_interval` 回合的局势解说，以及**游戏结束后的全局 AI 复盘**；无可用 Key 时复盘自动降级为模板文本。

```json
"commentator": {
  "provider": "deepseek",
  "model": "deepseek-v4-flash"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider` | string | 否 | 引用 `providers` 中的键 |
| `model` | string | 否 | 该 provider 下的模型名 |

### 字段详解

#### `base_url`

- 必须指向 OpenAI 兼容的 chat completions 接口。
- 常见值：
  - DeepSeek: `https://api.deepseek.com`
  - 硅基流动: `https://api.siliconflow.cn/v1`
  - OpenRouter: `https://openrouter.ai/api/v1`

#### `api_key` 与 `env_key`

读取优先级（`llm.py:17-27`）：

1. 若 `api_key` 是非空字符串，直接使用。
2. 否则若 `env_key` 存在，读取该环境变量。
3. 否则抛 `ProviderError`，该 provider 下的选手进入演示模式。

#### `thinking`

- 仅对 DeepSeek 生效。
- `"enabled"`：模型输出思维链，更慢更费 token，`temperature` 会被忽略。
- `"disabled"`：关闭思考模式，正常输出。
- 不配时，`llm_act` 不设置 `extra_body`。

#### `price_input` / `price_output`

- 单位：元 / 百万 token。
- 用于前端费用显示：`cost = (prompt × price_input + completion × price_output) / 1_000_000`（`engine.py:414`）。
- 未配时显示「费用未知」。

#### `models`

- 前端设置面板的 model 下拉框从这里读取。
- 即使 model 名不在列表中，也可以手动输入；后端只校验非空。

### 内置 provider 示例

| 键 | base_url | 环境变量 |
|----|----------|----------|
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| `siliconflow` | `https://api.siliconflow.cn/v1` | `SILICONFLOW_API_KEY` |
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |

### 添加一个新 provider：完整步骤示例

假设你想接入另一个 OpenAI 兼容服务「ExampleAI」：

1. 在 `config.json` 的 `providers` 下新增一节：

```json
"example": {
  "name": "ExampleAI",
  "base_url": "https://api.example.com/v1",
  "api_key": "",
  "env_key": "EXAMPLE_API_KEY",
  "price_input": 1.5,
  "price_output": 6,
  "models": ["example-chat", "example-large"]
}
```

2. 设置环境变量（推荐，避免明文 key）：

```cmd
set EXAMPLE_API_KEY=sk-your-key-here
```

3. 在 `agents` 中使用该 provider：

```json
{
  "name": "测试员",
  "provider": "example",
  "model": "example-chat",
  ...
}
```

4. 重启服务器。该选手会调用 ExampleAI，前端费用按 1.5/6 估算。

---

## 🤖 agents 节

`agents` 是选手数组，至少 2 人（`engine.py:277-291`）。每个选手对象：

```json
{
  "name": "陈默",
  "emoji": "🕸️",
  "role": "被害妄想症患者",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "backstory": "曾经被人背叛到一无所有...",
  "personality": "极度多疑、神经质...",
  "strategy": "时刻记录每个人的'可疑行径'...",
  "traits": {
    "aggression": 0.6,
    "sociability": 0.1,
    "greed": 0.5,
    "paranoia": 0.98
  }
}
```

| 字段 | 类型 | 必填 | 默认值 | 限制 | 说明 |
|------|------|------|--------|------|------|
| `name` | string | 是 | — | 2~20 字符 | 选手名字，唯一标识（`engine.py:328`） |
| `emoji` | string | 否 | 🤖 | 最长 4 字符 | 头像映射键（`engine.py:329`） |
| `role` | string | 否 | 幸存者 | 最长 20 字符 | 角色名（`engine.py:330`） |
| `provider` | string | 是 | — | — | 引用 `providers` 中的键（`engine.py:331`） |
| `model` | string | 是 | — | — | 该 provider 下的模型名（`engine.py:332`） |
| `backstory` | string | 否 | 空 | 最长 500 字符 | 人物背景（`agent.py:14`、`agent.py:106`） |
| `personality` | string | 否 | 空 | 最长 500 字符 | 性格描述（`agent.py:15`、`agent.py:107`） |
| `strategy` | string | 否 | 空 | 最长 500 字符 | 处世策略（`agent.py:26`、`agent.py:108`） |
| `traits` | object | 否 | 全部 0.5 | 0~1 | 四项特质（`agent.py:17-25`、`agent.py:109`） |

### 字段详解

#### `name`

- 唯一标识一名选手。
- 不能与其他选手重名，否则 `apply_setup` 拒绝（`engine.py:282-284`）。
- 会出现在日志、关系图、排行榜（键为 `name|model`）。

#### `emoji`

- 决定前端头像 SVG 图标。
- 映射表见 `web/icons.js:51-62`；未知 emoji 兜底为 `robot`。
- 长度限制 4 字符，因为部分 emoji 含变体选择器。

#### `role` / `backstory` / `personality` / `strategy`

- 全部进入 `system_prompt()` 的固定人设模板（`agent.py:104-116`）。
- 对真实模型：直接影响角色扮演。
- 对演示模式：仅作为文本参考，主要决策权重来自 `traits`。

### traits 四项含义与作用范围

| 特质 | 含义 | 演示模式作用 | 提示词作用 |
|------|------|--------------|------------|
| `aggression` | 攻击性 | 高攻击更可能主动攻击附近目标（`llm.py:155`、`llm.py:176`） | 写入 system prompt，模型参考 |
| `sociability` | 社交性 | 高社交更可能发起交易、说话（`llm.py:179`、`llm.py:189`） | 写入 system prompt，模型参考 |
| `greed` | 贪婪 | 影响对资源的重视程度 | 写入 system prompt，模型参考 |
| `paranoia` | 多疑 | 影响对威胁的判断 | 写入 system prompt，模型参考 |

### 极端人设配置示例

#### 示例 1：纯和平主义者

```json
{
  "name": "鸽子",
  "emoji": "🕊️",
  "role": "和平主义者",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "backstory": "从小被教育冲突没有赢家，只想让所有人活着。",
  "personality": "温和、回避冲突、乐于助人。",
  "strategy": "优先寻找食物矿脉，遇到人就提出交易，绝不主动攻击。",
  "traits": {
    "aggression": 0.05,
    "sociability": 0.95,
    "greed": 0.1,
    "paranoia": 0.1
  }
}
```

演示模式行为：几乎不会攻击，会积极交易和说话。

#### 示例 2：纯掠夺者

```json
{
  "name": "豺狼",
  "emoji": "🐺",
  "role": "掠夺者",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "backstory": "弱肉强食是唯一法则，资源要靠抢。",
  "personality": "冷酷、果断、不信任任何人。",
  "strategy": "寻找最近的对手，靠近后发动攻击；只在必要时休息和进食。",
  "traits": {
    "aggression": 0.98,
    "sociability": 0.05,
    "greed": 0.9,
    "paranoia": 0.8
  }
}
```

演示模式行为：看到附近有人就大概率攻击，不会主动交易。

---

## 🔒 安全注意事项

### API Key 明文存储

`config.json` 中 `api_key` 是明文。如果要把项目推到 GitHub：

1. 先删除 `api_key` 字段中的内容，或改用环境变量。
2. 把 `config.json` 加入 `.gitignore`。

当前 `.gitignore` 已包含 `replays/`、`logs/`、`stats.json`、`.env`，但未默认忽略 `config.json`，请自行添加：

```gitignore
config.json
```

### 环境变量优先

`llm.py:17-27` 的读取顺序：

1. 先读 `api_key`。
2. 若为空或不存在，再读 `env_key` 对应的环境变量。
3. 仍为空则抛 `ProviderError`，该选手进入演示模式。

### 设置保存行为

前端「保存到文件」只替换 `agents` 和 `world` 下的难度键，其余内容（包括 `providers` 里的 `api_key`）原样保留（`engine.py:370-402`）。

### 导出安全

`export_data()` 会导出选手终态与日志，但绝不包含 `api_key`（`engine.py:601-660`）。

### HTTP API 不暴露 Key

`/api/setup` 返回的 `providers` 只包含 `name` 和 `models`，不含 `api_key`（`main.py:153-159`）。
