"""AI 解说员触发逻辑测试（使用 fake LLM，不消耗真实 API）。"""

import asyncio

import engine as engine_mod
from engine import Engine


class FakeHub:
    recorder = None

    async def send(self, type_, payload):
        pass


def make_engine(providers=None, world_extra=None):
    world_extra = dict(world_extra or {})
    cfg = {
        "world": {"width": 8, "height": 6, "seed": 5, **world_extra},
        "providers": providers or {},
        "agents": [
            {"name": "甲", "emoji": "🤖", "provider": "x", "model": "m"},
            {"name": "乙", "emoji": "🤖", "provider": "x", "model": "m"},
        ],
    }
    if "commentator" in world_extra:
        cfg["commentator"] = world_extra.pop("commentator")
    return Engine(cfg, FakeHub())


async def run_turn_and_wait(eng):
    await eng.run_turn()
    tasks = [t for t in (eng._commentary_task, eng._reflection_task) if t]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def run(eng):
    asyncio.run(run_turn_and_wait(eng))


async def fake_llm_act(*args, **kwargs):
    return "wait", {}, "", None


def test_commentary_triggers_on_interval(monkeypatch):
    calls = []

    async def fake_chat(client, model, messages, **kwargs):
        calls.append(messages)
        return "局势扑朔迷离，下一波更精彩！", None

    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    monkeypatch.setattr(engine_mod, "llm_chat", fake_chat)

    eng = make_engine(
        providers={"x": {"name": "X", "base_url": "https://x", "api_key": "sk-x", "models": ["m"]}},
        world_extra={"commentary_interval": 2},
    )
    # 第一回合（turn=1）不触发
    run(eng)
    assert not any(h["kind"] == "commentary" for h in eng.history)
    assert len(calls) == 0

    # 第二回合（turn=2）触发
    run(eng)
    assert any(h["kind"] == "commentary" for h in eng.history)
    assert len(calls) == 1
    assert "局势扑朔迷离" in eng.history[-1]["text"]


def test_commentary_disabled_in_demo_mode(monkeypatch):
    async def fake_chat(client, model, messages, **kwargs):
        return "不该出现", None

    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    monkeypatch.setattr(engine_mod, "llm_chat", fake_chat)
    # 无 provider → demo 模式
    eng = make_engine(providers={}, world_extra={"commentary_interval": 1})
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    run(eng)
    assert not any(h["kind"] == "commentary" for h in eng.history)


def test_commentary_no_pile(monkeypatch):
    calls = [0]
    release = asyncio.Event()

    async def slow_chat(client, model, messages, **kwargs):
        calls[0] += 1
        await release.wait()
        return "慢解说", None

    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    monkeypatch.setattr(engine_mod, "llm_chat", slow_chat)
    eng = make_engine(
        providers={"x": {"name": "X", "base_url": "https://x", "api_key": "sk-x", "models": ["m"]}},
        world_extra={"commentary_interval": 1},
    )

    async def main():
        await eng.run_turn()
        task1 = eng._commentary_task
        assert task1 is not None
        # 解说还没完成时，下一回合不应再发起新调用
        await eng.run_turn()
        assert eng._commentary_task is task1
        release.set()
        await task1

    asyncio.run(main())
    assert calls[0] == 1


def test_commentary_uses_config_commentator(monkeypatch):
    calls = []

    async def fake_chat(client, model, messages, **kwargs):
        calls.append(model)
        return "解说", None

    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    monkeypatch.setattr(engine_mod, "llm_chat", fake_chat)
    cfg = {
        "world": {"width": 8, "height": 6, "seed": 5, "commentary_interval": 1},
        "providers": {
            "x": {"name": "X", "base_url": "https://x", "api_key": "sk-x", "models": ["m1"]},
        },
        "commentator": {"provider": "x", "model": "special-model"},
        "agents": [
            {"name": "甲", "emoji": "🤖", "provider": "x", "model": "m1"},
            {"name": "乙", "emoji": "🤖", "provider": "x", "model": "m1"},
        ],
    }
    eng = Engine(cfg, FakeHub())
    run(eng)
    assert len(calls) == 1
    assert calls[0] == "special-model"


def test_commentary_passes_provider_thinking(monkeypatch):
    """解说/复盘走的是 commentator 自己的 provider 配置，思考开关必须带上，
    否则 deepseek-flash 默认开思考会把 max_tokens 耗光、正文为空、解说静默丢失。"""
    seen = {}

    async def fake_chat(client, model, messages, **kwargs):
        seen.update(kwargs)
        return "解说", None

    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    monkeypatch.setattr(engine_mod, "llm_chat", fake_chat)
    eng = make_engine(
        providers={"x": {"name": "X", "base_url": "https://x", "api_key": "sk-x",
                         "models": ["m"], "thinking": "disabled", "thinking_style": "dashscope"}},
        world_extra={"commentary_interval": 1},
    )
    run(eng)
    assert seen.get("thinking") == "disabled"
    assert seen.get("thinking_style") == "dashscope"
