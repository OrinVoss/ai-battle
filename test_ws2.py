"""临时测试2：让演示模式跑 ~40 回合，统计战斗/交易/死亡等事件，验证戏能演起来。"""

import asyncio
import json
from collections import Counter

import websockets


async def main():
    async with websockets.connect("ws://127.0.0.1:8080/ws", max_size=5 * 1024 * 1024) as ws:
        await ws.recv()  # snapshot
        await ws.recv()  # status
        # 消费补发日志
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
            except asyncio.TimeoutError:
                break
            if m.get("type") != "log":
                break

        await ws.send(json.dumps({"type": "cmd", "action": "start"}))
        kinds = Counter()
        drama = []
        last_snap = None
        for _ in range(600):
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            except asyncio.TimeoutError:
                break
            t = m.get("type")
            if t == "log":
                kinds[m.get("kind")] += 1
                drama.append(f"[T{m.get('turn')}][{m.get('kind')}] {m.get('text')}")
                if len(drama) > 300:
                    drama.pop(0)
            elif t == "snapshot":
                last_snap = m
                alive = [a["name"] for a in m["agents"] if a["alive"]]
                if m.get("winner"):
                    print(f"[终局] 回合={m.get('turn')} 胜者={m.get('winner')} 存活={alive}")
                    break
                if m.get("turn", 0) >= 40:
                    break

        print("[统计]", dict(kinds))
        if last_snap:
            alive = [a["name"] for a in last_snap["agents"] if a["alive"]]
            print(f"[终态] 回合={last_snap.get('turn')} 存活={len(alive)}/{len(last_snap['agents'])}: {alive}")
            for a in last_snap["agents"]:
                if not a["alive"]:
                    print(f"  💀 {a['name']} 已死亡")
        print("\n[最近发生的戏]")
        for line in drama[-45:]:
            print(" ", line)


asyncio.run(main())
