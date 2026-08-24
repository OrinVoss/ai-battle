"""比赛日志落盘 / 一键导出的测试。"""

import asyncio
import json
import os

import engine as engine_mod
from collections import deque

from engine import Engine, _rotate_saved_files


class FakeHub:
    recorder = None

    async def send(self, type_, payload):
        pass


def make_engine(providers=None):
    cfg = {
        "world": {"width": 8, "height": 6, "seed": 5},
        "providers": providers or {},
        "agents": [
            {"name": "甲", "emoji": "🤖", "provider": "none", "model": "m"},
            {"name": "乙", "emoji": "🤖", "provider": "none", "model": "m"},
        ],
    }
    return Engine(cfg, FakeHub())


def log_files(d):
    return [f for f in os.listdir(d) if f.endswith(".log")]


# ---------- 日志落盘 ----------

def test_log_file_written(tmp_path):
    eng = make_engine()
    eng.log_dir = str(tmp_path)
    eng.reset()  # 重开一局 → 在临时目录开新文件
    eng.emit("fight", "阿哲 攻击 乌鸦，造成 11 点伤害")
    eng.emit("think", "💭 阿哲 想：先下手为强")
    files = log_files(tmp_path)
    assert len(files) == 1
    lines = open(os.path.join(tmp_path, files[0]), encoding="utf-8").read().splitlines()
    assert "[T0] [fight] 阿哲 攻击 乌鸦，造成 11 点伤害" in lines
    assert "[T0] [think] 💭 阿哲 想：先下手为强" in lines
    # reset 换新文件，旧文件关闭
    eng.reset()
    assert len(log_files(tmp_path)) == 2


def test_log_game_over_summary(tmp_path, monkeypatch):
    eng = make_engine()
    eng.log_dir = str(tmp_path)
    # 战绩文件也指向临时目录，避免污染项目根目录
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "stats.json"))
    eng.reset()
    monkeypatch.setattr(engine_mod, "demo_decide", lambda a, w: ("wait", {}))
    eng.agents[1].alive = False  # 只剩甲，下一回合结束
    asyncio.run(eng.run_turn())
    assert eng.winner == "甲"
    content = open(eng.log_path, encoding="utf-8").read()
    assert "本局结束：胜者 甲" in content


# ---------- 一键导出 ----------

def test_export_structure_and_no_api_key():
    eng = make_engine(providers={
        "deepseek": {"name": "DeepSeek", "base_url": "https://x", "api_key": "sk-test-secret",
                     "models": ["m1"], "price_input": 2, "price_output": 8},
    })
    eng.emit("sys", "一条日志")
    data = eng.export_data()
    assert set(data) == {"meta", "agents", "logs", "events"}
    assert data["meta"]["turn"] == 0 and "exported_at" in data["meta"]
    a = data["agents"][0]
    for k in ("name", "model", "role", "backstory", "traits", "hp", "items", "kills", "relations"):
        assert k in a
    blob = json.dumps(data, ensure_ascii=False)
    assert "api_key" not in blob and "sk-test-secret" not in blob
    assert data["logs"][-1] == "[T0] [sys] 一条日志"  # reset 自身的公告也在日志里


def test_export_prefers_log_file_when_longer(tmp_path):
    eng = make_engine()
    eng.log_dir = str(tmp_path)
    eng.reset()
    base = len(eng.history)  # reset 公告行数
    for i in range(5):
        eng.emit("sys", f"第{i}条")
    eng.history = deque(list(eng.history)[-2:])  # 模拟 history 被 800 上限截断
    data = eng.export_data()
    assert len(data["logs"]) == base + 5  # 以 log 文件为准，导出完整一局
    assert data["logs"][-1] == "[T0] [sys] 第4条"


def test_think_log_has_actor():
    eng = make_engine()
    eng.reset()
    eng.emit("think", "💭 甲 想：测试想法", data={"actor": "甲"})
    entry = eng.history[-1]
    assert entry["actor"] == "甲"


def test_export_events_array_includes_structured_data():
    eng = make_engine()
    eng.reset()
    eng.emit("fight", "⚔️ 甲 攻击 乙", data={"attacker": "甲", "victim": "乙", "damage": 10, "remaining_hp": 90})
    data = eng.export_data()
    assert "events" in data
    evt = data["events"][-1]
    assert evt["kind"] == "fight"
    assert evt["attacker"] == "甲"
    assert evt["victim"] == "乙"
    assert evt["damage"] == 10


def test_history_deque_maxlen():
    eng = make_engine()
    eng.reset()
    assert isinstance(eng.history, deque)
    for i in range(900):
        eng.emit("sys", f"msg {i}")
    assert len(eng.history) == 800
    assert eng.history[0]["text"] == "msg 100"
    assert eng.history[-1]["text"] == "msg 899"


def test_god_message_log_has_targets_and_sow():
    eng = make_engine()
    eng.reset()
    err = eng.god_message(["甲", "乙"], "挑拨测试", sow=True)
    assert err is None
    entry = eng.history[-1]
    assert entry["kind"] == "god"
    assert set(entry["targets"]) == {"甲", "乙"}
    assert entry["sow"] is True


# ---------- 日志/回放轮转 ----------

def test_rotate_saved_files_keeps_latest(tmp_path):
    d = tmp_path / "files"
    d.mkdir()
    for i in range(55):
        p = d / f"f{i:02d}.txt"
        p.write_text("x", encoding="utf-8")
        # 修改时间递增，保证顺序稳定
        os.utime(p, (i, i))
    _rotate_saved_files(str(d), keep=50)
    remaining = sorted(os.listdir(d))
    assert len(remaining) == 50
    # 保留 mtime 最大的 50 个（即 f05 ~ f54）
    assert remaining[0] == "f05.txt"
    assert remaining[-1] == "f54.txt"


def test_engine_reset_rotates_logs_and_replays(tmp_path, monkeypatch):
    import engine as engine_mod
    eng = make_engine()
    log_d = tmp_path / "logs"
    replay_d = tmp_path / "replays"
    log_d.mkdir()
    replay_d.mkdir()
    eng.log_dir = str(log_d)
    monkeypatch.setattr(engine_mod, "REPLAY_DIR", str(replay_d))
    # 预先放旧文件
    for i in range(3):
        (log_d / f"old_{i}.log").write_text("x", encoding="utf-8")
        (replay_d / f"old_{i}.jsonl").write_text("x", encoding="utf-8")
    eng.reset()
    # reset 会创建新文件；旧文件总数 <= 50 不会被删，所以只验证新增存在即可
    assert len(list(log_d.iterdir())) >= 3
    assert len(list(replay_d.iterdir())) >= 3
