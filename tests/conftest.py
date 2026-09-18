import os
import sys

import pytest

# 让测试能 import 项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine as engine_mod


@pytest.fixture(autouse=True)
def isolate_engine_files(tmp_path, monkeypatch):
    """把引擎的落盘目录整体改指临时目录。

    Engine 一构造就 reset()，会往 logs/ 与 replays/ 各写一个文件并触发
    "保留最近 50 个" 的轮转；测试若用真实目录，跑一次 pytest 就会把真实对局
    记录轮转掉（stats.json 同理会写进假选手）。
    """
    monkeypatch.setattr(engine_mod, "LOG_DIR", str(tmp_path / "_engine_files" / "logs"))
    monkeypatch.setattr(engine_mod, "REPLAY_DIR", str(tmp_path / "_engine_files" / "replays"))
    monkeypatch.setattr(engine_mod, "STATS_FILE", str(tmp_path / "_engine_files" / "stats.json"))
