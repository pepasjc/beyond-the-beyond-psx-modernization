"""Boot work/smooth.cue to the field, walk up and down, report a freeze.
    python debug/stability.py [frames]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import Game
N = int(sys.argv[1]) if len(sys.argv) > 1 else 400
g = Game("work/smooth.cue", "card.mcd")
g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
for _ in range(12):
    g.press("triangle", 4, 40)
g.step(240); g.press("triangle", 4, 20)
prev, same = None, 0
for i in range(N):
    g.step(1, hold=("down",) if (i // 120) % 2 else ("up",))
    fc = g.u32(0x800C9058)
    same = same + 1 if fc == prev else 0
    prev = fc
    if same > 30:
        print(f"FROZEN at +{i}  streak={g.u32(0x801E6780)}")
        break
else:
    print(f"OK {N} frames  streak={g.u32(0x801E6780)}")
