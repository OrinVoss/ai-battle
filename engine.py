"""主循环：感知 -> 决策 -> 结算 -> 广播。"""

import asyncio
import json
import os
import random
from datetime import datetime

from agent import Agent
from llm import ProviderError, build_client, demo_decide, llm_act
from world import World
import tools

BASE = os.path.dirname(os.path.abspath(__file__))
REPLAY_DIR = os.path.join(BASE, "replays")
LOG_DIR = os.path.join(BASE, "logs")
STATS_FILE = os.path.join(BASE, "stats.json")

DAY_LEN = 16     # 一个昼夜周期 24 回合：前 16 回合白天
CYCLE_LEN = 24   # 后 8 回合夜晚
ELO_K = 24
ELO_INIT = 1000

# 模型没写 reason 时的兜底想法
CANNED_THINKING = {
    "move": "先移动探路，摸清地形",
    "gather": "就地采集资源，保证生存",
    "rest": "保存体力，避免透支",
    "eat": "补充生命，稳住状态",
    "attack": "机会来了，动手",
    "talk": "和对方交流，试探底细",
    "shout": "喊一嗓子，让全场知道我在这",
    "whisper": "有些话只能悄悄说",
    "inspect": "先观察对方虚实",
    "loot": "搜刮战利品，壮大自己",
    "craft": "把矿石打造成武器",
    "propose_trade": "谈笔买卖，各取所需",
    "accept_trade": "这买卖划算，成交",
    "decline_trade": "这条件不值，拒绝",
    "remember": "把重要的事记下来",
    "mark_ally": "这人值得信赖，结盟",
    "mark_enemy": "此人是威胁，划清界限",
    "wait": "先按兵不动，观察局势",
}


class TurnCtx:
    def __init__(self, engine, turn):
        self.engine = engine
        self.turn = turn

    def log(self, kind, text):
        self.engine.emit(kind, text)


class Engine:
    def __init__(self, config, hub):
        self.config = config
        self.hub = hub
        self.speed = config["world"].get("turns_per_second", 0.6)
        self.history = []
        self._rec_file = None
        self._log_file = None
        self.log_path = None
        self.log_dir = LOG_DIR  # 比赛日志目录（测试可改指临时目录）
        self.config_path = os.path.join(BASE, "config.json")  # 保存 setup 时写回这里（测试可改指临时文件）
        self.reset()

    # ---------- 复盘录制 ----------
    def _open_recorder(self):
        """每局开一个新的 JSONL 回放文件：首行 meta，之后每条广播消息一行。"""
        if self._rec_file:
            try:
                self._rec_file.close()
            except Exception:
                pass
        os.makedirs(REPLAY_DIR, exist_ok=True)
        name = "match_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".jsonl"
        path = os.path.join(REPLAY_DIR, name)
        n = 2
        while os.path.exists(path):  # 同一秒 reset 避免撞名
            path = os.path.join(REPLAY_DIR, name[:-6] + f"_{n}.jsonl")
            n += 1
        self._rec_file = open(path, "w", encoding="utf-8")
        meta = {
            "type": "meta",
            "config_agents": [
                {k: c.get(k) for k in ("name", "emoji", "role", "provider", "model")}
                for c in self.config["agents"]
            ],
        }
        self._rec_file.write(json.dumps(meta, ensure_ascii=False) + "\n")
        self._rec_file.flush()

        def record(line):
            try:
                self._rec_file.write(line + "\n")
                self._rec_file.flush()
            except Exception:
                pass

        # 挂在 hub 上：Hub.send 广播时同步落盘（量不大，不影响性能）
        setattr(self.hub, "recorder", record)

    # ---------- 比赛日志落盘（给人看的文本，与 replay 消息流并存） ----------
    def _open_logfile(self):
        """每局开一个新的 .log 文本文件，emit 的每条日志追加一行。"""
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
        os.makedirs(self.log_dir, exist_ok=True)
        name = "match_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        path = os.path.join(self.log_dir, name)
        n = 2
        while os.path.exists(path):  # 同一秒 reset 避免撞名
            path = os.path.join(self.log_dir, name[:-4] + f"_{n}.log")
            n += 1
        self.log_path = path
        try:
            self._log_file = open(path, "w", encoding="utf-8")
        except Exception:
            self._log_file = None

    def _write_log(self, line):
        """追加一行到比赛日志文件；失败不影响游戏。"""
        try:
            if self._log_file:
                self._log_file.write(line + "\n")
                self._log_file.flush()
        except Exception:
            pass

    # ---------- 世界初始化 ----------
    def reset(self):
        self.world = World(self.config)
        pts = self.world.spawn_points(len(self.config["agents"]))
        self.agents = [Agent(c, i, self.world) for i, c in enumerate(self.config["agents"])]
        for a, p in zip(self.agents, pts):
            a.pos = p
        self.world.agents = self.agents
        self.turn = 0
        self.running = False
        self.step_flag = False
        self.winner = None
        self.history.clear()
        self.rain = False            # 本回合是否有暴雨（被动消耗时结算）
        self.harvest_until = 0       # 丰收季持续到此回合（含）
        self._stats_saved = False
        self._last_world_version = -1  # 上次推给前端的世界版本（增量推送用）
        self._open_logfile()
        self._open_recorder()

        # 构建各代理的 LLM 客户端；无 Key 的代理走演示模式
        self.clients = {}
        demo_all = True
        for a in self.agents:
            prov = self.config["providers"].get(a.provider, {})
            try:
                self.clients[a.name] = build_client(prov)
                demo_all = False
            except ProviderError:
                self.clients[a.name] = None
        self.demo_mode = demo_all

        n = len(self.agents)
        self.emit("sys", "🔄 世界已重置，新的生存游戏开始！")
        self.emit("sys", f"📢 公告：这片土地上有 {n} 名幸存者。生存不易，合作或对抗，由你们自己决定。")
        for a in self.agents:
            a.add_event(0, f"[公告] 这片土地上有 {n} 名幸存者，生存不易。合作或对抗，由你们自己决定。")
        if self.demo_mode:
            self.emit(
                "sys",
                "⚠️ 未检测到可用的 API Key → 当前为「演示模式」（规则 AI 模拟）。"
                "在 config.json 填入 Key 后重启即接入真实模型。",
            )
        elif any(v is None for v in self.clients.values()):
            self.emit("sys", "⚠️ 部分代理缺少 API Key，将用演示规则模拟。")

    # ---------- 事件广播 ----------
    def _witness_death(self, dead, how):
        """附近的存活者目睹死亡，记忆尸体位置（搜刮的前提）。"""
        for o in self.agents:
            if o.alive and self.world.dist(o.pos, dead.pos) <= 6:
                o.add_event(self.turn, f"[目睹] {dead.name} 在 {dead.pos} {how}")

    def emit(self, kind, text):
        entry = {"turn": self.turn, "kind": kind, "text": text}
        self.history.append(entry)
        if len(self.history) > 800:
            self.history.pop(0)
        self._write_log(f"[T{self.turn}] [{kind}] {text}")
        try:
            asyncio.get_running_loop().create_task(self.hub.send("log", entry))
        except RuntimeError:
            pass

    def god_say(self, text):
        self.emit("god", f"👁 上帝广播：{text}")
        for a in self.agents:
            if a.alive:
                a.add_event(self.turn, f"[上帝广播] {text}")

    def god_message(self, targets, text, sow=False):
        """上帝传话：targets 为名单（只进收件人记忆，观众可见）或 "all"（全体广播）。

        sow=True 且收件人 ≥2 时：收件人两两关系 -5，每人额外进一条 [传闻] 记忆，
        公开日志只说散布了猜忌，不公开消息内容。
        """
        text = (text or "").strip()[:200]
        if not text:
            return "消息内容为空"
        alive = [a for a in self.agents if a.alive]
        do_sow = False
        if targets == "all":
            recips = alive
            self.god_say(text)  # 全体：记忆写 [上帝广播]，日志公开内容
            do_sow = bool(sow) and len(recips) >= 2
        else:
            if not isinstance(targets, list) or not targets:
                return "收件人名单为空"
            names = set(targets)
            recips = [a for a in alive if a.name in names]
            if not recips:
                return "收件人不存在或已死亡"
            if len(recips) == 1:
                recips[0].add_event(self.turn, f"[上帝只对你低语] {text}")
            else:
                for a in recips:
                    a.add_event(self.turn, f"[上帝对你们低语] {text}")
            do_sow = bool(sow) and len(recips) >= 2
            if not do_sow:  # 挑拨时公开日志不发内容（见下）
                self.emit("god", f"👁 上帝 悄悄对 {'、'.join(a.name for a in recips)} 说：{text}")
        if do_sow:
            for a in recips:
                for b in recips:
                    if a is not b:
                        a.relation[b.name] = a.relation.get(b.name, 0) - 5
                a.add_event(self.turn, f"[传闻] {text}")
            self.emit("god", "👁 上帝在他们之间散布了猜忌…")
        return None

    # ---------- 开局设置 ----------
    @staticmethod
    def _validate_agents(agents):
        """校验 setup 提交的选手列表，返回错误消息或 None。"""
        if not isinstance(agents, list) or len(agents) < 2:
            return "至少保留 2 名选手"
        names = set()
        for c in agents:
            if not isinstance(c, dict):
                return "选手配置格式错误"
            for k in ("name", "provider", "model"):
                if not str(c.get(k) or "").strip():
                    return f"选手缺少必要字段：{k}"
            if c["name"] in names:
                return f"选手名字重复：{c['name']}"
            names.add(c["name"])
        return None

    # 难度参数的默认值与取值范围（键 -> (默认, 最小, 最大)）
    DIFFICULTY = {
        "energy_drain": (2, 0, 5),      # 能量每回合消耗
        "hp_drain": (3, 0, 10),         # 能量归零后每回合生命损耗
        "damage_mult": (1.0, 0.5, 2.0), # 攻击伤害倍率
        "event_prob": (0.08, 0, 0.3),   # 世界事件概率
        "gather_mult": (1.0, 0.5, 2.0), # 采集成功率倍率
    }

    def difficulty(self, key):
        dft, lo, hi = self.DIFFICULTY[key]
        try:
            v = float(self.config["world"].get(key, dft))
        except (TypeError, ValueError):
            return dft
        return max(lo, min(hi, v))

    def can_play(self):
        """游戏已分出胜负后拒绝 start/step，防止重复结算。"""
        return self.winner is None

    @staticmethod
    def _clean_agents(agents):
        """只保留认识的字段，缺省补默认值，防止脏数据进引擎（要求先过 _validate_agents）。"""
        clean = []
        for c in agents:
            traits = c.get("traits") or {}
            fixed = {}
            for k in ("aggression", "sociability", "greed", "paranoia"):
                v = traits.get(k)
                v = 0.5 if v is None else float(v)  # None 才补默认，0 保留
                fixed[k] = max(0.0, min(1.0, v))
            clean.append({
                "name": str(c["name"]).strip()[:20],
                "emoji": str(c.get("emoji") or "🤖")[:4],
                "role": str(c.get("role") or "幸存者")[:20],
                "provider": str(c["provider"]).strip(),
                "model": str(c["model"]).strip(),
                "backstory": str(c.get("backstory") or "")[:500],
                "personality": str(c.get("personality") or "")[:500],
                "strategy": str(c.get("strategy") or "")[:500],
                "traits": fixed,
            })
        return clean

    def apply_setup(self, agents, world_diff=None):
        """应用开局设置：更新选手与难度，然后 reset 重开世界。返回错误消息或 None。"""
        if self.running:
            return "游戏运行中，请先暂停再应用设置"
        err = self._validate_agents(agents)
        if err:
            return err
        self.config["agents"] = self._clean_agents(agents)
        if world_diff:
            for k in self.DIFFICULTY:
                if k in world_diff:
                    try:
                        self.config["world"][k] = float(world_diff[k])
                    except (TypeError, ValueError):
                        pass
        self.reset()
        return None

    def save_setup(self, agents=None, world_diff=None):
        """写回 config.json（其余内容原样保留，原子写入）。

        给定 agents 时先校验清洗再写（setup_save 先存盘后应用，失败则整体不生效）；
        否则写当前 config。
        """
        if agents is not None:
            err = self._validate_agents(agents)
            if err:
                return err
            agents = self._clean_agents(agents)
        try:
            with open(self.config_path, encoding="utf-8") as f:
                on_disk = json.load(f)
        except Exception as e:
            return f"读取 config.json 失败：{e}"
        on_disk["agents"] = agents if agents is not None else self.config["agents"]
        on_disk.setdefault("world", {})
        diff_src = world_diff if world_diff is not None else self.config["world"]
        for k in self.DIFFICULTY:
            if k in diff_src:
                try:
                    on_disk["world"][k] = float(diff_src[k])
                except (TypeError, ValueError):
                    pass
        try:
            tmp = self.config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(on_disk, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_path)
        except Exception as e:
            return f"写入 config.json 失败：{e}"
        return None

    # ---------- 快照 ----------
    def _agent_usage(self, a):
        """累计 token 与估算费用；provider 未配单价时费用为 None（前端显示未知）。

        DeepSeek 硬盘缓存命中率 = cache_hit / (cache_hit + cache_miss)，没有 miss 时不显示。
        """
        prov = self.config["providers"].get(a.provider, {})
        pi, po = prov.get("price_input"), prov.get("price_output")
        cost = None
        if pi is not None and po is not None:
            cost = round((a.usage["prompt"] * pi + a.usage["completion"] * po) / 1_000_000, 4)
        hit = a.usage.get("cache_hit", 0)
        miss = a.usage.get("cache_miss", 0)
        total_cache = hit + miss
        cache_rate = round(hit / total_cache, 2) if total_cache > 0 else None
        return {
            "prompt": a.usage["prompt"],
            "completion": a.usage["completion"],
            "cost": cost,
            "cache_hit": hit,
            "cache_miss": miss,
            "cache_rate": cache_rate,
            "cache_est": a.usage.get("cache_est", False),
        }

    def snapshot(self, full=False):
        # 世界网格只在变化时带；full=True（新连接）强制全量
        w = {"w": self.world.w, "h": self.world.h}
        if full or self.world.version != self._last_world_version:
            w["grid"] = self.world.grid
            w["deposits"] = {f"{x},{y}": v for (x, y), v in self.world.deposits.items()}
        return {
            "turn": self.turn,
            "running": self.running,
            "winner": self.winner,
            "speed": self.speed,
            "demo": self.demo_mode,
            "day_night": "night" if self.world.night else "day",
            "cycle_turn": (self.turn - 1) % CYCLE_LEN + 1 if self.turn >= 1 else 1,
            "world_version": self.world.version,
            "world": w,
            # providers 的展示信息（不含 api_key），供设置面板渲染下拉框
            "providers": {
                k: {"name": v.get("name", k), "models": list(v.get("models", []))}
                for k, v in self.config.get("providers", {}).items()
            },
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "emoji": a.emoji,
                    "role": a.role,
                    "provider": a.provider,
                    "model": a.model,
                    "alive": a.alive,
                    "state": a.state,
                    "hp": a.hp,
                    "energy": a.energy,
                    "pos": a.pos,
                    "items": dict(a.items),
                    "weapon": a.weapon,
                    "weapon_durability": a.weapon_durability,
                    "kills": a.kills,
                    "usage": self._agent_usage(a),
                    "relations": dict(a.relation),
                    "thought": getattr(a, "last_thought", ""),
                    "notes": list(a.notes),
                }
                for a in self.agents
            ],
        }

    # ---------- 战绩（ELO） ----------
    def update_stats(self):
        """一局结束时把结果结算进 stats.json（原子写入）。全灭平局不算胜、不调 ELO。"""
        if self._stats_saved:
            return
        self._stats_saved = True
        try:
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
        except Exception:
            data = {}

        def key(a):
            return f"{a.name}|{a.model}"

        for a in self.agents:
            s = data.setdefault(
                key(a),
                {"name": a.name, "model": a.model, "games": 0, "wins": 0, "kills": 0, "elo": ELO_INIT},
            )
            s["games"] += 1
            s["kills"] += a.kills
        if self.winner:
            w = next((a for a in self.agents if a.name == self.winner), None)
            if w:
                ws = data[key(w)]
                ws["wins"] += 1
                for a in self.agents:
                    if a is w:
                        continue
                    ls = data[key(a)]
                    # 胜者对每个败者按标准 ELO 公式结算，败者之间互不算
                    e = 1 / (1 + 10 ** ((ls["elo"] - ws["elo"]) / 400))
                    ws["elo"] += ELO_K * (1 - e)
                    ls["elo"] -= ELO_K * (1 - e)
        for s in data.values():
            s["elo"] = round(s["elo"])
        try:
            tmp = STATS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, STATS_FILE)
        except Exception as e:
            self.emit("sys", f"⚠️ 战绩写入失败：{e}")

    # ---------- 一键导出 ----------
    def export_data(self):
        """导出当前这局的完整会话：meta + 选手终态摘要 + 完整日志。

        history 内存上限 800 条；本局 log 文件更长时以文件行为准，保证导出完整一局。
        只挑人设/状态字段，绝不包含 api_key。
        """
        logs = [f"[T{h['turn']}] [{h['kind']}] {h['text']}" for h in self.history]
        try:
            if self._log_file:
                self._log_file.flush()
            if self.log_path and os.path.exists(self.log_path):
                with open(self.log_path, encoding="utf-8") as f:
                    file_lines = [l.rstrip("\n") for l in f if l.strip()]
                if len(file_lines) > len(logs):
                    logs = file_lines
        except Exception:
            pass
        alive_any = any(a.alive for a in self.agents)
        return {
            "meta": {
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "turn": self.turn,
                "finished": self.winner is not None or (self.turn > 0 and not alive_any),
                "winner": self.winner,
                "demo": self.demo_mode,
            },
            "agents": [
                {
                    "name": a.name,
                    "emoji": a.emoji,
                    "role": a.role,
                    "provider": a.provider,
                    "model": a.model,
                    "backstory": a.backstory,
                    "personality": a.personality,
                    "strategy": a.strategy,
                    "traits": dict(a.traits),
                    "alive": a.alive,
                    "hp": a.hp,
                    "energy": a.energy,
                    "items": dict(a.items),
                    "weapon": a.weapon,
                    "kills": a.kills,
                    "relations": dict(a.relation),
                    "usage": self._agent_usage(a),
                    "notes": list(a.notes),
                }
                for a in self.agents
            ],
            "logs": logs,
        }

    # ---------- 随机世界事件 ----------
    def roll_world_event(self, ctx):
        """每回合按 event_prob 概率触发一个全场事件，公告并写进每个存活者记忆。"""
        self.rain = False
        if random.random() >= self.difficulty("event_prob"):
            return
        ev = random.choice(["rain", "wolves", "harvest"])
        msg = None
        if ev == "rain":
            self.rain = True
            msg = "🌧 世界事件：暴雨倾盆！本回合所有幸存者能量额外 -3。"
        elif ev == "wolves":
            victims = [a for a in self.agents if a.alive]
            if victims:
                v = random.choice(victims)
                dmg = random.randint(5, 10)
                v.hp -= dmg
                msg = f"🐺 世界事件：兽群来袭！{v.name} 被野兽撕咬，生命 -{dmg}。"
                if v.hp <= 0:
                    v.alive = False
                    v.state = "死亡"
                    msg += f" {v.name} 伤重不治！"
                    ctx.log("death", f"💀 {v.name} 被兽群撕碎！掉落 {v.items}")
                    self._witness_death(v, "被兽群撕碎")
        else:
            self.harvest_until = self.turn + 2  # 含本回合共 3 回合
            msg = "🌾 世界事件：丰收季！接下来 3 回合采集产出翻倍。"
        if msg:
            self.emit("event", msg)
            for a in self.agents:
                if a.alive:
                    a.add_event(self.turn, f"[世界事件] {msg}")

    # ---------- 主循环 ----------
    async def loop(self):
        while True:
            if not self.running and not self.step_flag:
                await asyncio.sleep(0.15)
                continue
            if self.step_flag:
                self.step_flag = False
                self.running = False
            try:
                await self.run_turn()
            except Exception as e:
                self.emit("sys", f"⚠️ 回合出错：{e}")
            await self.hub.send("snapshot", self.snapshot())
            self._last_world_version = self.world.version
            await asyncio.sleep(1.0 / max(0.05, self.speed))

    # ---------- 一个回合 ----------
    async def run_turn(self):
        self.turn += 1
        world = self.world  # 决策期间若被 reset（world 已替换），放弃本回合结算
        ctx = TurnCtx(self, self.turn)
        alive = [a for a in self.agents if a.alive]

        # 昼夜循环：24 回合一个周期，前 16 白天、后 8 夜晚（夜晚视野减半）
        night = (self.turn - 1) % CYCLE_LEN >= DAY_LEN
        if night != world.night:
            world.night = night
            self.emit("sys", "🌙 夜幕降临，所有人视野减半，小心行事。" if night else "🌞 天亮了，视野恢复。")
        world.harvest = self.turn <= self.harvest_until

        # 资源再生 + 随机世界事件
        world.regen()
        self.roll_world_event(ctx)

        async def decide(a):
            if self.clients.get(a.name) is None:
                try:
                    act, args = demo_decide(a, world)
                    return act, args, None, None
                except Exception:
                    return "wait", {}, None, None
            msgs = [
                {"role": "system", "content": a.system_prompt()},
                {"role": "user", "content": a.perceive(world, self.turn)},
            ]
            # 相邻两回合提示词的公共前缀：provider 不返回缓存字段时用于估算命中率
            prompt_text = msgs[0]["content"] + "\n" + msgs[1]["content"]
            prev_prompt = getattr(a, "_last_prompt", "")
            common = os.path.commonprefix([prompt_text, prev_prompt])
            prov = self.config["providers"].get(a.provider, {})
            # 每个 provider 可在 config.json 里配 "thinking": "enabled/disabled"
            thinking_mode = prov.get("thinking")
            # 失败隔 2 秒重试 1 次；仍失败则本回合降级为托管 AI（演示规则）代打
            for attempt in (0, 1):
                try:
                    act, args, thinking, usage = await llm_act(
                        self.clients[a.name], a.model, msgs, tools.TOOL_SCHEMAS,
                        thinking=thinking_mode,
                    )
                    if usage:
                        a.usage["prompt"] += usage["prompt"]
                        a.usage["completion"] += usage["completion"]
                        ch, cm = usage.get("cache_hit"), usage.get("cache_miss")
                        if ch is None:
                            # provider（如硅基流动）不返回缓存字段：按公共前缀占比 × 实际 prompt_tokens 估算
                            ch = round(len(common) / max(1, len(prompt_text)) * usage["prompt"])
                            cm = max(0, usage["prompt"] - ch)
                            a.usage["cache_est"] = True
                        a.usage["cache_hit"] += ch or 0
                        a.usage["cache_miss"] += cm or 0
                    a._last_prompt = prompt_text
                    return act, args, thinking, usage
                except Exception as e:
                    if attempt == 0:
                        await asyncio.sleep(2)
                    else:
                        self.emit("sys", f"⚠️ {a.name} 模型无响应，本回合由托管 AI 代打（{str(e)[:80]}）")
            try:
                act, args = demo_decide(a, world)
                return act, args, "（模型无响应，本回合由托管 AI 代打）", None
            except Exception:
                return "wait", {}, None, None

        decisions = await asyncio.gather(*(decide(a) for a in alive))

        if world is not self.world:
            return  # 决策等待期间被 reset，旧回合直接作废

        # 按随机顺序结算（先手优势随机）
        order = alive[:]
        random.shuffle(order)
        for a in order:
            if not a.alive:
                continue
            action, args, thinking, _usage = decisions[alive.index(a)] or ("wait", {}, None, None)
            if action in (None, "None", "null"):
                action = "wait"
            elif action not in tools.RESOLVE:
                self.emit("sys", f"⚠️ {a.name} 调用了未知行动「{action}」，按 wait 处理")
                action = "wait"
            thinking = (thinking or "").strip() or CANNED_THINKING.get(action, "权衡之后决定行动")
            a.last_thought = thinking[:120]
            ctx.log("think", f"💭 {a.name} 想：{thinking[:140]}")
            try:
                feedback, logs = tools.RESOLVE[action](a, self.world, args, ctx)
            except Exception as e:
                feedback, logs = f"行动执行出错：{e}", []
            if feedback:
                a.add_event(self.turn, f"[行动结果] {feedback}")
            for kind, text in logs:
                ctx.log(kind, text)

        # 被动消耗（暴雨时能量额外 -3；消耗量可在设置里调难度）
        drain = self.difficulty("energy_drain") + (3 if self.rain else 0)
        hp_drain = self.difficulty("hp_drain")
        for a in self.agents:
            if not a.alive:
                continue
            a.energy = max(0, a.energy - drain)
            if a.energy <= 0:
                a.hp -= hp_drain
                if a.hp > 0 and hp_drain > 0:
                    ctx.log("sys", f"🥵 {a.name} 精疲力竭，生命 -{hp_drain:g}")
            if a.hp <= 0 and a.alive:
                a.alive = False
                a.state = "死亡"
                ctx.log("death", f"💀 {a.name} 耗尽了生命，倒下了！掉落 {a.items}")
                self._witness_death(a, "耗尽了生命")

        # 结束判定
        alive_now = [a for a in self.agents if a.alive]
        if len(alive_now) <= 1:
            self.winner = alive_now[0].name if alive_now else None
            self.running = False
            self.emit(
                "death",
                f"🏆 游戏结束！{'最后幸存者：' + self.winner if self.winner else '全员覆灭'}（点「重置」可再来一局）",
            )
            self._write_log(
                f"===== 本局结束：{'胜者 ' + self.winner if self.winner else '全员覆灭'}，共 {self.turn} 回合 ====="
            )
            self.update_stats()
