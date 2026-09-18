"""工具结算逻辑的纯单元测试：不依赖网络、API key 和 Engine 主循环。"""

from agent import Agent
from world import World
import tools


class Ctx:
    """最小 TurnCtx stub：只提供 turn 和 log。"""

    def __init__(self, turn=1):
        self.turn = turn
        self.logs = []

    def log(self, kind, text):
        self.logs.append((kind, text))


def flat_world(w=8, h=8, seed=1):
    """生成一块全平地的世界，方便精确摆场景。"""
    world = World({"world": {"width": w, "height": h, "seed": seed}})
    world.grid = [["." for _ in range(w)] for _ in range(h)]
    world.deposits = {}
    world.depleted = {}
    return world


def make_agent(world, name, pos=(0, 0), idx=0):
    a = Agent({"name": name, "emoji": "🤖", "provider": "none", "model": "demo"}, idx, world)
    a.pos = pos
    return a


def pair():
    """两个相邻代理的标准场景。"""
    w = flat_world()
    a = make_agent(w, "甲", (2, 2), 0)
    b = make_agent(w, "乙", (3, 2), 1)
    w.agents = [a, b]
    return w, a, b


# ---------- move ----------

def test_move_blocked_and_energy():
    w = flat_world()
    a = make_agent(w, "甲", (1, 1))
    w.agents = [a]
    w.grid[0][1] = "~"  # 上方是水域
    fb, logs = tools.resolve_move(a, w, {"direction": "up"}, Ctx())
    assert "障碍" in fb
    assert a.pos == (1, 1) and a.energy == 100 and logs == []
    fb, logs = tools.resolve_move(a, w, {"direction": "down"}, Ctx())
    assert a.pos == (1, 2) and a.energy == 99  # 正常移动扣 1 能量
    assert logs and logs[0][0] == "move"
    data = logs[0][2]
    assert data["actor"] == "甲" and data["action"] == "move"
    assert data["from"] == [1, 1] and data["to"] == [1, 2]


def test_rest_wait_log_has_actor_and_action():
    w = flat_world()
    a = make_agent(w, "甲", (1, 1))
    w.agents = [a]
    _, logs = tools.resolve_rest(a, w, {}, Ctx())
    assert logs[0][2] == {"actor": "甲", "action": "rest"}
    _, logs = tools.resolve_wait(a, w, {}, Ctx())
    assert logs[0][2] == {"actor": "甲", "action": "wait"}


# ---------- gather ----------

def test_gather_depletes_deposit():
    w = flat_world()
    a = make_agent(w, "甲", (2, 2))
    w.agents = [a]
    w.grid[2][2] = "f"
    w.deposits[(2, 2)] = 1
    food0 = a.items["food"]
    fb, logs = tools.resolve_gather(a, w, {}, Ctx())
    assert "食物" in fb and a.items["food"] > food0
    assert (2, 2) not in w.deposits          # 矿脉采空
    assert w.grid[2][2] == "."               # 格子变回平地
    assert w.depleted[(2, 2)] == "f"         # 记录为采空，等 regen 再长


def test_gather_harvest_double():
    w = flat_world()
    a = make_agent(w, "甲", (2, 2))
    w.agents = [a]
    w.grid[2][2] = "o"
    w.deposits[(2, 2)] = 5
    w.harvest = True  # 丰收季产出翻倍
    tools.resolve_gather(a, w, {}, Ctx())
    assert a.items["ore"] == 2


# ---------- eat ----------

def test_eat_without_food():
    w, a, _ = pair()
    a.items["food"] = 0
    hp0 = a.hp
    fb, logs = tools.resolve_eat(a, w, {}, Ctx())
    assert "没有食物" in fb and a.hp == hp0 and logs == []


def test_eat_craft_log_has_structured_fields():
    w, a, _ = pair()
    a.items["food"] = 1
    _, logs = tools.resolve_eat(a, w, {}, Ctx())
    assert logs[0][2] == {"actor": "甲", "action": "eat", "resource": "food", "amount": 1}
    a.items["ore"] = 3
    _, logs = tools.resolve_craft(a, w, {}, Ctx())
    assert logs[0][2] == {"actor": "甲", "action": "craft", "resource": "weapon", "amount": 1}


def test_gather_log_has_structured_fields():
    w = flat_world()
    a = make_agent(w, "甲", (2, 2))
    w.agents = [a]
    w.grid[2][2] = "o"
    w.deposits[(2, 2)] = 5
    _, logs = tools.resolve_gather(a, w, {}, Ctx())
    data = logs[0][2]
    assert data["actor"] == "甲" and data["action"] == "gather"
    assert data["resource"] == "ore" and data["amount"] == 1


def test_loot_log_has_structured_fields():
    w, a, b = pair()
    b.alive = False
    b.state = "死亡"
    b.pos = a.pos
    b.items = {"food": 2, "ore": 1}
    _, logs = tools.resolve_loot(a, w, {"target": "乙"}, Ctx())
    data = logs[0][2]
    assert data["actor"] == "甲" and data["action"] == "loot"
    assert data["amount"] == 2 and data.get("ore") == 1


# ---------- attack / 武器耐久 ----------

def test_attack_kill_drops_relations_kills():
    w, a, b = pair()
    b.hp = 5  # 一刀必杀
    fb, logs = tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    assert not b.alive and b.state == "死亡"
    assert a.kills == 1                                    # 击杀数 +1
    assert a.relation["乙"] == -4 and b.relation["甲"] == -6  # 结仇
    texts = [item[1] for item in logs]
    assert any("杀死" in t and "掉落" in t for t in texts)   # 致死掉落播报


def test_attack_log_has_structured_fields(monkeypatch):
    w, a, b = pair()
    monkeypatch.setattr(tools.random, "randint", lambda lo, hi: 10)
    fb, logs = tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    fight = next(item for item in logs if item[0] == "fight" and "攻击" in item[1])
    data = fight[2]
    assert data["attacker"] == "甲"
    assert data["victim"] == "乙"
    assert data["damage"] == 10
    assert data["remaining_hp"] == 90
    assert data["night_bonus"] is False


def test_death_log_has_structured_fields():
    w, a, b = pair()
    b.hp = 5
    b.items = {"food": 2, "ore": 1}
    b.weapon = True
    _, logs = tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    death = next(item for item in logs if item[0] == "death")
    data = death[2]
    assert data["victim"] == "乙"
    assert data["attacker"] == "甲"
    assert data["cause"] == "attack"
    assert data["loot"] == {"food": 2, "ore": 1, "weapon": 1}
    assert data["pos"] == [3, 2]


def test_attack_weapon_durability_break():
    w, a, b = pair()
    a.weapon = True
    a.weapon_durability = 1  # 这一击后归零
    _, logs = tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    assert a.weapon is False and a.weapon_durability == 0
    assert b.hp <= 100 - 18  # 这一击仍吃到武器加成（8~14+10）
    assert any("武器碎裂" in item[1] for item in logs)
    # 碎裂后再攻击：无武器伤害最多 14
    b.hp = 100
    a.energy = 100
    tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    assert 100 - b.hp <= 14


def test_attack_night_bonus(monkeypatch):
    w, a, b = pair()
    w.night = True
    monkeypatch.setattr(tools.random, "randint", lambda lo, hi: 10)
    fb, logs = tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    # 基础 10，无武器，夜晚 +3，倍率 1.0 → 13
    assert b.hp == 100 - 13
    assert "夜晚偷袭+3" in fb
    assert any("夜晚偷袭+3" in item[1] for item in logs)
    fight = next(item for item in logs if item[0] == "fight")
    assert fight[2]["night_bonus"] is True


def test_attack_day_no_bonus(monkeypatch):
    w, a, b = pair()
    w.night = False
    monkeypatch.setattr(tools.random, "randint", lambda lo, hi: 10)
    tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    assert b.hp == 100 - 10


# ---------- craft ----------

def test_craft_ore_not_enough():
    w, a, _ = pair()
    a.items["ore"] = 2
    fb, logs = tools.resolve_craft(a, w, {}, Ctx())
    assert "矿石不够" in fb and not a.weapon


def test_craft_success():
    w, a, _ = pair()
    a.items["ore"] = 3
    fb, logs = tools.resolve_craft(a, w, {}, Ctx())
    assert a.weapon is True and a.weapon_durability == 6 and a.items["ore"] == 0
    fb2, _ = tools.resolve_craft(a, w, {}, Ctx())
    assert "已经有武器" in fb2


# ---------- inspect 视野限制 ----------

def test_inspect_vision_limit():
    w, a, b = pair()
    b.pos = (7, 7)  # 距离 (2,2) 为 10 格 > 6
    fb, _ = tools.resolve_inspect(a, w, {"target": "乙"}, Ctx())
    assert "看不到" in fb
    b.pos = (6, 4)  # 距离 6 格，白天视野内
    fb, _ = tools.resolve_inspect(a, w, {"target": "乙"}, Ctx())
    assert "乙" in fb and "HP" in fb
    w.night = True  # 夜晚视野 3 格
    fb, _ = tools.resolve_inspect(a, w, {"target": "乙"}, Ctx())
    assert "看不到" in fb


# ---------- 赠送 ----------

def test_give_success_changes_relation():
    w, a, b = pair()
    a.items = {"food": 3, "ore": 1}
    b.items = {"food": 0, "ore": 0}
    fb, logs = tools.resolve_give(a, w, {"target": "乙", "item": "food", "amount": 2}, Ctx())
    assert a.items == {"food": 1, "ore": 1}
    assert b.items == {"food": 2, "ore": 0}
    assert b.relation.get("甲", 0) == 2
    assert "送给 乙 2个food" in fb
    assert any("🎁 甲 送给 乙 2个food" in item[1] for item in logs)
    data = logs[0][2]
    assert data == {"from": "甲", "to": "乙", "offer_item": "food", "offer_amount": 2, "result": "given"}


def test_give_not_enough_items():
    w, a, b = pair()
    a.items = {"food": 1, "ore": 0}
    fb, _ = tools.resolve_give(a, w, {"target": "乙", "item": "food", "amount": 2}, Ctx())
    assert "food不够" in fb
    assert a.items == {"food": 1, "ore": 0}


def test_give_too_far():
    w, a, b = pair()
    b.pos = (7, 7)
    a.items = {"food": 3, "ore": 0}
    fb, _ = tools.resolve_give(a, w, {"target": "乙", "item": "food", "amount": 1}, Ctx())
    assert "太远" in fb
    assert a.items["food"] == 3


def test_give_self_rejected():
    w, a, _ = pair()
    a.items = {"food": 3, "ore": 0}
    fb, _ = tools.resolve_give(a, w, {"target": "甲", "item": "food", "amount": 1}, Ctx())
    assert "不存在" in fb or "对象不存在" in fb
    assert a.items["food"] == 3


# ---------- 交易全流程 ----------

def test_trade_propose_accept_flow():
    w, a, b = pair()  # 距离 1，可交易
    a.items = {"food": 3, "ore": 0}
    b.items = {"food": 0, "ore": 2}
    fb, logs = tools.resolve_propose_trade(
        a, w, {"target": "乙", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    assert "已提出交易" in fb or "提出" in fb
    tr = b.pending_trade
    assert tr and tr["from"] == "甲"
    prop = logs[0][2]
    assert prop == {"from": "甲", "to": "乙", "offer_item": "food", "offer_amount": 1,
                    "want_item": "ore", "want_amount": 1, "result": "proposed"}
    fb, logs = tools.resolve_accept_trade(b, w, {"trade_id": tr["id"]}, Ctx())
    assert "完成" in fb
    assert a.items == {"food": 2, "ore": 1}
    assert b.items == {"food": 1, "ore": 1}
    assert a.relation["乙"] == 3 and b.relation["甲"] == 3
    assert b.pending_trade is None and w.pending_trades == []
    acc = logs[0][2]
    assert acc == {"from": "甲", "to": "乙", "offer_item": "food", "offer_amount": 1,
                   "want_item": "ore", "want_amount": 1, "result": "accepted"}


def test_trade_decline_flow():
    w, a, b = pair()
    a.items = {"food": 3, "ore": 0}
    b.items = {"food": 0, "ore": 2}
    tools.resolve_propose_trade(
        a, w, {"target": "乙", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    tr = b.pending_trade
    fb, logs = tools.resolve_decline_trade(b, w, {"trade_id": tr["id"]}, Ctx())
    assert "拒绝" in fb
    assert b.pending_trade is None and w.pending_trades == []
    assert a.items == {"food": 3, "ore": 0} and b.items == {"food": 0, "ore": 2}
    dec = logs[0][2]
    assert dec == {"from": "甲", "to": "乙", "offer_item": "food", "offer_amount": 1,
                   "want_item": "ore", "want_amount": 1, "result": "declined"}


def test_trade_overwrite_rejected():
    w, a, b = pair()
    c = make_agent(w, "丙", (4, 2), 2)
    w.agents = [a, b, c]
    a.items = {"food": 3, "ore": 0}
    c.items = {"food": 3, "ore": 0}
    tools.resolve_propose_trade(
        a, w, {"target": "乙", "offer_item": "food", "offer_amount": 1,
               "want_item": "ore", "want_amount": 1}, Ctx())
    first = b.pending_trade
    fb, _ = tools.resolve_propose_trade(
        c, w, {"target": "乙", "offer_item": "food", "offer_amount": 2,
               "want_item": "ore", "want_amount": 1}, Ctx())
    assert "正在处理其他交易" in fb      # 不再静默覆盖
    assert b.pending_trade is first      # 仍是最初那笔


# ---------- loot 搜尸 ----------

def test_loot_corpse():
    w, a, b = pair()
    b.alive = False
    b.state = "死亡"
    b.pos = a.pos  # 尸体在同一格
    b.items = {"food": 2, "ore": 1}
    a.items = {"food": 0, "ore": 0}
    fb, logs = tools.resolve_loot(a, w, {"target": "乙"}, Ctx())
    assert "搜刮" in fb
    assert a.items == {"food": 2, "ore": 1}
    assert b.items == {"food": 0, "ore": 0}
    # 活人不能被搜刮
    b.alive = True
    fb2, _ = tools.resolve_loot(a, w, {"target": "乙"}, Ctx())
    assert "还活着" in fb2


def test_loot_weapon_transfer():
    """死者有武器且搜刮者没有时，缴获武器（含剩余耐久）。"""
    w, a, b = pair()
    b.alive = False
    b.state = "死亡"
    b.pos = a.pos
    b.items = {"food": 0, "ore": 0}
    b.weapon = True
    b.weapon_durability = 4
    fb, logs = tools.resolve_loot(a, w, {"target": "乙"}, Ctx())
    assert "缴获" in fb
    assert a.weapon is True and a.weapon_durability == 4
    assert b.weapon is False and b.weapon_durability == 0


def test_loot_weapon_vanishes_when_actor_has_weapon():
    """自己已有武器时，死者武器不继承，且提示文案正确。"""
    w, a, b = pair()
    b.alive = False
    b.state = "死亡"
    b.pos = a.pos
    b.items = {"food": 0, "ore": 0}
    b.weapon = True
    b.weapon_durability = 4
    a.weapon = True
    a.weapon_durability = 5
    fb, logs = tools.resolve_loot(a, w, {"target": "乙"}, Ctx())
    assert "缴获" not in fb
    assert "死者的武器随尸体消失了" in fb
    assert a.weapon_durability == 5  # 自己的武器不受影响
    log_text = logs[0][1]
    assert "死者的武器随尸体消失了" in log_text


def test_corpse_visible_in_perception():
    """感知里应列出视野内尸体的名字/位置/物品，让 loot 可操作。"""
    w, a, b = pair()
    b.alive = False
    b.state = "死亡"
    b.pos = (a.pos[0] + 1, a.pos[1])
    b.items = {"food": 3, "ore": 2}
    txt = a.perceive(w, 1)
    assert "尸体" in txt and "乙" in txt
    assert "食物x3" in txt and "矿石x2" in txt


def test_attack_kill_notifies_witnesses():
    """击杀时视野内存活者收到尸体位置记忆。"""
    import engine as E
    w, a, b = pair()
    c = w.agents[2] if len(w.agents) > 2 else None
    # pair() 只有两人；手动加旁观者
    if c is None:
        from agent import Agent
        c = Agent({"name": "丙", "provider": "x", "model": "y"}, 2, w)
        c.pos = (b.pos[0] + 1, b.pos[1])
        w.agents.append(c)
    b.hp = 5
    a.energy = 50
    a.pos = b.pos  # 同格必中
    fb, logs = tools.resolve_attack(a, w, {"target": "乙"}, Ctx())
    assert b.alive is False
    assert any("目睹" in m and "乙" in m for m in c.memory)



# ---------- 参数类型容错：模型偶尔把 text/note 写成数字 ----------

def test_text_args_tolerate_non_string():
    w, a, b = pair()
    for fn, args in ((tools.resolve_talk, {"text": 5}),
                     (tools.resolve_shout, {"text": 5}),
                     (tools.resolve_whisper, {"target": "乙", "text": 7}),
                     (tools.resolve_remember, {"note": 42})):
        feedback, logs = fn(a, w, args, Ctx())
        assert isinstance(feedback, str) and feedback      # 不抛异常，且有反馈
        assert isinstance(logs, list)
    assert a.notes == ["[T1] 42"]                          # 数字被转成文本记下
