"""临时测试3：耐心等待真实模型的回合推进，检查决策是否正常。"""

import asyncio
import json

import websockets


async def main():
    async with websockets.connect("ws://127.0.0.1:8080/ws", max_size=5 * 1024 * 1024) as ws:
        snap = json.loads(await ws.recv())
        print(f"[连接] 回合={snap.get('turn')} running={snap.get('running')} demo={snap.get('demo')}")
        await ws.recv()  # status

        # 先看历史日志里有没有失败
        fails = 0
        lines = []
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.2))
            except asyncio.TimeoutError:
                break
            if m.get("type") == "log":
                lines.append(f"[T{m.get('turn')}][{m.get('kind')}] {m.get('text')}")
                if "决策失败" in m.get("text", "") or "出错" in m.get("text", ""):
                    fails += 1
        print(f"[历史日志] {len(lines)} 条，其中失败 {fails} 条")
        for l in lines[-12:]:
            print(" ", l)

        if snap.get("running"):
            print("[游戏已在运行，开始等待新回合…]")
        else:
            await ws.send(json.dumps({"type": "cmd", "action": "start"}))
            print("[命令] start 已发送")

        # 等待最多 8 个快照（每回合完成后推一次）
        seen = 0
        for _ in range(400):
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            except asyncio.TimeoutError:
                print("[超时] 25 秒无消息")
                break
            t = m.get("type")
            if t == "log":
                if "决策失败" in m.get("text", "") or "出错" in m.get("text", ""):
                    print("  ⚠️", m.get("text")[:120])
                else:
                    print(f"  [T{m.get('turn')}][{m.get('kind')}] {m.get('text')[:80]}")
            elif t == "snapshot":
                seen += 1
                alive = [a["name"] for a in m["agents"] if a["alive"]]
                print(f"  [快照 {seen}] 回合={m.get('turn')} 存活={len(alive)}/{len(m['agents'])}")
                if seen >= 6:
                    break
        print(f"[结果] 收到 {seen} 个快照")
        if seen >= 3:
            print("[完成] 真实模型回合推进正常")
        else:
            print("[注意] 快照不足，模型可能响应慢或调用失败")


asyncio.run(main())
