"""Random-input soak test: boot work/<cue> to the field, then mash random
directions (often with circle = run) and the occasional face button
(menus, dialogs, doors, battles) for N frames; report a freeze (no
vblank-handler progress for 5 s) and how much of the time the in-between
pictures were active.
    python debug/soak.py [cue] [frames] [seed]"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import Game
from interp60 import STREAK
cue = sys.argv[1] if len(sys.argv) > 1 else "work/smooth.cue"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rng = random.Random(int(sys.argv[3]) if len(sys.argv) > 3 else 1)
g = Game(cue, "card.mcd")
g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
for _ in range(12):
    g.press("triangle", 4, 40)
g.step(240); g.press("triangle", 4, 20)
prev, same, active, i = None, 0, 0, 0
trail = []
TRACE_FROM = int(os.environ.get("SOAK_TRACE_FROM", "-1"))
while i < N:
    r = rng.random()
    if r < 0.08:
        hold, n = (rng.choice(["triangle", "cross", "square", "start"]),), 4
    else:
        d = rng.choice(["up", "down", "left", "right"])
        hold, n = ((d, "circle") if rng.random() < 0.5 else (d,)), rng.randint(10, 90)
    for _ in range(n):
        g.step(1, hold=hold)
        i += 1
        fc = g.u32(0x800C9058)
        same = same + 1 if fc == prev else 0
        prev = fc
        active += g.u32(STREAK) >= 45
        if 0 <= TRACE_FROM <= i and i % 10 == 0:
            trail.append((i, fc, g.u32(STREAK), g.u32(0x800DB4E0), g.u32(0x800DB4E4), g.u32(0x800DB4E8), hold))
            if i % 250 == 0:
                g.shot(f"trail_{i}")
        if same > 300:
            g.shot("soak_frozen")
            open("work/soak_trail.txt", "w").write(chr(10).join("f=%d framecnt=%d streak=%d cbs=%08x %08x %08x %s" % t for t in trail))
            for t in trail[-40:]:
                print("  f=%d framecnt=%d streak=%d cbs=%08x %08x %08x %s" % t)
            tcb = g.u32(g.u32(0x80000108))
            print("  tcb epc %08x ra %08x sp %08x cause %08x" % (g.u32(tcb + 0x88), g.u32(tcb + 0x84), g.u32(tcb + 0x7C), g.u32(tcb + 0x98)))
            sys.exit(f"FROZEN at frame {i} (streak {g.u32(STREAK)}), shots/soak_frozen.png")
    if i % 2000 < n:
        g.shot(f"soak_{i // 2000:02d}")
print(f"OK {N} frames, in-between pictures active {100 * active // N}% of the time")
