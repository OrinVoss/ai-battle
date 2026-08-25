"""工具定义（给模型看的函数调用 Schema）与行动结算。"""

import random

DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "move", "description": "向指定方向移动一格（消耗1能量）。", "parameters": {"type": "object", "properties": {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]}}, "required": ["direction"]}}},
    {"type": "function", "function": {"name": "gather", "description": "在当前格子采集资源：草地30%捡到食物，森林50%找到野果，食物矿脉(f)采到食物，矿石矿脉(o)采到矿石。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "rest", "description": "原地休息，恢复20能量。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "eat", "description": "吃一份食物，恢复12生命。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "attack", "description": "攻击视野内(距离≤2)的目标，消耗5能量，造成8-14伤害(有武器+10)。", "parameters": {"type": "object", "properties": {"target": {"type": "string", "description": "目标代理的名字"}}, "required": ["target"]}}},
    {"type": "function", "function": {"name": "talk", "description": "说话，距离4格内的代理能听到。", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "shout", "description": "大声喊话，全场都能听到，但会暴露你的位置。", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "whisper", "description": "悄悄话，只让指定的人听到。", "parameters": {"type": "object", "properties": {"target": {"type": "string"}, "text": {"type": "string"}}, "required": ["target", "text"]}}},
    {"type": "function", "function": {"name": "inspect", "description": "观察指定代理的详细状态。", "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}}},
    {"type": "function", "function": {"name": "loot", "description": "搜刮同一格内尸体的物品。", "parameters": {"type": "object", "properties": {"target": {"type": "string", "description": "尸体所属代理的名字"}}, "required": ["target"]}}},
    {"type": "function", "function": {"name": "craft", "description": "用3块矿石打造武器（攻击+10）。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "give", "description": "单方面把食物或矿石赠送给距离4格内的其他存活代理，受赠者会领情（关系+2）。", "parameters": {"type": "object", "properties": {"target": {"type": "string", "description": "受赠者名字"}, "item": {"type": "string", "enum": ["food", "ore"], "description": "赠送物品"}, "amount": {"type": "integer", "description": "赠送数量"}}, "required": ["target", "item", "amount"]}}},
    {"type": "function", "function": {"name": "propose_trade", "description": "向距离4格内的代理提出以物易物交易。", "parameters": {"type": "object", "properties": {"target": {"type": "string"}, "offer_item": {"type": "string", "enum": ["food", "ore"]}, "offer_amount": {"type": "integer"}, "want_item": {"type": "string", "enum": ["food", "ore"]}, "want_amount": {"type": "integer"}}, "required": ["target", "offer_item", "offer_amount", "want_item", "want_amount"]}}},
    {"type": "function", "function": {"name": "accept_trade", "description": "接受收到的交易提案。", "parameters": {"type": "object", "properties": {"trade_id": {"type": "string"}}, "required": ["trade_id"]}}},
    {"type": "function", "function": {"name": "decline_trade", "description": "拒绝收到的交易提案。", "parameters": {"type": "object", "properties": {"trade_id": {"type": "string"}}, "required": ["trade_id"]}}},
    {"type": "function", "function": {"name": "remember", "description": "把重要的事记进长期笔记（最多10条），比如恩怨、盟约、观察结论。", "parameters": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}}},
    {"type": "function", "function": {"name": "mark_ally", "description": "宣布与某人结盟（关系提升为至少+3）。", "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}}},
    {"type": "function", "function": {"name": "mark_enemy", "description": "宣布与某人敌对（关系降至-3）。", "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}}},
    {"type": "function", "function": {"name": "wait", "description": "原地待命，观察局势。", "parameters": {"type": "object", "properties": {}}}},
]

# 给所有工具注入可选的 reason 参数：模型的"内心想法"，只展示给观战者，不影响世界逻辑
for _t in TOOL_SCHEMAS:
    _p = _t["function"]["parameters"]
    _p.setdefault("properties", {})["reason"] = {
        "type": "string",
        "description": "（可选但强烈建议）用一句话写出你此刻的思考与行动理由。观战者能看到它，但其他代理看不到你的想法。",
    }


def _target(world, name, actor=None):
    """按名字找存活目标；actor 本人不算合法目标（禁止攻击/交易/密谋自己）。"""
    t = world.by_name(name)
    if not t or not t.alive or t is actor:
        return None
    return t


def _items_str(items, weapon=False):
    """物品字典转人类可读文本：食物x2 矿石x1（+武器）。"""
    parts = []
    if items.get("food"):
        parts.append(f"食物x{items['food']}")
    if items.get("ore"):
        parts.append(f"矿石x{items['ore']}")
    if weapon:
        parts.append("武器")
    return " ".join(parts) if parts else "空无一物"


# ---------- 各行动结算：返回 (反馈给代理的话, [(日志类型, 日志文本), ...]) ----------

def resolve_move(a, w, args, ctx):
    d = args.get("direction", "")
    if d not in DIRS:
        return "方向无效", []
    if a.energy < 1:
        return "能量不足，无法移动", []
    dx, dy = DIRS[d]
    x, y = a.pos
    nx, ny = x + dx, y + dy
    if w.is_blocked(nx, ny):
        return "前方是障碍，过不去", []
    a.pos = (nx, ny)
    a.energy = max(0, a.energy - 1)
    return f"移动到 ({nx},{ny})", [(
        "move",
        f"🚶 {a.name} 移动到 ({nx},{ny})",
        {"actor": a.name, "action": "move", "from": [x, y], "to": [nx, ny]},
    )]


def resolve_gather(a, w, args, ctx):
    x, y = a.pos
    t = w.tile(x, y)
    mult = 2 if getattr(w, "harvest", False) else 1  # 丰收季产出翻倍
    rate = getattr(w, "gather_mult", 1.0)            # 难度：采集成功率倍率
    if t in ("f", "o") and (x, y) not in w.deposits:
        w.grid[y][x] = "."  # 地形是矿脉但已无储量记录：修正为平地
        return "矿脉已枯竭", []
    if t == "f":
        amount = (1 + random.choice([0, 1])) * mult
        a.items["food"] += amount
        w.consume(x, y)
        return "采集到食物", [("item", f"🌾 {a.name} 在食物矿脉采集到食物", {"actor": a.name, "action": "gather", "resource": "food", "amount": amount})]
    if t == "o":
        amount = 1 * mult
        a.items["ore"] += amount
        w.consume(x, y)
        return "采集到矿石", [("item", f"⛏️ {a.name} 在矿石矿脉采到矿石", {"actor": a.name, "action": "gather", "resource": "ore", "amount": amount})]
    if t == "F":
        if random.random() < 0.5 * rate:
            amount = 1 * mult
            a.items["food"] += amount
            return "在森林里找到野果", [("item", f"🌰 {a.name} 在森林里找到野果", {"actor": a.name, "action": "gather", "resource": "food", "amount": amount})]
        return "森林里什么也没找到", []
    if t == ".":
        if random.random() < 0.3 * rate:
            amount = 1 * mult
            a.items["food"] += amount
            return "在草丛里捡到食物", [("item", f"🍞 {a.name} 捡到食物", {"actor": a.name, "action": "gather", "resource": "food", "amount": amount})]
        return "一无所获", []
    return "这里没有可采集的东西", []


def resolve_rest(a, w, args, ctx):
    a.energy = min(100, a.energy + 20)
    return "休息了一会儿，能量恢复", [("move", f"😴 {a.name} 原地休息", {"actor": a.name, "action": "rest"})]


def resolve_eat(a, w, args, ctx):
    if a.items["food"] <= 0:
        return "没有食物可吃", []
    a.items["food"] -= 1
    a.hp = min(100, a.hp + 12)
    return "吃掉一份食物，生命恢复", [("item", f"🍽️ {a.name} 吃了一份食物", {"actor": a.name, "action": "eat", "resource": "food", "amount": 1})]


def resolve_attack(a, w, args, ctx):
    t = _target(w, args.get("target", ""), a)
    if not t:
        return "目标不存在或已死亡", []
    if w.dist(a.pos, t.pos) > 2:
        return "目标太远，够不着", []
    if a.energy < 5:
        return "能量不足，无法攻击", []
    a.energy -= 5
    # 难度：伤害倍率作用于最终伤害（含武器加成）；夜晚再额外+3
    night = getattr(w, "night", False)
    dmg = round((random.randint(8, 14) + (10 if a.weapon else 0)) * getattr(w, "damage_mult", 1.0))
    if night:
        dmg += 3
    t.hp -= dmg
    a.relation[t.name] = a.relation.get(t.name, 0) - 4
    t.relation[a.name] = t.relation.get(a.name, 0) - 6
    t.last_attacker = a.name
    night_note = "（夜晚偷袭+3）" if night else ""
    remaining_hp = max(0, t.hp)
    logs = [(
        "fight",
        f"⚔️ {a.name} 攻击 {t.name}，造成 {dmg} 点伤害{night_note}（{t.name} 剩余 HP {remaining_hp}）",
        {"attacker": a.name, "victim": t.name, "damage": dmg, "remaining_hp": remaining_hp, "night_bonus": night},
    )]
    if a.weapon:
        a.weapon_durability -= 1
        if a.weapon_durability <= 0:
            a.weapon = False
            a.weapon_durability = 0
            logs.append(("fight", f"💥 {a.name} 的武器碎裂了！", {"actor": a.name, "weapon_broke": True}))
    if t.hp <= 0:
        t.alive = False
        t.state = "死亡"
        a.kills += 1
        logs.append((
            "death",
            f"💀 {t.name} 被 {a.name} 杀死！掉落了 {_items_str(t.items, t.weapon)}",
            {
                "victim": t.name,
                "attacker": a.name,
                "cause": "attack",
                "loot": {"food": t.items["food"], "ore": t.items["ore"], "weapon": 1 if t.weapon else 0},
                "pos": list(t.pos),
            },
        ))
        # 附近的存活者目睹死亡，知道尸体位置（搜刮的前提）
        for o in w.agents:
            if o.alive and o is not a and w.dist(o.pos, t.pos) <= 6:
                o.add_event(ctx.turn, f"[目睹] {t.name} 被 {a.name} 杀死在 {t.pos}")
    return f"对 {t.name} 造成 {dmg} 伤害{night_note}", logs


def resolve_talk(a, w, args, ctx):
    text = (args.get("text", "") or "").strip()[:120]
    if not text:
        return "话到嘴边又咽了回去", []
    a.last_talk = ctx.turn
    for o in w.agents:
        if o is a or not o.alive:
            continue
        if w.dist(a.pos, o.pos) <= 4:
            o.add_event(ctx.turn, f"[{a.name} 说] {text}")
    return f"你说了：{text}", [("talk", f"💬 {a.name}：{text}")]


def resolve_shout(a, w, args, ctx):
    text = (args.get("text", "") or "").strip()[:120]
    if not text:
        return "喊了个寂寞", []
    a.last_talk = ctx.turn
    x, y = a.pos
    for o in w.agents:
        if o is a or not o.alive:
            continue
        o.add_event(ctx.turn, f"[{a.name} 大喊(位置{x},{y})] {text}")
    return f"你喊了：{text}", [("talk", f"📢 {a.name}（{x},{y}）大喊：{text}")]


def resolve_whisper(a, w, args, ctx):
    t = _target(w, args.get("target", ""), a)
    text = (args.get("text", "") or "").strip()[:120]
    if not t:
        return "对方不在", []
    if not text:
        return "不知道说什么", []
    a.last_talk = ctx.turn
    t.add_event(ctx.turn, f"[{a.name} 悄悄对你说] {text}")
    return f"你悄悄告诉 {t.name}：{text}", [("talk", f"🤫 {a.name} 对 {t.name} 悄声说：{text}")]


def resolve_inspect(a, w, args, ctx):
    t = w.by_name(args.get("target", ""))
    if not t:
        return "查无此人", []
    if not t.alive:
        return f"{t.name} 已经死了", []
    vision = 3 if getattr(w, "night", False) else 6
    if w.dist(a.pos, t.pos) > vision:
        return "距离太远，看不到对方", []
    weapon_str = f"有（耐久{t.weapon_durability}）" if t.weapon else "无"
    return (
        f"{t.name}: HP{t.hp} 能量{t.energy} 位置{t.pos} 食物x{t.items['food']} "
        f"矿石x{t.items['ore']} 武器{weapon_str} 对你态度{t.relation.get(a.name, 0)}"
    ), []


def resolve_loot(a, w, args, ctx):
    t = w.by_name(args.get("target", ""))
    if not t or t.alive:
        return "目标还活着，没法搜刮", []
    if t.pos != a.pos:
        return "尸体不在这里", []
    got = dict(t.items)
    a.items["food"] += got["food"]
    a.items["ore"] += got["ore"]
    t.items = {"food": 0, "ore": 0}
    extra = ""
    weapon_got = 0
    if t.weapon and not a.weapon:
        # 缴获死者的武器（含剩余耐久）；自己已有武器则死者武器随尸体消失
        a.weapon = True
        a.weapon_durability = t.weapon_durability
        t.weapon = False
        t.weapon_durability = 0
        extra = f"，并缴获了武器（耐久{a.weapon_durability}）"
        weapon_got = 1
    elif t.weapon and a.weapon:
        extra = "，死者的武器随尸体消失了"
    data = {"actor": a.name, "action": "loot", "resource": "food", "amount": got["food"]}
    if got["ore"]:
        data["ore"] = got["ore"]
    if weapon_got:
        data["weapon"] = weapon_got
    return f"搜刮到 {_items_str(got)}{extra}", [("item", f"🪦 {a.name} 搜刮了 {t.name} 的尸体，得到 {_items_str(got)}{extra}", data)]


def resolve_craft(a, w, args, ctx):
    if a.weapon:
        return "已经有武器了", []
    if a.items["ore"] < 3:
        return "矿石不够（需要3块）", []
    a.items["ore"] -= 3
    a.weapon = True
    a.weapon_durability = 6
    return "打造了一把武器（攻击+10，耐久6）", [("item", f"🔨 {a.name} 用3块矿石打造了武器！", {"actor": a.name, "action": "craft", "resource": "weapon", "amount": 1})]


def resolve_give(a, w, args, ctx):
    t = _target(w, args.get("target", ""), a)
    if not t:
        return "赠送对象不存在或已死亡", []
    if w.dist(a.pos, t.pos) > 4:
        return "对方太远，没法赠送", []
    item = args.get("item")
    if item not in ("food", "ore"):
        return "只能赠送 food 或 ore", []
    try:
        amount = int(args.get("amount", 0))
    except (TypeError, ValueError):
        return "赠送数量无效", []
    if amount < 1:
        return "赠送数量至少为1", []
    if a.items.get(item, 0) < amount:
        return f"你的{item}不够", []
    a.items[item] -= amount
    t.items[item] += amount
    t.relation[a.name] = t.relation.get(a.name, 0) + 2
    return (
        f"你送给 {t.name} {amount}个{item}，{t.name} 对你领情了",
        [("trade", f"🎁 {a.name} 送给 {t.name} {amount}个{item}", {
            "from": a.name, "to": t.name, "offer_item": item, "offer_amount": amount, "result": "given"
        })],
    )


def resolve_propose_trade(a, w, args, ctx):
    t = _target(w, args.get("target", ""), a)
    if not t:
        return "交易对象不存在", []
    if w.dist(a.pos, t.pos) > 4:
        return "对方太远，没法交易", []
    if t.pending_trade:
        return "对方正在处理其他交易，稍后再试", []
    offer = args.get("offer_item")
    want = args.get("want_item")
    try:
        on = int(args.get("offer_amount", 0))
        wn = int(args.get("want_amount", 0))
    except (TypeError, ValueError):
        return "交易数量无效", []
    if offer not in ("food", "ore") or want not in ("food", "ore"):
        return "交易物品无效", []
    if on < 1 or wn < 1:
        return "交易数量无效", []
    if a.items.get(offer, 0) < on:
        return f"你没有那么多{offer}", []
    tid = f"T{ctx.turn}-{a.id}"
    tr = {"id": tid, "from": a.name, "to": t.name, "offer": offer, "on": on, "want": want, "wn": wn}
    w.pending_trades.append(tr)
    t.pending_trade = tr
    return f"已向 {t.name} 提出交易", [("trade", f"🤝 {a.name} 向 {t.name} 提出交易：{on}个{offer} 换 {wn}个{want}", {
        "from": a.name, "to": t.name, "offer_item": offer, "offer_amount": on,
        "want_item": want, "want_amount": wn, "result": "proposed"
    })]


def resolve_accept_trade(a, w, args, ctx):
    tr = a.pending_trade
    if not tr or tr["id"] != args.get("trade_id"):
        return "没有这笔交易", []

    def cancel():
        a.pending_trade = None
        if tr in w.pending_trades:
            w.pending_trades.remove(tr)

    offerer = w.by_name(tr["from"])
    if not offerer or not offerer.alive:
        cancel()  # 交易方已死亡，顺手清空挂单
        return "交易方已死亡", []
    if w.dist(a.pos, offerer.pos) > 4:
        cancel()  # 报价后走远了，交易作废
        return "对方已走远，交易取消", []
    if a.items.get(tr["want"], 0) < tr["wn"]:
        return "你的东西不够，交易取消", []
    if offerer.items.get(tr["offer"], 0) < tr["on"]:
        return "对方的东西不够，交易取消", []
    offerer.items[tr["offer"]] -= tr["on"]
    a.items[tr["want"]] -= tr["wn"]
    a.items[tr["offer"]] += tr["on"]
    offerer.items[tr["want"]] += tr["wn"]
    a.pending_trade = None
    if tr in w.pending_trades:
        w.pending_trades.remove(tr)
    a.relation[offerer.name] = a.relation.get(offerer.name, 0) + 3
    offerer.relation[a.name] = offerer.relation.get(a.name, 0) + 3
    return "交易完成", [("trade", f"✅ 交易达成：{a.name} 用 {tr['wn']}个{tr['want']} 换到 {tr['on']}个{tr['offer']}", {
        "from": offerer.name, "to": a.name, "offer_item": tr["offer"], "offer_amount": tr["on"],
        "want_item": tr["want"], "want_amount": tr["wn"], "result": "accepted"
    })]


def resolve_decline_trade(a, w, args, ctx):
    tr = a.pending_trade
    if not tr or tr["id"] != args.get("trade_id"):
        return "没有这笔交易", []
    a.pending_trade = None
    if tr in w.pending_trades:
        w.pending_trades.remove(tr)
    return "你拒绝了交易", [("trade", f"❌ {a.name} 拒绝了 {tr['from']} 的交易", {
        "from": tr["from"], "to": a.name, "offer_item": tr["offer"], "offer_amount": tr["on"],
        "want_item": tr["want"], "want_amount": tr["wn"], "result": "declined"
    })]


def resolve_remember(a, w, args, ctx):
    note = (args.get("note", "") or "").strip()[:100]
    if not note:
        return "记了个寂寞", []
    a.notes.append(f"[T{ctx.turn}] {note}")
    if len(a.notes) > 10:
        a.notes.pop(0)
    return "已记入长期笔记", []


def resolve_mark_ally(a, w, args, ctx):
    t = _target(w, args.get("target", ""), a)
    if not t:
        return "目标不存在", []
    a.relation[t.name] = max(a.relation.get(t.name, 0), 3)
    return f"你宣布与 {t.name} 结盟", [("sys", f"🤜 {a.name} 宣布与 {t.name} 结为盟友！")]


def resolve_mark_enemy(a, w, args, ctx):
    t = _target(w, args.get("target", ""), a)
    if not t:
        return "目标不存在", []
    a.relation[t.name] = min(a.relation.get(t.name, 0), -3)
    return f"你宣布与 {t.name} 敌对", [("sys", f"💢 {a.name} 宣布与 {t.name} 敌对！")]


def resolve_wait(a, w, args, ctx):
    return "原地待命，观察四周", [("move", f"👀 {a.name} 原地待命", {"actor": a.name, "action": "wait"})]


RESOLVE = {
    "move": resolve_move,
    "gather": resolve_gather,
    "rest": resolve_rest,
    "eat": resolve_eat,
    "attack": resolve_attack,
    "talk": resolve_talk,
    "shout": resolve_shout,
    "whisper": resolve_whisper,
    "inspect": resolve_inspect,
    "loot": resolve_loot,
    "craft": resolve_craft,
    "give": resolve_give,
    "propose_trade": resolve_propose_trade,
    "accept_trade": resolve_accept_trade,
    "decline_trade": resolve_decline_trade,
    "remember": resolve_remember,
    "mark_ally": resolve_mark_ally,
    "mark_enemy": resolve_mark_enemy,
    "wait": resolve_wait,
}
