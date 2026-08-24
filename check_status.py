"""临时检查：服务器状态与历史日志分类。"""

import asyncio
import json

import websockets


async def main():
    async with websockets.connect("ws://127.0.0.1:8080/ws", max_size=5 * 1024 * 1024) as ws:
        s = json.loads(await ws.recv())
        print(f"回合={s.get('turn')} running={s.get('running')} demo={s.get('demo')} "
              f"地图={s['world']['w']}x{s['world']['h']}")
        await ws.recv()
        kinds = {}
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
            except asyncio.TimeoutError:
                break
            if m.get("type") == "log":
                kinds[m.get("kind")] = kinds.get(m.get("kind"), 0) + 1
        print("历史日志分类:", kinds)


asyncio.run(main())
