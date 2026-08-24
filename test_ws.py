"""临时测试：连接 WebSocket，启动模拟，收集若干回合日志后退出。"""

import asyncio
import json

import websockets


async def main():
    uri = "ws://127.0.0.1:8080/ws"
    async with websockets.connect(uri, max_size=5 * 1024 * 1024) as ws:
        first = json.loads(await ws.recv())
        w = first.get("world", {})
        print(f"[连接] type={first.get('type')} 回合={first.get('turn')} "
              f"地图={w.get('w')}x{w.get('h')} 选手={len(first.get('agents', []))} demo={first.get('demo')}")
        for a in first.get("agents", []):
            print(f"  - {a['name']} {a['emoji']} {a['provider']}/{a['model']} @ {a['pos']}")

        status = json.loads(await ws.recv())
        print(f"[连接] status running={status.get('running')}")

        # 补发的历史日志
        replay = 0
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.5))
            except asyncio.TimeoutError:
                break
            if m.get("type") == "log":
                replay += 1
        print(f"[连接] 补发历史日志 {replay} 条")

        await ws.send(json.dumps({"type": "cmd", "action": "start"}))
        print("[命令] start 已发送，开始收集 6 个回合快照…")

        logs = 0
        snapshots = 0
        last = None
        for _ in range(200):
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            except asyncio.TimeoutError:
                print("[超时] 10 秒无消息，停止")
                break
            t = m.get("type")
            if t == "log":
                logs += 1
                last = m.get("text", "")
                if "回合" in last or "战斗" in last or "攻击" in last or "交易" in last or "死亡" in last or "喊" in last or "说" in last:
                    print(f"  [T{m.get('turn')}][{m.get('kind')}] {m.get('text')[:70]}")
            elif t == "snapshot":
                snapshots += 1
                alive = [a["name"] for a in m.get("agents", []) if a["alive"]]
                if snapshots <= 3 or snapshots % 2 == 0:
                    print(f"  [快照 {snapshots}] 回合={m.get('turn')} 存活={len(alive)}/{len(m.get('agents', []))} 运行={m.get('running')}")
                if snapshots >= 6:
                    break
            elif t == "status":
                print(f"[status] running={m.get('running')} winner={m.get('winner')}")

        print(f"[结果] 日志 {logs} 条 / 快照 {snapshots} 个 / 最后日志: {last}")
        print("[完成] 测试通过" if snapshots >= 3 and logs > 0 else "[失败] 数据不足")


asyncio.run(main())
