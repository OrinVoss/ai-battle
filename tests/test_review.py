"""AI 全局复盘测试：LLM 生成、演示模式降级、reset 清空、snapshot/export 携带。"""

import asyncio

import pytest

import engine as engine_mod
from engine import Engine


class FakeHub:
    def __init__(self):
        self.recorder = None
        self.messages = []

    async def send(self, type_, payload):
        self.messages.append({"type": type_, **payload})


def make_engine(providers=None, world_extra=None, agents=None):
    world_extra = dict(world_extra or {})
    agents = agents or [
        {"name": "甲", "emoji": "🤖", "provider": "x", "model": "m"},
        {"name": "乙", "emoji": "🤖", "provider": "x", "model": "m"},
    ]
    cfg = {
        "world": {"width": 8, "height": 6, "seed": 5, **world_extra},
        "providers": providers or {},
        "agents": agents,
    }
    if "commentator" in world_extra:
        cfg["commentator"] = world_extra.pop("commentator")
    return Engine(cfg, FakeHub())


def run_and_wait(eng):
    async def main():
        await eng.run_turn()
        if eng._review_task is not None:
            await eng._review_task
    asyncio.run(main())


async def fake_llm_act(*args, **kwargs):
    return "wait", {}, "", None


def test_review_with_llm(tmp_path, monkeypatch):
    calls = []

    async def fake_chat(client, model, messages, **kwargs):
        calls.append(messages)
        return "局势一波三折，甲最终凭借冷静收割摘冠。MVP 当属甲。", None

    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    monkeypatch.setattr(engine_mod, "llm_chat", fake_chat)
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))

    eng = make_engine(
        providers={"x": {"name": "X", "base_url": "https://x", "api_key": "sk-x", "models": ["m"]}},
        world_extra={"max_turns": 1},
    )
    eng.log_dir = str(tmp_path)
    eng.reset()
    run_and_wait(eng)

    assert eng.winner is not None
    assert eng.match_review == "局势一波三折，甲最终凭借冷静收割摘冠。MVP 当属甲。"
    assert any(e["kind"] == "review" for e in eng.history)

    review_msgs = [m for m in eng.hub.messages if m["type"] == "review"]
    assert len(review_msgs) == 1
    assert review_msgs[0]["text"] == eng.match_review

    snap = eng.snapshot()
    assert snap["match_review"] == eng.match_review

    exp = eng.export_data()
    assert exp["meta"]["review"] == eng.match_review

    # 确认 prompt 里带有关键结构和结束信息
    assert calls
    all_text = "\n".join(m["content"] for m in calls[0])
    assert "一句话总结" in all_text
    assert "结局：max_turns" in all_text


def test_review_demo_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))

    eng = make_engine(providers={}, world_extra={"max_turns": 1})
    eng.log_dir = str(tmp_path)
    eng.reset()
    run_and_wait(eng)

    assert eng.winner is not None
    assert eng.match_review is not None
    assert "演示模式自动生成" in eng.match_review

    review_msgs = [m for m in eng.hub.messages if m["type"] == "review"]
    assert len(review_msgs) == 1
    assert review_msgs[0]["text"] == eng.match_review

    exp = eng.export_data()
    assert exp["meta"]["review"] == eng.match_review


def test_review_reset_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))

    eng = make_engine(world_extra={"max_turns": 1})
    eng.log_dir = str(tmp_path)
    eng.reset()
    run_and_wait(eng)

    assert eng.match_review is not None
    old_task = eng._review_task
    eng.reset()
    assert eng.match_review is None
    assert old_task.cancelled() or old_task.done()
