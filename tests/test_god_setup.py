"""上帝操作 / 开局设置 / 难度参数的测试。"""

import asyncio
import json

import engine as engine_mod
from engine import Engine
from agent import Agent
from world import World
import tools


class FakeHub:
    recorder = None

    async def send(self, type_, payload):
        pass


def make_engine(world_extra=None, agents=None):
    cfg = {
        "world": {"width": 8, "height": 6, "seed": 5, **(world_extra or {})},
        "providers": {},
        "agents": agents or [
            {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
            {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
        ],
    }
    return Engine(cfg, FakeHub())


def flat_world(w=8, h=8, seed=1, **extra):
    world = World({"world": {"width": w, "height": h, "seed": seed, **extra}})
    world.grid = [["." for _ in range(w)] for _ in range(h)]
    world.deposits = {}
    world.depleted = {}
    return world


def make_agent(world, name, pos=(0, 0), idx=0):
    a = Agent({"name": name, "emoji": "🤖", "provider": "none", "model": "m"}, idx, world)
    a.pos = pos
    return a


class Ctx:
    def __init__(self, turn=1):
        self.turn = turn
        self.logs = []

    def log(self, kind, text):
        self.logs.append((kind, text))


# ---------- 上帝传话 ----------

def make_engine3():
    return make_engine(agents=[
        {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "丙", "emoji": "🤖", "provider": "none", "model": "m"},
    ])


def test_god_msg_single():
    eng = make_engine3()
    a, b, c = eng.agents
    err = eng.god_message(["甲"], "北边有矿")
    assert err is None
    assert any("[上帝只对你低语] 北边有矿" in m for m in a.memory)
    assert not any("北边有矿" in m for m in b.memory + c.memory)  # 只进目标记忆
    logs = [h for h in eng.history if h["kind"] == "god"]
    assert logs and "悄悄对 甲 说" in logs[-1]["text"] and "北边有矿" in logs[-1]["text"]


def test_god_msg_multi():
    eng = make_engine3()
    a, b, c = eng.agents
    err = eng.god_message(["甲", "乙"], "南边安全")
    assert err is None
    assert any("[上帝对你们低语] 南边安全" in m for m in a.memory)
    assert any("[上帝对你们低语] 南边安全" in m for m in b.memory)
    assert not any("南边安全" in m for m in c.memory)  # 名单外不可见
    logs = [h for h in eng.history if h["kind"] == "god"]
    assert "悄悄对 甲、乙 说" in logs[-1]["text"]  # 日志列出名单


def test_god_msg_all_is_broadcast():
    eng = make_engine3()
    a, b, c = eng.agents
    err = eng.god_message("all", "风暴将至")
    assert err is None
    for x in (a, b, c):
        assert any("[上帝广播] 风暴将至" in m for m in x.memory)
    logs = [h for h in eng.history if h["kind"] == "god"]
    assert logs[-1]["text"] == "👁 上帝广播：风暴将至"


def test_god_msg_sow():
    eng = make_engine3()
    a, b, c = eng.agents
    err = eng.god_message(["甲", "乙"], "他们中有人想独吞矿脉", sow=True)
    assert err is None
    assert a.relation["乙"] == -5 and b.relation["甲"] == -5  # 两两 -5
    assert "丙" not in a.relation and "丙" not in b.relation  # 名单外不受影响
    for x in (a, b):
        assert any("[传闻] 他们中有人想独吞矿脉" in m for m in x.memory)      # 传闻进记忆
        assert any("[上帝对你们低语] 他们中有人想独吞矿脉" in m for m in x.memory)  # 低语也进记忆
    assert not any("独吞" in m for m in c.memory)
    god_logs = [h["text"] for h in eng.history if h["kind"] == "god"]
    assert any("散布了猜忌" in t for t in god_logs)
    assert not any("独吞" in t for t in god_logs)  # 公开日志不泄露内容


def test_god_msg_sow_single_ignored():
    eng = make_engine3()
    a, b, _ = eng.agents
    err = eng.god_message(["甲"], "你是天选之人", sow=True)  # 单人时挑拨忽略
    assert err is None
    assert a.relation.get("乙", 0) == 0 and b.relation.get("甲", 0) == 0
    assert not any("[传闻]" in m for m in a.memory)
    logs = [h for h in eng.history if h["kind"] == "god"]
    assert "你是天选之人" in logs[-1]["text"]  # 退化为普通私聊，日志公开


def test_god_msg_invalid():
    eng = make_engine3()
    assert eng.god_message(["甲"], "  ") is not None            # 空文本
    assert eng.god_message([], "hi") is not None                # 空名单
    assert eng.god_message(["不存在的人"], "hi") is not None    # 全部无效
    eng.agents[1].alive = False
    assert eng.god_message(["乙"], "hi") is not None            # 死者被过滤后无人
    # 部分有效：死者/错名被过滤，活着的照常收到
    assert eng.god_message(["甲", "乙", "幽灵"], "幸存者你好") is None
    assert any("幸存者你好" in m for m in eng.agents[0].memory)


# ---------- 开局设置 ----------

NEW_AGENTS = [
    {"name": "小红", "emoji": "🦊", "role": "游侠", "provider": "none", "model": "m",
     "backstory": "来自森林", "personality": "机灵", "strategy": "苟住",
     "traits": {"aggression": 0.8, "sociability": 0.2, "greed": 0.5, "paranoia": 0.9}},
    {"name": "小蓝", "provider": "none", "model": "m"},  # 缺省字段应补默认
]


def test_apply_setup():
    eng = make_engine()
    eng.turn = 10
    err = eng.apply_setup(NEW_AGENTS, {"energy_drain": 4, "damage_mult": 1.5})
    assert err is None
    assert [a.name for a in eng.agents] == ["小红", "小蓝"]
    assert eng.turn == 0 and eng.world is not None          # 已 reset
    assert eng.agents[0].traits["paranoia"] == 0.9
    assert eng.agents[1].emoji == "🤖" and eng.agents[1].role == "幸存者"
    assert eng.difficulty("energy_drain") == 4
    assert eng.difficulty("damage_mult") == 1.5


def test_apply_setup_invalid():
    eng = make_engine()
    before = eng.config["agents"]
    assert eng.apply_setup([NEW_AGENTS[0]]) is not None            # 少于 2 人
    assert eng.apply_setup([{"provider": "x", "model": "m"},
                            {"name": "b", "provider": "x", "model": "m"}]) is not None  # 缺 name
    assert eng.apply_setup([NEW_AGENTS[0], NEW_AGENTS[0]]) is not None  # 重名
    assert eng.config["agents"] is before                        # 非法输入不生效
    # 运行中拒绝应用
    eng.running = True
    assert eng.apply_setup(NEW_AGENTS) is not None
    eng.running = False


def test_save_setup(tmp_path):
    on_disk = {
        "world": {"width": 8, "height": 6, "seed": 5},
        "providers": {"deepseek": {"name": "DeepSeek", "base_url": "https://x",
                                   "api_key": "sk-secret", "models": ["m1"]}},
        "agents": [{"name": "旧人", "provider": "deepseek", "model": "m1"}],
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(on_disk, ensure_ascii=False), encoding="utf-8")
    eng = make_engine()
    eng.config_path = str(p)
    assert eng.apply_setup(NEW_AGENTS, {"hp_drain": 9}) is None
    assert eng.save_setup() is None
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["providers"]["deepseek"]["api_key"] == "sk-secret"  # 原有内容不动
    assert saved["providers"]["deepseek"]["base_url"] == "https://x"
    assert [a["name"] for a in saved["agents"]] == ["小红", "小蓝"]
    assert saved["world"]["hp_drain"] == 9
    assert saved["world"]["width"] == 8


# ---------- 难度参数 ----------

def test_damage_mult(monkeypatch):
    w = flat_world(damage_mult=2.0)
    a = make_agent(w, "甲", (2, 2), 0)
    b = make_agent(w, "乙", (3, 2), 1)
    w.agents = [a, b]
    monkeypatch.setattr(tools.random, "randint", lambda lo, hi: 11)
    tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    assert b.hp == 100 - 22  # 11 x 2.0，作用于最终伤害
    # 倍率 1.0 时同样种子下是 11
    w2 = flat_world()
    a2 = make_agent(w2, "甲", (2, 2), 0)
    b2 = make_agent(w2, "乙", (3, 2), 1)
    w2.agents = [a2, b2]
    tools.resolve_attack(a2, w2, {"target": "乙"}, Ctx())
    assert b2.hp == 100 - 11


def test_gather_mult(monkeypatch):
    # 草地基础概率 0.3；倍率 2.0 后 0.6，random()=0.5 时成功
    w = flat_world(gather_mult=2.0)
    a = make_agent(w, "甲", (2, 2))
    w.agents = [a]
    monkeypatch.setattr(tools.random, "random", lambda: 0.5)
    fb, _ = tools.resolve_gather(a, w, {}, Ctx())
    assert "捡到食物" in fb
    # 倍率 1.0 时同样随机数失败
    w2 = flat_world()
    a2 = make_agent(w2, "甲", (2, 2))
    w2.agents = [a2]
    fb2, _ = tools.resolve_gather(a2, w2, {}, Ctx())
    assert "一无所获" in fb2


def test_energy_hp_drain_and_event_prob(monkeypatch):
    eng = make_engine(world_extra={"energy_drain": 5, "hp_drain": 7, "event_prob": 0})
    # 让演示决策固定为 wait，排除行动干扰
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    eng.agents[1].energy = 3  # 乙这回合能量归零
    asyncio.run(eng.run_turn())
    assert eng.agents[0].energy == 95       # 100 - 5（自定义消耗）
    assert eng.agents[1].energy == 0
    assert eng.agents[1].hp == 93           # 100 - 7（自定义生命损耗）
    assert not any(h["kind"] == "event" for h in eng.history)  # event_prob=0 不触发事件
