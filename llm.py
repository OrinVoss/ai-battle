"""多模型客户端：DeepSeek / 硅基流动 / OpenRouter（OpenAI 兼容协议）+ 演示模式。"""

import json
import os
import random

from openai import AsyncOpenAI

from tools import DIRS


class ProviderError(Exception):
    pass


def _load_dotenv(path=None):
    """零依赖 .env 加载：KEY=VALUE 逐行读取，不覆盖已存在的环境变量。"""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass  # 没有 .env 就用系统环境变量，正常


_load_dotenv()


def build_client(cfg):
    """按 provider 配置构建 AsyncOpenAI 客户端；配置有问题一律抛 ProviderError（回退演示模式）。"""
    try:
        key = cfg.get("api_key") or ""
        if not isinstance(key, str):
            key = ""
        env_name = cfg.get("env_key") or ""
        if not key.strip() and isinstance(env_name, str) and env_name:
            key = os.environ.get(env_name, "") or ""
        if not key.strip():
            raise ProviderError(
                f"缺少 API Key：请在 config.json 的「{cfg.get('name')}」填入 api_key，"
                f"或设置环境变量 {cfg.get('env_key')}"
            )
        base_url = cfg.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ProviderError(f"provider「{cfg.get('name')}」缺少 base_url")
        return AsyncOpenAI(base_url=base_url, api_key=key, timeout=90)
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(f"provider 配置错误：{e}")


def _try_json(s):
    """从文本里解析 JSON 对象：容忍 ``` 围栏和 JSON 后面跟着的解释文字。"""
    if not s:
        return None
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[4:]
    i = s.find("{")
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[i:])
        return obj
    except Exception:
        return None


def _trim_think(s, limit=160):
    """想法太长时只保留结尾（结论通常在后半段）。"""
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return "…" + s[-limit:]


async def llm_act(client, model, messages, tools, temperature=0.9, max_tokens=900, thinking=None):
    """调用模型，返回 (action_name, args_dict, thinking, usage)。

    usage 为 {"prompt": int, "completion": int}，取不到时为 None。
    thinking: None=不设置；"enabled"/"disabled"=通过 extra_body 控制 DeepSeek 思考模式。
    """
    kwargs = dict(
        model=model,
        messages=messages,
        tools=tools or None,
        tool_choice="auto",
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if thinking is not None:
        kwargs["extra_body"] = {"thinking": {"type": thinking}}
    resp = await client.chat.completions.create(**kwargs)
    usage = None
    u = getattr(resp, "usage", None)
    if u is not None:
        usage = {
            "prompt": getattr(u, "prompt_tokens", 0) or 0,
            "completion": getattr(u, "completion_tokens", 0) or 0,
            # DeepSeek 硬盘缓存命中/未命中 token；provider 未返回时保持 None（由调用方估算）
            "cache_hit": getattr(u, "prompt_cache_hit_tokens", None),
            "cache_miss": getattr(u, "prompt_cache_miss_tokens", None),
        }
    msg = resp.choices[0].message
    content = (getattr(msg, "content", None) or "").strip()
    reasoning = (getattr(msg, "reasoning_content", None) or "").strip()
    # 优先走 function calling
    if getattr(msg, "tool_calls", None):
        tc = msg.tool_calls[0]
        args = _try_json(getattr(tc.function, "arguments", "") or "")
        if not isinstance(args, dict):  # 解析出列表/标量等脏数据时按空调用处理
            args = {}
        t2 = str(args.get("reason") or "").strip()  # 精炼理由优先
        thinking = t2 or (content or reasoning)
        return tc.function.name, args, _trim_think(thinking), usage
    # 兜底：模型可能直接把 JSON 写在正文里
    parsed = _try_json(content)
    if isinstance(parsed, dict):
        if "action" in parsed:
            args = parsed.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            thinking = str(parsed.get("thinking") or args.get("reason") or "").strip()
            return str(parsed["action"]), args, thinking, usage
        if "name" in parsed:
            args = parsed.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            thinking = str(parsed.get("thinking") or args.get("reason") or "").strip()
            return str(parsed["name"]), args, _trim_think(thinking), usage
    return None, {}, _trim_think(content or reasoning), usage


async def llm_chat(client, model, messages, temperature=0.9, max_tokens=200, thinking=None):
    """通用聊天调用，返回 (content_text, usage)。

    用于解说员、反思等非工具场景。调用失败直接抛出异常，由调用方决定是否静默。
    """
    kwargs = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
    if thinking is not None:
        kwargs["extra_body"] = {"thinking": {"type": thinking}}
    resp = await client.chat.completions.create(**kwargs)
    usage = None
    u = getattr(resp, "usage", None)
    if u is not None:
        usage = {
            "prompt": getattr(u, "prompt_tokens", 0) or 0,
            "completion": getattr(u, "completion_tokens", 0) or 0,
        }
    msg = resp.choices[0].message
    text = (getattr(msg, "content", None) or "").strip()
    return text, usage


# ---------------------------------------------------------------------------
# 演示模式：没有 API Key 时，用规则 AI 模拟代理行为，方便先看整体效果
# ---------------------------------------------------------------------------

PHRASES = [
    "大家好，认识一下？",
    "你看起来不错，交个朋友？",
    "这片地是我的，走远点。",
    "今天天气不错，适合采集。",
    "有吃的吗？可以换。",
    "别惹我。",
    "我们一起活下去吧。",
    "哼，又来一个。",
]


def _near_threat(agent, world):
    for o in world.agents:
        if o is agent or not o.alive:
            continue
        if world.dist(agent.pos, o.pos) > 2:
            continue
        if agent.relation.get(o.name, 0) < 0 or o.name == agent.last_attacker:
            return o
    return None


def _last_move_blocked(agent):
    """检查最近一条 [行动结果] 是否是移动被障碍阻挡。"""
    for entry in reversed(agent.memory):
        if "[行动结果]" in entry:
            return "过不去" in entry or "无法移动" in entry
    return False


def _pick_move(agent, world, preferred=None):
    """为演示 AI 选一个可移动方向：优先 preferred，避开上次撞墙方向，全堵则 rest。"""
    dirs = ["up", "down", "left", "right"]
    if preferred and preferred in dirs:
        dirs.remove(preferred)
        dirs.insert(0, preferred)
    if _last_move_blocked(agent):
        last = getattr(agent, "_demo_last_dir", None)
        if last and last in dirs:
            dirs.remove(last)
    for d in dirs:
        dx, dy = DIRS[d]
        nx, ny = agent.pos[0] + dx, agent.pos[1] + dy
        if not world.is_blocked(nx, ny):
            agent._demo_last_dir = d
            return "move", {"direction": d}
    return "rest", {}


def demo_decide(agent, world):
    """规则决策：让演示模式也能演出生死存亡的戏。"""
    r = random.random()
    t = agent.traits
    threat = _near_threat(agent, world)

    if threat and agent.energy >= 20 and agent.hp > 30 and t["aggression"] > 0.35 and r < 0.7:
        return "attack", {"target": threat.name}
    if agent.hp < 35 and agent.items["food"] > 0:
        return "eat", {}
    if agent.energy < 22:
        return "rest", {}
    if agent.pending_trade:
        tr = agent.pending_trade
        if agent.items.get(tr["want"], 0) >= tr["wn"] and r < 0.65:
            return "accept_trade", {"trade_id": tr["id"]}
        return "decline_trade", {"trade_id": tr["id"]}
    tx, ty = agent.pos
    ttype = world.tile(tx, ty)
    if ttype in ("f", "o") or (ttype == "F" and r < 0.6) or (ttype == "." and r < 0.3):
        return "gather", {}
    if agent.items["ore"] >= 3 and not agent.weapon:
        return "craft", {}
    nb = world.nearest_agent(agent)
    if nb:
        nd = world.dist(agent.pos, nb.pos)
        # 攻击性强的：贴脸就动手
        if nd <= 2 and t["aggression"] > 0.5 and agent.energy > 25 and agent.hp > 40:
            return "attack", {"target": nb.name}
        # 商人：手里有富余食物就去谈生意
        if nd <= 4 and t["sociability"] > 0.6 and agent.items["food"] >= 3 and r < 0.5:
            return "propose_trade", {
                "target": nb.name, "offer_item": "food", "offer_amount": 1,
                "want_item": "ore", "want_amount": 1,
            }
        # 主动靠近别人（挑衅或社交）
        if nd > 2 and t["aggression"] > 0.6 and r < 0.35:
            d = world.dir_toward(agent.pos, nb.pos)
            if d:
                return _pick_move(agent, world, preferred=d)
        if nd <= 3 and r < 0.35:
            return "talk", {"text": random.choice(PHRASES)}

    res = world.nearest_resource(agent.pos)
    if res:
        d = world.dir_toward(agent.pos, res)
        if d:
            return _pick_move(agent, world, preferred=d)
    return _pick_move(agent, world)
