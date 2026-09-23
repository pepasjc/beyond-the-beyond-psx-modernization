"""Interactive-ish navigation: restore a state, run a move list, save a
state and a screenshot.

    python nav.py <cue> <in_state> <out_state> "down:60 right:30 tri ..."

Moves: <button>[+<button>...]:<frames>, or a bare button for a tap.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import Game  # noqa: E402

cue, src, dst, moves = sys.argv[1:5]
g = Game(cue, "card.mcd")
g.restore(open(src, "rb").read())
g.step(2)
for m in moves.split():
    if ":" in m:
        b, n = m.split(":")
        g.step(int(n), hold=tuple(b.split("+")) if b != "wait" else ())
    else:
        g.press({"tri": "triangle"}.get(m, m), 4, 20)
g.step(2)
open(dst, "wb").write(g.state())
name = dst.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
g.shot(name)
p = 0x800FE700
print(f"player px ({g.s32(p + 0x1c) >> 8},{g.s32(p + 0x20) >> 8})  battle_actor0_state={g.s16(0x800F9B20 + 0x14)}")
