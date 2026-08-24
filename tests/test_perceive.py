"""perceive() 提示词结构回归测试（DeepSeek 前缀缓存优化）。"""

from agent import Agent
from world import World


def flat_world(w=8, h=8, seed=1, **extra):
    world = World({"world": {"width": w, "height": h, "seed": seed, **extra}})
    world.grid = [["." for _ in range(w)] for _ in range(h)]
    world.deposits = {}
    world.depleted = {}
    return world


def make_agent(world, name, pos=(0, 0), idx=0):
    cfg = {"name": name, "emoji": "🤖", "provider": "none", "model": "m"}
    a = Agent(cfg, idx, world)
    a.pos = pos
    return a


def test_perceive_starts_with_rules():
    w = flat_world()
    a = make_agent(w, "甲", (2, 2), 0)
    w.agents = [a]
    out = a.perceive(w, 1)
    assert out.startswith("【世界规则】"), "规则段必须放在 user 消息最开头"


def test_turn_number_only_at_end():
    w = flat_world()
    a = make_agent(w, "甲", (2, 2), 0)
    w.agents = [a]
    for turn in (1, 2, 5):
        out = a.perceive(w, turn)
        lines = out.splitlines()
        # 最后一行必须是「当前：第 N 回合 · ...」
        assert lines[-1].startswith("当前："), "回合/昼夜信息必须在最后一行"
        assert f"第 {turn} 回合" in lines[-1], f"第 {turn} 回合信息应位于消息末尾"
        # 去掉最后一行后，正文中不能再出现「第 N 回合」
        body = "\n".join(lines[:-1])
        assert f"第 {turn} 回合" not in body, f"第 {turn} 回合不应出现在正文中间"


def test_prefix_stable_across_turns_when_state_unchanged():
    w = flat_world()
    a = make_agent(w, "甲", (3, 3), 0)
    w.agents = [a]
    # 塞一些记忆，让提示词足够长，便于验证前 50% 前缀稳定
    for i in range(12):
        a.add_event(i + 1, f"看到一件不重要的事 {i}")
    out1 = a.perceive(w, 1)
    out2 = a.perceive(w, 2)
    # 状态完全不变时，只有最后的「当前：第 N 回合 · ...」变化，
    # 因此前 50% 字符应当完全一致（连续回合的缓存前缀命中）。
    half1 = len(out1) // 2
    half2 = len(out2) // 2
    assert out1[:half1] == out2[:half2], "状态不变时 user 消息前 50% 必须完全一致"


def test_silent_hint_is_volatile_and_near_end():
    w = flat_world()
    a = make_agent(w, "甲", (2, 2), 0)
    w.agents = [a]
    a.last_talk = 0
    out = a.perceive(w, 3)
    # 3 回合没说话应当出现提示
    assert "回合没开口" in out
    # 提示行必须在「当前：第 N 回合」之前，且不能在规则/状态等稳定内容之前
    lines = out.splitlines()
    silent_idx = next(i for i, line in enumerate(lines) if "回合没开口" in line)
    current_idx = next(i for i, line in enumerate(lines) if line.startswith("当前："))
    assert silent_idx < current_idx, "催说话提示应位于末尾附近"
    assert silent_idx > 0, "催说话提示不应压到第一行"
