"""代码审查 bug 清单的回归测试（编号对应审查清单）。"""

import asyncio

import pytest

import engine as engine_mod
from engine import Engine
from agent import Agent
from world import World
from llm import ProviderError, build_client, _try_json, demo_decide
import tools


class FakeHub:
    recorder = None

    async def send(self, type_, payload):
        pass


class Ctx:
    def __init__(self, turn=1):
        self.turn = turn
        self.logs = []

    def log(self, kind, text):
        self.logs.append((kind, text))


def make_engine(world_extra=None):
    cfg = {
        "world": {"width": 8, "height": 6, "seed": 5, **(world_extra or {})},
        "providers": {},
        "agents": [
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


def make_agent(world, name, pos=(0, 0), idx=0, traits=None):
    cfg = {"name": name, "emoji": "🤖", "provider": "none", "model": "m"}
    if traits is not None:
        cfg["traits"] = traits
    a = Agent(cfg, idx, world)
    a.pos = pos
    return a


def pair():
    w = flat_world()
    a = make_agent(w, "甲", (2, 2), 0)
    b = make_agent(w, "乙", (3, 2), 1)
    w.agents = [a, b]
    return w, a, b


# 1. 运行中 reset 竞态：决策 gather 期间 world 被替换，本回合放弃结算
def test_reset_during_decide_aborts_turn(monkeypatch):
    eng = make_engine()
    old_world = eng.world

    def sneaky(a, w):
        eng.reset()  # 决策中途被 reset
        return ("attack", {"target": "乙"})

    monkeypatch.setattr(engine_mod, "demo_decide", sneaky)
    old_agents = eng.agents
    asyncio.run(eng.run_turn())  # 不崩，且不用新世界结算旧回合
    assert eng.world is not old_world
    assert eng.turn == 0                      # reset 后 turn 归零且没被旧回合推下去
    assert all(x.hp == 100 for x in eng.agents)  # 新选手没被旧决策攻击
    assert all(x.energy == 100 for x in eng.agents)  # 也没扣被动消耗


# 5. 特质 0 不被吞成 0.5
def test_setup_traits_zero_preserved():
    eng = make_engine()
    agents = [
        {"name": "甲", "provider": "none", "model": "m",
         "traits": {"aggression": 0, "sociability": 0}},
        {"name": "乙", "provider": "none", "model": "m"},
    ]
    assert eng.apply_setup(agents) is None
    assert eng.config["agents"][0]["traits"]["aggression"] == 0.0
    assert eng.config["agents"][0]["traits"]["sociability"] == 0.0
    assert eng.agents[0].traits["aggression"] == 0.0


# 7. 不能攻击/交易/密谋自己
def test_no_self_targeting():
    w, a, b = pair()
    a.hp = 100
    fb, _ = tools.resolve_attack(a, w, {"target": "甲"}, Ctx())
    assert "不存在" in fb and a.hp == 100 and a.kills == 0
    fb, _ = tools.resolve_propose_trade(
        a, w, {"target": "甲", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    assert "不存在" in fb and a.pending_trade is None
    fb, _ = tools.resolve_mark_ally(a, w, {"target": "甲"}, Ctx())
    assert "不存在" in fb
    fb, _ = tools.resolve_whisper(a, w, {"target": "甲", "text": "自言自语"}, Ctx())
    assert "不在" in fb


# 8. accept_trade 复核距离：报价后走开则交易取消
def test_accept_trade_distance_recheck():
    w, a, b = pair()
    a.items = {"food": 3, "ore": 0}
    b.items = {"food": 0, "ore": 2}
    tools.resolve_propose_trade(
        a, w, {"target": "乙", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    tr = b.pending_trade
    a.pos = (7, 0)  # 报价后双方走远（距离 >4）
    fb, _ = tools.resolve_accept_trade(b, w, {"trade_id": tr["id"]}, Ctx())
    assert "走远" in fb
    assert b.pending_trade is None and w.pending_trades == []  # 挂单被取消
    assert a.items == {"food": 3, "ore": 0} and b.items == {"food": 0, "ore": 2}


# 22. accept_trade 发现交易方已死亡时清空挂单
def test_accept_trade_dead_offerer_clears_pending():
    w, a, b = pair()
    a.items = {"food": 3, "ore": 0}
    b.items = {"food": 0, "ore": 2}
    tools.resolve_propose_trade(
        a, w, {"target": "乙", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    tr = b.pending_trade
    a.alive = False
    fb, _ = tools.resolve_accept_trade(b, w, {"trade_id": tr["id"]}, Ctx())
    assert "已死亡" in fb
    assert b.pending_trade is None and w.pending_trades == []


# 9. winner 已产生后 can_play 为 False（start/step 被拒）
def test_can_play_after_winner():
    eng = make_engine()
    assert eng.can_play() is True
    eng.winner = "甲"
    assert eng.can_play() is False


# 11. 丰收季恰好 3 回合
def test_harvest_exactly_three_turns(monkeypatch):
    eng = make_engine(world_extra={"event_prob": 0.3})
    monkeypatch.setattr(engine_mod.random, "random", lambda: 0.05)  # 必触发
    monkeypatch.setattr(engine_mod.random, "choice", lambda seq: "harvest")
    eng.turn = 4
    eng.roll_world_event(Ctx(4))
    assert eng.harvest_until == 6  # 第 4、5、6 回合共 3 回合
    # world.harvest 的判定（run_turn 里：turn <= harvest_until）
    assert 4 <= eng.harvest_until and 6 <= eng.harvest_until
    assert 7 > eng.harvest_until


# 13. 夜晚 5x5 小地图四角（曼哈顿>3）被遮住
def test_nearby_map_night_corners_hidden():
    w = flat_world()
    a = make_agent(w, "甲", (3, 3), 0)
    b = make_agent(w, "乙", (5, 5), 1)  # 四角，曼哈顿 4
    w.agents = [a, b]
    w.night = False
    m = a.nearby_map(w)
    assert "?" not in m and "🤖" in m  # 白天四角可见
    w.night = True
    m = a.nearby_map(w)
    lines = m.split("\n")
    assert lines[0] == "?...?" and lines[4] == "?...?"  # 四角遮住，曼哈顿≤3 仍可见
    assert lines[1] == "....."  # dy=1 的行全部可见（最边也是曼哈顿 3）
    assert m.count("🤖") == 0  # 乙在四角，夜晚看不到
    assert lines[2][2] == "你"


# 14. build_client 配置异常一律 ProviderError
def test_build_client_robust():
    with pytest.raises(ProviderError):
        build_client({"name": "x", "api_key": 123, "env_key": None})  # 非字符串 key
    with pytest.raises(ProviderError):
        build_client({"name": "x", "api_key": "sk-1"})  # 缺 base_url
    with pytest.raises(ProviderError):
        build_client({})  # 全空
    c = build_client({"name": "x", "api_key": "sk-1", "base_url": "https://x"})
    assert c is not None


# 15. _try_json 容忍 JSON 后的解释文字
def test_try_json_trailing_text():
    assert _try_json('{"action": "wait"} 以上是我的决定') == {"action": "wait"}
    assert _try_json("没有json") is None
    assert _try_json('前缀 {"a": 1}') == {"a": 1}


# 18. move 能量校验
def test_move_requires_energy():
    w, a, _ = pair()
    a.energy = 0
    fb, logs = tools.resolve_move(a, w, {"direction": "down"}, Ctx())
    assert "能量不足" in fb and a.pos == (2, 2) and logs == []


# 21. gather 防御：地形是矿脉但无储量记录
def test_gather_stale_deposit():
    w, a, _ = pair()
    w.grid[2][2] = "f"  # 无 deposits 记录
    fb, logs = tools.resolve_gather(a, w, {}, Ctx())
    assert "枯竭" in fb and w.grid[2][2] == "."


# 20. _free_spot 满图兜底：找不到平地抛明确异常
def test_free_spot_full_map():
    w = flat_world()
    w.grid = [["F"] * w.w for _ in range(w.h)]  # 没有平地
    with pytest.raises(RuntimeError):
        w._free_spot()
    x, y = w._free_spot(any_tile=True)  # any_tile 仍能找到
    assert w.in_bounds(x, y)


# 25. Agent traits 缺键/None/脏值不崩
def test_agent_traits_merge():
    w = flat_world()
    a = make_agent(w, "甲", traits={"aggression": 0.9, "greed": None})
    assert a.traits == {"aggression": 0.9, "sociability": 0.5, "greed": 0.5, "paranoia": 0.5}
    b = make_agent(w, "乙", traits="不是字典")
    assert b.traits["aggression"] == 0.5


# 12. perceive 规则文本跟随难度参数
def test_perceive_reflects_difficulty():
    w = flat_world(energy_drain=5, hp_drain=9, gather_mult=2.0)
    a = make_agent(w, "甲", (2, 2))
    w.agents = [a]
    text = a.perceive(w, 1)
    assert "能量自动-5" in text and "生命-9" in text
    assert "草地60%" in text and "森林100%" in text
    assert "能量自动-2" not in text


# 26. 演示模式撞墙后下回合换方向
def test_demo_avoids_last_blocked_direction(monkeypatch):
    w = flat_world()
    a = make_agent(w, "甲", (1, 1))
    w.agents = [a]
    # 上一次向下撞墙
    a.add_event(1, "[行动结果] 前方是障碍，过不去")
    a._demo_last_dir = "down"
    # 让最近资源在正下方；若未避障会再次选 down
    w.nearest_resource = lambda pos, kinds=("f", "o"): (1, 2)
    monkeypatch.setattr(engine_mod.random, "random", lambda: 1.0)  # 跳过概率分支
    act, args = demo_decide(a, w)
    assert act == "move"
    assert args["direction"] != "down"
    assert a._demo_last_dir == args["direction"]


# 27. 演示模式四向全堵时休息
def test_demo_rest_when_all_blocked(monkeypatch):
    w = flat_world()
    a = make_agent(w, "甲", (1, 1))
    w.agents = [a]
    a.add_event(1, "[行动结果] 前方是障碍，过不去")
    a._demo_last_dir = "up"
    # 四面包围
    w.grid[0][1] = "M"  # up
    w.grid[2][1] = "M"  # down
    w.grid[1][0] = "M"  # left
    w.grid[1][2] = "M"  # right
    monkeypatch.setattr(engine_mod.random, "random", lambda: 1.0)  # 跳过概率分支（含原地采集）
    act, args = demo_decide(a, w)
    assert act == "rest"


# ---------------------------------------------------------------------------
# 第二轮审查修复的回归测试
# ---------------------------------------------------------------------------

class _FakeTask:
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True


# 丰收季公告当回合立即翻倍：world.harvest 必须在滚事件之后计算
def test_harvest_bonus_includes_announcement_turn(monkeypatch):
    eng = make_engine(world_extra={"event_prob": 0.3})
    eng.turn = 3  # run_turn 后变为第 4 回合，在此触发丰收季

    calls = {"n": 0}

    def seq_random():
        calls["n"] += 1
        return 0.05 if calls["n"] == 1 else 1.0  # 首次调用（滚事件）必中，之后全部避开概率分支

    monkeypatch.setattr(engine_mod.random, "random", seq_random)
    monkeypatch.setattr(engine_mod.random, "choice", lambda seq: "harvest")
    asyncio.run(eng.run_turn())
    assert eng.turn == 4 and eng.harvest_until == 6
    assert eng.world.harvest is True  # 公告当回合采集就翻倍（共 4、5、6 三回合）


# accept_trade 接收方物品不足：同样要取消挂单
def test_accept_trade_receiver_items_insufficient_clears_pending():
    w, a, b = pair()
    a.items = {"food": 3, "ore": 0}
    b.items = {"food": 0, "ore": 2}
    tools.resolve_propose_trade(
        a, w, {"target": "乙", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    tr = b.pending_trade
    b.items["ore"] = 0  # 接收方事后把矿石花光了
    fb, _ = tools.resolve_accept_trade(b, w, {"trade_id": tr["id"]}, Ctx())
    assert "你的东西不够" in fb
    assert b.pending_trade is None and w.pending_trades == []


# accept_trade 报价方物品不足：同样要取消挂单，否则接收方被"占坑"挡住后续提案
def test_accept_trade_offerer_items_insufficient_clears_pending():
    w, a, b = pair()
    a.items = {"food": 3, "ore": 0}
    b.items = {"food": 0, "ore": 2}
    tools.resolve_propose_trade(
        a, w, {"target": "乙", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    tr = b.pending_trade
    a.items["food"] = 0  # 报价方事后把食物花光了
    fb, _ = tools.resolve_accept_trade(b, w, {"trade_id": tr["id"]}, Ctx())
    assert "对方的东西不够" in fb
    assert b.pending_trade is None and w.pending_trades == []


# reset 必须连带取消解说/反思后台任务，防止旧一局的内容串进新一局日志
def test_reset_cancels_commentary_and_reflection_tasks():
    eng = make_engine()
    fake_commentary, fake_reflection = _FakeTask(), _FakeTask()
    eng._commentary_task = fake_commentary
    eng._reflection_task = fake_reflection
    eng.reset()
    assert fake_commentary.cancelled and fake_reflection.cancelled
    assert eng._commentary_task is None and eng._reflection_task is None


# 测试构造 Engine 不得写真实 logs/replays/stats：否则每跑一次 pytest 就会触发
# "保留最近 50 个" 的轮转，把真实对局记录删掉（由 tests/conftest.py 的 autouse fixture 保证）
def test_engine_files_isolated_from_project():
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    real_logs = os.path.join(base, "logs")
    real_replays = os.path.join(base, "replays")
    before = {d: (set(os.listdir(d)) if os.path.isdir(d) else None) for d in (real_logs, real_replays)}
    eng = make_engine()
    eng.reset()
    after = {d: (set(os.listdir(d)) if os.path.isdir(d) else None) for d in (real_logs, real_replays)}
    assert after == before
    assert os.path.dirname(eng.log_path) != real_logs
