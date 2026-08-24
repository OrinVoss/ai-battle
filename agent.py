"""代理：一个模型选手。持有状态、关系、记忆、感知。"""

from collections import deque


class Agent:
    def __init__(self, cfg, idx, world):
        self.id = idx
        self.name = cfg["name"]
        self.emoji = cfg.get("emoji", "🤖")
        self.provider = cfg["provider"]
        self.model = cfg["model"]
        self.role = cfg.get("role", "幸存者")
        self.backstory = cfg.get("backstory", "")
        self.personality = cfg.get("personality", "")
        # 特质：与默认值合并并转 float，缺键/None/脏值都不崩
        raw_traits = cfg.get("traits") or {}
        if not isinstance(raw_traits, dict):
            raw_traits = {}
        self.traits = {}
        for k, dft in (("aggression", 0.5), ("sociability", 0.5), ("greed", 0.5), ("paranoia", 0.5)):
            try:
                self.traits[k] = float(raw_traits.get(k, dft))
            except (TypeError, ValueError):
                self.traits[k] = dft
        self.strategy = cfg.get("strategy", "")

        self.hp = 100
        self.energy = 100
        self.pos = (0, 0)  # 由 engine 分配出生点
        self.items = {"food": 2, "ore": 0}
        self.weapon = False
        self.weapon_durability = 0   # 武器耐久：打造时为 6，每次攻击 -1，归零碎裂
        self.kills = 0               # 本局击杀数（attack 致死 +1）
        self.usage = {"prompt": 0, "completion": 0, "cache_hit": 0, "cache_miss": 0, "cache_est": False}  # 本局累计 token / 缓存命中（est=命中率为本地估算）
        self.alive = True
        self.state = "存活"
        self.relation = {}          # 名字 -> 关系分
        self.memory = deque(maxlen=18)   # 短期见闻
        self.notes = []             # 长期笔记（模型自己写）
        self.pending_trade = None
        self.last_attacker = None
        self.last_talk = 0
        self.last_thought = ""

    # ---------- 记忆 ----------
    def add_event(self, turn, s):
        self.memory.append(f"[T{turn}] {s}")

    # ---------- 关系 ----------
    def rel_label(self, score):
        if score >= 3:
            return "盟友"
        if score > 0:
            return "友善"
        if score == 0:
            return "中立"
        if score >= -4:
            return "敌对"
        return "深仇"

    def relation_str(self, world):
        parts = []
        for o in world.agents:
            if o is self:
                continue
            s = self.relation.get(o.name, 0)
            parts.append(f"{o.name}:{self.rel_label(s)}({s:+d})")
        return "；".join(parts) or "无"

    # ---------- 感知 ----------
    def vision_range(self, world):
        """视野半径：白天 6 格，夜晚减半为 3 格（曼哈顿距离）。"""
        return 3 if getattr(world, "night", False) else 6

    def nearby_map(self, world):
        x, y = self.pos
        vision = self.vision_range(world)
        lines = []
        for yy in range(y - 2, y + 3):
            row = ""
            for xx in range(x - 2, x + 3):
                if not world.in_bounds(xx, yy):
                    row += "█"
                    continue
                if (xx, yy) == self.pos:
                    row += "你"
                    continue
                if world.dist(self.pos, (xx, yy)) > vision:
                    row += "?"  # 视野外（如夜晚的四角），地形也遮住
                    continue
                occ = None
                for o in world.agents:
                    if o.pos == (xx, yy):
                        occ = o
                        break
                if occ:
                    row += occ.emoji if occ.alive else "💀"
                else:
                    row += world.tile(xx, yy)
            lines.append(row)
        return "\n".join(lines)

    def system_prompt(self):
        return f"""你是「{self.name} {self.emoji}」，{self.role}。
人物设定：{self.backstory}
性格：{self.personality}
处世策略：{self.strategy}
特质：攻击性 {self.traits['aggression']} / 社交性 {self.traits['sociability']} / 贪婪 {self.traits['greed']} / 多疑 {self.traits['paranoia']}（0~1）

你正身处一个生存沙盒世界，和其他几个「模型代理」生活在一起。你可以自由决定：合作、交易、结盟、欺骗、掠夺、攻击……一切取决于你的判断。你的终极目标是：活下去，并尽可能发展壮大。扮演好你自己，像真人一样思考和行动。

【行动要求】
- 每回合调用一个工具。调用工具时，必须在参数里带上 reason 字段，用一句话写出你此刻的思考与行动理由（例如"南边好像有矿脉，先去占住"）。
- reason 会被观战者看到，但其他代理看不到你的内心想法，可以放心写。
- 说话（talk）完全免费，是了解他人、谈判、试探、挑衅的唯一手段。不要闷头当独行侠——情报就是生命。"""

    def perceive(self, world, turn):
        tx, ty = self.pos
        mem = list(self.memory)[-12:]
        mem.reverse()
        notes = "；".join(self.notes) if self.notes else "无"
        trade = (
            f"{self.pending_trade['from']} 想用 {self.pending_trade['on']}个{self.pending_trade['offer']}"
            f" 换你的 {self.pending_trade['wn']}个{self.pending_trade['want']}（交易编号 {self.pending_trade['id']}）"
            if self.pending_trade else "无"
        )
        night = getattr(world, "night", False)
        vision = self.vision_range(world)
        nearby_people = []
        nearby_corpses = []
        for o in world.agents:
            if o is self:
                continue
            d = world.dist(self.pos, o.pos)
            if d > vision:
                continue
            if o.alive:
                nearby_people.append(f"{o.name}{o.emoji}({d}格)")
            else:
                # 尸体可搜刮：报出名字、位置与残留物品，让 loot 可操作
                loot_desc = f"食物x{o.items['food']} 矿石x{o.items['ore']}" + (" 武器" if o.weapon else "")
                nearby_corpses.append(f"{o.name}的尸体💀在{o.pos}（{loot_desc}）")
        np_str = "；".join(nearby_people) or "视野内没有其他人"
        corpse_str = "；".join(nearby_corpses) or "无"
        silent = turn - getattr(self, "last_talk", 0)
        silent_line = f"（你已经 {silent} 回合没开口说过话了——说话免费，情报无价，别当哑巴。）" if silent >= 3 else ""
        weapon_str = f"有（攻击+10，耐久{self.weapon_durability}）" if self.weapon else "无"
        time_line = "🌙 夜晚（视野受限，只能看到 3 格内的人）" if night else "🌞 白天"
        # 规则文本跟随实际难度参数，调难度后提示词不说谎
        drain = getattr(world, "energy_drain", 2)
        hp_drain = getattr(world, "hp_drain", 3)
        grass_rate = min(100, round(30 * getattr(world, "gather_mult", 1.0)))
        forest_rate = min(100, round(50 * getattr(world, "gather_mult", 1.0)))
        dmg_mult = getattr(world, "damage_mult", 1.0)
        dmg_lo, dmg_hi, dmg_wp = round(8 * dmg_mult), round(14 * dmg_mult), round(10 * dmg_mult)
        night_bonus = "，夜晚偷袭+3" if night else ""

        # user 消息按「最稳定 → 最易变」排序，让 DeepSeek 前缀缓存命中率最大化：
        # 1) 世界规则（难度参数不变时完全稳定）
        # 2) 状态/关系/笔记/交易/视野（多数回合只小变）
        # 3) 5x5 小地图（每回合随位置变）
        # 4) 最近见闻（每回合都变）
        # 5) 易变提示行、回合/昼夜信息（最后）
        parts = [
            "【世界规则】",
            f"- 每回合你必须且只能执行一个行动。回合不断循环：每回合能量自动-{drain:g}；能量归零后每回合生命-{hp_drain:g}。",
            f"- 🍞 吃食物：生命+12。😴 休息：能量+20。采集：草地{grass_rate}%捡到食物，森林{forest_rate}%找到野果，f/o 矿脉直接采集（矿脉会耗尽）。",
            f"- ⚔️ 攻击：消耗5能量，伤害{dmg_lo}-{dmg_hi}（有武器+{dmg_wp}{night_bonus}），会结仇，被打的人会记住你。武器有耐久，用多了会碎。",
            f"- ⛏️ 3块矿石可打造武器（攻击+{dmg_wp}）。你可以和其他人交易食物/矿石，也可以单方面赠送给4格内的人以拉拢关系。",
            "- 你只能看到视野内的人，看不到的人也无法 inspect；距离你4格内的人说话你能听到；全场大喊也能听到（但会暴露你的位置）。",
            "- 你的选择完全自由：和平共处、结盟、垄断资源、见人就打、背后偷袭……都行。用工具执行行动；拿不定主意就用 wait。",
            "",
            "【你的状态】",
            f"❤️ 生命 {self.hp}/100 | ⚡ 能量 {self.energy}/100 | 📍 位置 ({tx},{ty})",
            f"🍞 食物 x{self.items['food']} | ⛏️ 矿石 x{self.items['ore']} | 🗡️ 武器 {weapon_str}",
            "",
            f"【你与所有代理的关系】{self.relation_str(world)}",
            f"【你的长期笔记】{notes}",
            f"【你视野内的人】（视野 {vision} 格）{np_str}",
            f"【你视野内的尸体】（可移动到同格搜刮）{corpse_str}",
            f"【待处理交易】{trade}",
            "",
            "【你周围的环境】（5x5，你=你，f=食物矿，o=矿石矿，F=森林，~=水，M=山，?=视野外）",
            self.nearby_map(world),
            "",
            "【最近的见闻】",
            chr(10).join(mem) if mem else "（你还没有看到什么特别的事）",
        ]
        if silent_line:
            parts.append(silent_line)
        parts.append(f"当前：第 {turn} 回合 · {time_line}")
        return "\n".join(parts)
