"""临时检查：服务器状态与历史日志分类。"""

import asyncio
import json
import os
import sys

import websockets


def _get_port():
    """端口优先级：命令行参数 > 环境变量 PORT > 默认 8080。"""
    if len(sys.argv) > 1:
        try:
            return int(sys.argv[1])
        except ValueError:
            print(f"[check_status] 无效端口参数：{sys.argv[1]}", file=sys.stderr)
            sys.exit(1)
    try:
        return int(os.environ.get("PORT", "8080"))
    except ValueError:
        print(f"[check_status] 环境变量 PORT 无效：{os.environ.get('PORT')}", file=sys.stderr)
        sys.exit(1)


async def main():
    port = _get_port()
    uri = f"ws://127.0.0.1:{port}/ws"
    try:
        async with websockets.connect(uri, max_size=5 * 1024 * 1024) as ws:
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
    except (OSError, websockets.exceptions.WebSocketException) as e:
        print(f"[check_status] 无法连接到 {uri}：{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


asyncio.run(main())
