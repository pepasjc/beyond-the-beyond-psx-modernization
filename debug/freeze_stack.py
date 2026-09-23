"""Run work/smooth.cue until the first in-between picture freezes the game,
then list stack words that look like return addresses into game or cave code."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import Game
from interp60 import STREAK
g = Game("work/smooth.cue", "card.mcd")
g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
for _ in range(12):
    g.press("triangle", 4, 40)
g.step(240); g.press("triangle", 4, 20)
for i in range(200):
    g.step(1, hold=("right",))
    if g.u32(STREAK) >= 45:
        break
g.step(8)
st, ch = g.u32(0x801E6790), g.u32(0x801E6794)
print("probe GPUSTAT %08x CHCR %08x" % (st, ch))
print("framecnt", g.u32(0x800C9058), g.u32(0x800C9058))
lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x801FFB00
r = g.ram(lo, 0x801FFF00 - lo)
for o in range(0, len(r), 4):
    w = struct.unpack_from("<I", r, o)[0]
    if 0x80010000 <= w < 0x800C5800 and w % 4 == 0:
        print(hex(lo + o), hex(w))
