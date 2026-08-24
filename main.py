"""AI 大战 · 多模型生存沙盒 —— 服务器入口（FastAPI + WebSocket + 静态页面）。"""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from engine import REPLAY_DIR, STATS_FILE, Engine

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)


class Hub:
    """向所有已连接的前端广播；同时把每条消息同步落盘到回放文件。"""

    def __init__(self):
        self.conns = set()
        self.recorder = None  # engine 每局挂一个写文件的回调

    async def send(self, type_, payload):
        data = json.dumps({"type": type_, **payload}, ensure_ascii=False)
        if self.recorder:
            try:
                self.recorder(data)
            except Exception:
                pass
        if not self.conns:
            return
        # 并行发送，失败的连接剔除
        targets = list(self.conns)
        results = await asyncio.gather(
            *(ws.send_text(data) for ws in targets), return_exceptions=True
        )
        for ws, r in zip(targets, results):
            if isinstance(r, Exception):
                self.conns.discard(ws)


hub = Hub()
engine = Engine(CONFIG, hub)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(engine.loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="AI 大战 · 多模型生存沙盒", lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.conns.add(ws)
    # 新连接先补发全量状态（full=True 保证带完整地图）
    await ws.send_text(json.dumps({"type": "snapshot", **engine.snapshot(full=True)}, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "status", "running": engine.running, "winner": engine.winner}, ensure_ascii=False))
    for entry in engine.history:
        await ws.send_text(json.dumps({"type": "log", **entry}, ensure_ascii=False))
    try:
        while True:
            msg = await ws.receive_json()
            t = msg.get("type")
            if t == "cmd":
                act = msg.get("action")
                if act == "start":
                    if engine.can_play():
                        engine.running = True
                        engine.step_flag = False
                        await hub.send("status", {"running": True, "winner": None})
                    else:  # 已分出胜负，拒绝重复结算
                        await hub.send("status", {"running": False, "winner": engine.winner})
                elif act == "pause":
                    engine.running = False
                    await hub.send("status", {"running": False, "winner": engine.winner})
                elif act == "step":
                    if engine.can_play():
                        engine.step_flag = True
                        engine.running = True
                        await hub.send("status", {"running": True, "winner": None})
                    else:
                        await hub.send("status", {"running": False, "winner": engine.winner})
                elif act == "reset":
                    engine.running = False  # 先停表再重置，避免旧回合用新世界结算
                    engine.reset()
                    await hub.send("snapshot", engine.snapshot(full=True))
                    engine._last_world_version = engine.world.version
                    await hub.send("status", {"running": False, "winner": None})
                elif act == "speed":
                    try:
                        engine.speed = float(msg.get("value", 0.6))
                    except (TypeError, ValueError):
                        pass
            elif t == "setup" or t == "setup_save":
                # 开局设置：应用（+reset）；setup_save 先写文件成功后再应用，失败则整体不生效
                try:
                    if t == "setup_save":
                        err = engine.save_setup(msg.get("agents"), msg.get("world"))
                        if not err:
                            err = engine.apply_setup(msg.get("agents"), msg.get("world"))
                    else:
                        err = engine.apply_setup(msg.get("agents"), msg.get("world"))
                except Exception as e:
                    err = f"设置应用失败：{e}"
                await ws.send_text(json.dumps(
                    {"type": "setup_result", "ok": not err, "saved": t == "setup_save" and not err,
                     "error": err}, ensure_ascii=False))
                if not err:
                    await hub.send("snapshot", engine.snapshot(full=True))
                    engine._last_world_version = engine.world.version
                    await hub.send("status", {"running": False, "winner": None})
            elif t == "god_msg":
                try:
                    err = engine.god_message(msg.get("targets"), str(msg.get("text", "")), bool(msg.get("sow")))
                except Exception as e:
                    err = f"上帝传话失败：{e}"
                if err:
                    await ws.send_text(json.dumps({"type": "setup_result", "ok": False, "error": err}, ensure_ascii=False))
            elif t == "god":
                text = (msg.get("text") or "").strip()
                if text:
                    engine.god_say(text[:200])
    except WebSocketDisconnect:
        hub.conns.discard(ws)
    except Exception:
        hub.conns.discard(ws)


@app.get("/api/export")
def api_export():
    """一键导出当前这局的完整会话 JSON（meta + 选手终态 + 全量日志）。"""
    return JSONResponse(
        engine.export_data(),
        headers={"Content-Disposition": 'attachment; filename="match_export.json"'},
    )


@app.get("/api/setup")
def api_setup():
    """设置面板的编辑数据：完整选手配置 + providers 展示信息（不含 api_key）+ 难度参数。"""
    return {
        "agents": CONFIG["agents"],
        "providers": {
            k: {"name": v.get("name", k), "models": list(v.get("models", []))}
            for k, v in CONFIG.get("providers", {}).items()
        },
        "world": {k: engine.difficulty(k) for k in Engine.DIFFICULTY}
        | {"max_turns": engine.max_turns},
    }


@app.get("/api/stats")
def api_stats():
    """战绩排行榜数据（跨局累计，重置不影响）。"""
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


@app.get("/api/replays")
def api_replays():
    """回放文件列表（文件名/大小/修改时间，新的在前）。"""
    if not os.path.isdir(REPLAY_DIR):
        return []
    out = []
    for name in os.listdir(REPLAY_DIR):
        if not name.endswith(".jsonl"):
            continue
        try:
            st = os.stat(os.path.join(REPLAY_DIR, name))
        except OSError:
            continue  # 文件刚被删掉等情况，跳过即可
        out.append({"name": name, "size": st.st_size, "mtime": st.st_mtime})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


@app.get("/api/replays/{name}")
def api_replay(name: str):
    """返回整个 JSONL 回放文本；校验文件名防目录穿越。"""
    base = os.path.realpath(REPLAY_DIR)
    path = os.path.realpath(os.path.join(base, name))
    if not name.endswith(".jsonl") or os.path.dirname(path) != base or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="回放不存在")
    with open(path, encoding="utf-8") as f:
        return PlainTextResponse(f.read())


app.mount("/", StaticFiles(directory=os.path.join(BASE, "web"), html=True), name="web")


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """前端文件禁用缓存，改代码刷新页面即可生效，避免浏览器缓存旧版。"""
    response = await call_next(request)
    if request.url.path in ("/", "/index.html", "/app.js", "/style.css"):
        response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="127.0.0.1", port=port)
