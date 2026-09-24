"""Which 256-byte blocks of high RAM (0x801E0000..0x80200000) does the game
ever write during a random-input soak?  Run on a disc without our code.
    python debug/ramuse.py [cue] [frames] [seed]"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from emu import Game
cue = sys.argv[1] if len(sys.argv) > 1 else "work/control.cue"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rng = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 1)
LO, HI = 0x801E0000, 0x80200000
g = Game(cue, "card.mcd")
used = np.zeros((HI - LO) // 256, bool)
def scan():
    a = np.frombuffer(g.ram(LO, HI - LO), np.uint8).reshape(-1, 256)
    used[:] |= a.any(1)
for k in range(2120 + 480 + 600 + 12 * 44 + 240 + 24):
    pass
g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
for _ in range(12):
    g.press("triangle", 4, 40)
g.step(240); g.press("triangle", 4, 20)
scan()
i = 0
while i < N:
    if rng.random() < 0.08:
        hold, n = (rng.choice(["triangle", "cross", "square", "start"]),), 4
    else:
        d = rng.choice(["up", "down", "left", "right"])
        hold, n = ((d, "circle") if rng.random() < 0.5 else (d,)), rng.randint(10, 90)
    for _ in range(n):
        g.step(1, hold=hold); i += 1
        if i % 15 == 0:
            scan()
free, start = [], None
for b in range(len(used) + 1):
    if b < len(used) and not used[b]:
        start = b if start is None else start
    elif start is not None:
        free.append((LO + start * 256, LO + b * 256)); start = None
for s, e in sorted(free, key=lambda x: x[0] - x[1])[:8]:
    print(f"never written: {s:#x}..{e:#x} ({(e - s) // 1024} KB)")
np.save(f"work/ramuse_{os.path.basename(cue)}_{sys.argv[3] if len(sys.argv) > 3 else 1}.npy", used)
