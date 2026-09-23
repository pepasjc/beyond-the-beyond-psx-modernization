"""Boot work/smooth.cue to the field, walk left/right inside the church,
report a freeze (no vblank-handler progress for 5 s; shorter stalls happen
normally, e.g. during map changes).
    python debug/stability.py [frames]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import Game
from interp60 import STREAK
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
g = Game("work/smooth.cue", "card.mcd")
g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
for _ in range(12):
    g.press("triangle", 4, 40)
g.step(240); g.press("triangle", 4, 20)
prev, same = None, 0
for i in range(N):
    g.step(1, hold=("left",) if (i // 60) % 2 else ("right",))
    fc = g.u32(0x800C9058)
    same = same + 1 if fc == prev else 0
    prev = fc
    if same > 300:
        print(f"FROZEN at +{i}  streak={g.u32(STREAK)}")
        break
else:
    print(f"OK {N} frames  streak={g.u32(STREAK)}")
