"""Which 256-byte blocks of main RAM does the game ever leave non-zero?
Boots a disc to the field (card slot, optional walk to the world map), then
mashes random inputs (menus, dialogs, doors, battles) and samples RAM.  A
block counts as used once any sample finds a non-zero byte in it.  The
masks of several runs are OR-ed by debug/ramfree_sum.py.
    python debug/ramfree.py <cue> <card> <slot 0-2> <frames> <seed> [map]"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from emu import Game

cue, card, slot, N, seed = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
to_map = len(sys.argv) > 6 and sys.argv[6] == "map"
rng = random.Random(seed)
LO, HI = 0x80000000, 0x80200000
g = Game(cue, card)
used = np.zeros((HI - LO) // 256, bool)
modes = set()


def scan():
    a = np.frombuffer(g.ram(LO, HI - LO), np.uint8).reshape(-1, 256)
    used[:] |= a.any(1)
    modes.add(g.u32(0x800DB4E0))


g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
for _ in range(4):
    g.press("triangle", 4, 40)
g.step(150); g.press("triangle", 4, 60)
for _ in range(slot):
    g.press("down", 4, 30)
for _ in range(8):
    g.press("triangle", 4, 40)
scan()
if to_map:   # Border Church (work/card2main.mcd slot 2): hold down to the world map
    for k in range(900):
        g.step(1, hold=("down",))
        if k % 15 == 0:
            scan()
i = 0
while i < N:
    r = rng.random()
    if r < 0.10:
        hold, n = (rng.choice(["triangle", "triangle", "cross", "square", "start", "select"]),), 4
    else:
        d = rng.choice(["up", "down", "left", "right"])
        hold, n = ((d, "circle") if rng.random() < 0.5 else (d,)), rng.randint(10, 90)
    for _ in range(n):
        g.step(1, hold=hold); i += 1
        if i % 15 == 0:
            scan()
    if i % 3000 < n:
        g.shot(f"ramfree_{seed}_{i // 3000:02d}")
tag = f"{os.path.basename(card)}_{slot}_{seed}{'_map' if to_map else ''}"
np.save(f"work/ramfree_{tag}.npy", used)
print(tag, "modes", sorted(hex(m) for m in modes), "used blocks", int(used.sum()))
