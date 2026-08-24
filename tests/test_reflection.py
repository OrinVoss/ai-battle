"""定期反思触发逻辑测试（fake LLM，不消耗真实 API）。"""

import asyncio

import engine as engine_mod
from engine import Engine


async def fake_llm_act(*args, **kwargs):
    return "wait", {}, "", None


class FakeHub:
    recorder = None

    async def send(self, type_, payload):
        pass


def make_engine(providers=None, world_extra=None):
    cfg = {
        "world": {"width": 8, "height": 6, "seed": 5, **(world_extra or {})},
        "providers": providers or {},
        "agents": [
            {"name": "甲", "emoji": "🤖", "provider": "x", "model": "m"},
            {"name": "乙", "emoji": "🤖", "provider": "x", "model": "m"},
        ],
    }
    return Engine(cfg, FakeHub())


async def run_turn_and_wait(eng):
    await eng.run_turn()
    tasks = [t for t in (eng._commentary_task, eng._reflection_task) if t]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def run(eng):
    asyncio.run(run_turn_and_wait(eng))


def test_reflection_writes_to_notes(monkeypatch):
    async def fake_chat(client, model, messages, **kwargs):
        return "先稳住，别当出头鸟", None

    monkeypatch.setattr(engine_mod, "llm_chat", fake_chat)
    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    eng = make_engine(
        providers={"x": {"name": "X", "base_url": "https://x", "api_key": "sk-x", "models": ["m"]}},
        world_extra={"reflect_interval": 2},
    )
    # turn=1 不触发
    run(eng)
    assert not any(n.startswith("[反思]") for a in eng.agents for n in a.notes)

    # turn=2 触发反思
    run(eng)
    for a in eng.agents:
        assert any(n == "[反思] 先稳住，别当出头鸟" for n in a.notes)
    assert any(h["kind"] == "think" and "反思" in h["text"] for h in eng.history)


def test_reflection_skipped_in_demo_mode(monkeypatch):
    async def fake_chat(client, model, messages, **kwargs):
        return "不该出现", None

    monkeypatch.setattr(engine_mod, "llm_chat", fake_chat)
    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    eng = make_engine(providers={}, world_extra={"reflect_interval": 1})
    run(eng)
    assert not any(h["kind"] == "think" and "反思" in h["text"] for h in eng.history)


def test_reflection_failure_silent(monkeypatch):
    async def fail_chat(client, model, messages, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine_mod, "llm_chat", fail_chat)
    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    eng = make_engine(
        providers={"x": {"name": "X", "base_url": "https://x", "api_key": "sk-x", "models": ["m"]}},
        world_extra={"reflect_interval": 1},
    )
    run(eng)
    # 反思失败不抛异常、不影响代理状态
    assert all(len(a.notes) == 0 for a in eng.agents)


def test_reflection_no_pile(monkeypatch):
    calls = [0]
    release = asyncio.Event()

    async def slow_chat(client, model, messages, **kwargs):
        calls[0] += 1
        await release.wait()
        return "慢反思", None

    monkeypatch.setattr(engine_mod, "llm_chat", slow_chat)
    monkeypatch.setattr(engine_mod, "llm_act", fake_llm_act)
    eng = make_engine(
        providers={"x": {"name": "X", "base_url": "https://x", "api_key": "sk-x", "models": ["m"]}},
        world_extra={"reflect_interval": 1},
    )

    async def main():
        await eng.run_turn()
        task1 = eng._reflection_task
        assert task1 is not None
        await eng.run_turn()
        assert eng._reflection_task is task1
        release.set()
        await task1

    asyncio.run(main())
    # 反思按代理调用，2 名代理各调用 1 次
    assert calls[0] == 2
