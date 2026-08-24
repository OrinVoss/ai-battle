"""终局判定：回合上限、评分排序、称号、stats 累计。"""

import asyncio
import json
import os

import pytest

import engine as engine_mod
from engine import Engine


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


# ---------- 回合上限 ----------

def test_max_turns_forces_game_over(tmp_path, monkeypatch):
    eng = make_engine(world_extra={"max_turns": 2})
    eng.log_dir = str(tmp_path)
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))
    eng.reset()
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    asyncio.run(eng.run_turn())
    assert eng.turn == 1
    assert eng.winner is None
    assert eng.game_over is None
    asyncio.run(eng.run_turn())
    assert eng.turn == 2
    assert eng.winner is not None
    assert eng.game_over["reason"] == "max_turns"
    assert len(eng.game_over["rankings"]) == 2
    assert "生存冠军" in eng.game_over["titles"]


def test_max_turns_zero_means_unlimited(tmp_path, monkeypatch):
    eng = make_engine(world_extra={"max_turns": 0})
    eng.log_dir = str(tmp_path)
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))
    eng.reset()
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    for _ in range(5):
        asyncio.run(eng.run_turn())
    assert eng.winner is None
    assert eng.game_over is None


# ---------- 评分排序 ----------

def test_ranking_sort_alive_kills_resources():
    eng = make_engine(agents=[
        {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "丙", "emoji": "🤖", "provider": "none", "model": "m"},
    ])
    eng.reset()
    a, b, c = eng.agents
    a.alive = False
    a.kills = 5
    a.items = {"food": 10, "ore": 10}
    b.alive = True
    b.kills = 1
    b.items = {"food": 1, "ore": 0}
    c.alive = True
    c.kills = 2
    c.items = {"food": 0, "ore": 0}
    rankings = eng._compute_rankings()
    names = [r["name"] for r in rankings]
    # 存活 > 击杀 > 资源
    assert names == ["丙", "乙", "甲"]


def test_ranking_tie_break_by_relation_total():
    eng = make_engine(agents=[
        {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
    ])
    eng.reset()
    a, b = eng.agents
    a.alive = True
    a.kills = 1
    a.items = {"food": 0, "ore": 0}
    a.relation = {"乙": 5}
    b.alive = True
    b.kills = 1
    b.items = {"food": 0, "ore": 0}
    b.relation = {"甲": 0}
    rankings = eng._compute_rankings()
    assert rankings[0]["name"] == "甲"
    assert rankings[1]["name"] == "乙"


# ---------- 称号 ----------

def test_titles_basic():
    eng = make_engine(agents=[
        {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "丙", "emoji": "🤖", "provider": "none", "model": "m"},
    ])
    eng.reset()
    a, b, c = eng.agents
    # 甲存活、击杀最多、资源最多、正关系最高
    a.alive = True
    a.kills = 3
    a.items = {"food": 5, "ore": 2}
    a.weapon = True
    a.relation = {"乙": 5, "丙": 3}
    b.alive = False
    b.kills = 0
    b.items = {"food": 0, "ore": 0}
    b.relation = {"甲": -2}
    c.alive = False
    c.kills = 0
    c.items = {"food": 1, "ore": 1}
    c.relation = {"甲": 1}
    titles = eng._compute_titles()
    assert titles["生存冠军"] == "甲"
    assert titles["霸主"] == "甲"
    assert titles["富翁"] == "甲"
    assert titles["外交家"] == "甲"


def test_no_conqueror_when_zero_kills():
    eng = make_engine()
    eng.reset()
    for a in eng.agents:
        a.kills = 0
    titles = eng._compute_titles()
    assert "霸主" not in titles


def test_diplomat_requires_positive_relation():
    eng = make_engine(agents=[
        {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
    ])
    eng.reset()
    for a in eng.agents:
        a.relation = {o.name: -1 for o in eng.agents if o is not a}
    titles = eng._compute_titles()
    assert "外交家" not in titles


def test_richest_falls_back_to_all_when_no_alive():
    eng = make_engine(agents=[
        {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
        {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
    ])
    eng.reset()
    a, b = eng.agents
    a.alive = False
    a.items = {"food": 1, "ore": 0}
    b.alive = False
    b.items = {"food": 0, "ore": 1}
    titles = eng._compute_titles()
    # 乙资源分 = 0 + 1*2 + 0 = 2 > 甲 1
    assert titles["富翁"] == "乙"


# ---------- stats 累计 ----------

def test_stats_accumulates_titles(tmp_path, monkeypatch):
    eng = make_engine(world_extra={"max_turns": 1})
    eng.log_dir = str(tmp_path)
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))
    eng.reset()
    # 让甲拿到所有称号
    a, b = eng.agents
    a.kills = 1
    a.items = {"food": 5, "ore": 5}
    a.weapon = True
    a.relation = {"乙": 5}
    asyncio.run(eng.run_turn())
    assert eng.winner == "甲"
    with open(tmp_path / "stats.json", encoding="utf-8") as f:
        data = json.load(f)
    key_a = "甲|m"
    key_b = "乙|m"
    assert data[key_a]["titles"]["生存冠军"] == 1
    assert data[key_a]["titles"]["霸主"] == 1
    assert data[key_a]["titles"]["富翁"] == 1
    assert data[key_a]["titles"]["外交家"] == 1
    assert data[key_b]["titles"] == {}


# ---------- 正常歼灭结局 ----------

def test_normal_elimination_unchanged(tmp_path, monkeypatch):
    eng = make_engine()
    eng.log_dir = str(tmp_path)
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))
    eng.reset()
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    eng.agents[1].alive = False
    asyncio.run(eng.run_turn())
    assert eng.winner == "甲"
    assert eng.game_over["reason"] == "elimination"
    assert eng.game_over["titles"]["生存冠军"] == "甲"
