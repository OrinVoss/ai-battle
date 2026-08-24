"""世界生成 / 资源再生 / 采空记录的测试（固定 seed，确定性）。"""

from world import World


def make_world(w=20, h=16, seed=42):
    return World({"world": {"width": w, "height": h, "seed": seed}})


def flat_world(w=8, h=8, seed=7):
    world = make_world(w, h, seed)
    world.grid = [["." for _ in range(w)] for _ in range(h)]
    world.deposits = {}
    world.depleted = {}
    return world


# ---------- 地图生成 ----------

def test_generation():
    w = make_world()
    assert w.w == 20 and w.h == 16
    assert len(w.grid) == 16 and all(len(row) == 20 for row in w.grid)
    # 每个矿脉格子都有剩余量记录，且相互一致
    kinds = set()
    for y in range(w.h):
        for x in range(w.w):
            t = w.grid[y][x]
            if t in ("f", "o"):
                kinds.add(t)
                assert (x, y) in w.deposits and w.deposits[(x, y)] > 0
    for (x, y) in w.deposits:
        assert w.grid[y][x] in ("f", "o")
    assert kinds  # 至少生成过矿脉
    # 出生点不重复且在界内
    pts = w.spawn_points(6)
    assert len(set(pts)) == 6 and all(w.in_bounds(x, y) for x, y in pts)


# ---------- consume 采空 ----------

def test_consume_depletes():
    w = flat_world()
    w.grid[3][3] = "o"
    w.deposits[(3, 3)] = 2
    v0 = w.version
    w.consume(3, 3)
    assert w.deposits[(3, 3)] == 1 and w.version == v0 + 1
    w.consume(3, 3)
    assert (3, 3) not in w.deposits      # 采空
    assert w.grid[3][3] == "."           # 变回平地
    assert w.depleted[(3, 3)] == "o"     # 记录采空类型，供 regen 再长
    assert w.version > v0 + 1


# ---------- regen ----------

def test_regen_deposit_grows_with_cap():
    w = flat_world()
    w.grid[1][1] = "f"
    w.deposits[(1, 1)] = 5
    for _ in range(100):  # 15% 概率 +1，100 回合必定长满且不超过 6
        w.regen()
        assert w.deposits[(1, 1)] <= 6
    assert w.deposits[(1, 1)] == 6


def test_regen_depleted_regrows():
    w = flat_world()
    w.depleted[(3, 3)] = "o"
    w.grid[3][3] = "."
    regrown = False
    for _ in range(500):  # 2% 概率重新长出
        w.regen()
        if (3, 3) in w.deposits:
            regrown = True
            break
    assert regrown
    assert w.grid[3][3] == "o"                  # 长出同类型矿脉
    assert 2 <= w.deposits[(3, 3)] <= 6         # 量 2-4 起步（可能被 regen 又加了）
    assert (3, 3) not in w.depleted             # 不再算采空格
