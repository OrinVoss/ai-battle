"""世界：地图生成、地形、资源矿脉。"""

import random

BLOCKED = {"~", "M"}  # 水、山不可通行
TILE_CN = {".": "平地", "F": "森林", "~": "水域", "M": "山地", "f": "食物矿脉", "o": "矿石矿脉"}


class World:
    def __init__(self, cfg):
        w = cfg["world"]["width"]
        h = cfg["world"]["height"]
        self.w, self.h = w, h
        self.rng = random.Random(cfg["world"].get("seed"))
        self.grid = [["." for _ in range(w)] for _ in range(h)]
        self.deposits = {}        # (x,y) -> 剩余量
        self.depleted = {}        # (x,y) -> 被采空的矿脉类型（"f"/"o"），供 regen 重新长出
        self.agents = []          # 由 engine 填充
        self.pending_trades = []
        self.version = 0          # 地形/矿脉任何变化 +1，用于增量推送
        self.night = False        # 夜晚标记（engine 维护）
        self.harvest = False      # 丰收季标记（engine 维护）
        # 难度参数（可在设置面板调节，挂 config["world"] 下；范围与 engine.DIFFICULTY 一致）
        def _diff(key, dft, lo, hi):
            try:
                return max(lo, min(hi, float(cfg["world"].get(key, dft))))
            except (TypeError, ValueError):
                return dft
        self.damage_mult = _diff("damage_mult", 1.0, 0.5, 2.0)  # 攻击伤害倍率
        self.gather_mult = _diff("gather_mult", 1.0, 0.5, 2.0)  # 采集成功率倍率
        self.energy_drain = _diff("energy_drain", 2, 0, 5)      # 能量每回合消耗（感知文本用）
        self.hp_drain = _diff("hp_drain", 3, 0, 10)             # 能量归零后生命损耗（感知文本用）
        self._generate()

    def _generate(self):
        cells = self.w * self.h
        for _ in range(int(cells * 0.05)):
            self._blob("~", 2, 4)
        for _ in range(int(cells * 0.05)):
            self._blob("M", 1, 3)
        for _ in range(int(cells * 0.12)):
            self._blob("F", 2, 5)
        for _ in range(int(cells * 0.030)):
            x, y = self._free_spot()
            self.grid[y][x] = "f"
            self.deposits[(x, y)] = self.rng.randint(3, 6)
        for _ in range(max(2, int(cells * 0.015))):
            x, y = self._free_spot()
            self.grid[y][x] = "o"
            self.deposits[(x, y)] = self.rng.randint(3, 6)

    def _blob(self, ch, minc, maxc):
        x, y = self._free_spot(any_tile=True)
        for _ in range(self.rng.randint(minc, maxc)):
            if self.rng.random() < 0.6:
                x += self.rng.choice([-1, 1])
            else:
                y += self.rng.choice([-1, 1])
            x = max(0, min(self.w - 1, x))
            y = max(0, min(self.h - 1, y))
            if self.grid[y][x] == ".":
                self.grid[y][x] = ch

    def _free_spot(self, any_tile=False):
        for _ in range(1000):  # 随机尝试，避免地图将满时死循环
            x = self.rng.randrange(self.w)
            y = self.rng.randrange(self.h)
            if any_tile or self.grid[y][x] == ".":
                return x, y
        for y in range(self.h):  # 超限后顺序扫描兜底
            for x in range(self.w):
                if any_tile or self.grid[y][x] == ".":
                    return x, y
        raise RuntimeError("地图上没有可用的空地")

    def in_bounds(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def tile(self, x, y):
        return self.grid[y][x] if self.in_bounds(x, y) else "M"

    def is_blocked(self, x, y):
        return (not self.in_bounds(x, y)) or self.tile(x, y) in BLOCKED

    def consume(self, x, y):
        """采集矿脉一次；采空后记入 depleted，等待 regen 重新长出。"""
        if (x, y) in self.deposits:
            self.deposits[(x, y)] -= 1
            self.version += 1
            if self.deposits[(x, y)] <= 0:
                del self.deposits[(x, y)]
                self.depleted[(x, y)] = self.grid[y][x]
                self.grid[y][x] = "."

    def regen(self):
        """每回合资源再生：现存矿脉 15% 概率 +1（上限 6）；被采空的格子 2% 概率重新长出同类矿脉（量 2-4）。"""
        changed = False
        for pos in list(self.deposits):
            if self.deposits[pos] < 6 and self.rng.random() < 0.15:
                self.deposits[pos] += 1
                changed = True
        for pos, kind in list(self.depleted.items()):
            if self.rng.random() < 0.02:
                x, y = pos
                self.grid[y][x] = kind
                self.deposits[pos] = self.rng.randint(2, 4)
                del self.depleted[pos]
                changed = True
        if changed:
            self.version += 1

    def spawn_points(self, n):
        pts = []
        while len(pts) < n:
            x, y = self._free_spot()
            if (x, y) not in pts:
                pts.append((x, y))
        return pts

    def dist(self, a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def by_name(self, name):
        for a in self.agents:
            if a.name == name:
                return a
        return None

    def nearest_resource(self, pos, kinds=("f", "o")):
        best, bd = None, 10**9
        for y in range(self.h):
            for x in range(self.w):
                if self.grid[y][x] in kinds:
                    d = self.dist(pos, (x, y))
                    if d < bd:
                        bd, best = d, (x, y)
        return best

    def nearest_agent(self, agent):
        best, bd = None, 10**9
        for o in self.agents:
            if o is agent or not o.alive:
                continue
            d = self.dist(agent.pos, o.pos)
            if d < bd:
                bd, best = d, o
        return best

    def dir_toward(self, frm, to):
        dx, dy = to[0] - frm[0], to[1] - frm[1]
        if dx != 0 and dy != 0:
            if self.rng.random() < 0.5:
                dx, dy = dx, 0
            else:
                dx, dy = 0, dy
        if dx > 0:
            return "right"
        if dx < 0:
            return "left"
        if dy > 0:
            return "down"
        if dy < 0:
            return "up"
        return None
