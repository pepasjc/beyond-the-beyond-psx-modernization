"""Log the leader and every follower (objects whose last script op is 0x25)
per frame while holding a direction.   python debug/follow_log.py <cue> <hold...>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import boot_to_field
O = 0x800FE700
cue, *hold = sys.argv[1:]
g = boot_to_field(cue)
g.step(10)
def prev_op(i):
    b = O + i * 0x70
    base, pc = g.u32(b), g.u16(b + 8)
    return g.u16(base + pc * 2 - 4) if base else None
followers = [i for i in range(64) if prev_op(i) == 0x25]
lead = g.s16(0x800CDDB8)
print("leader", lead, "followers", followers, [(i, g.u8(O + i * 0x70 + 0x11)) for i in followers])
for i in [lead] + followers:
    b = O + i * 0x70
    print(i, "acc", hex(g.u16(b + 0x14)), "fric", hex(g.u16(b + 0x16)), hex(g.u16(b + 0x18)))
for f in range(90):
    g.step(1, hold=tuple(hold))
    row = []
    for i in [lead] + followers:
        b = O + i * 0x70
        row.append((g.s32(b + 0x1c) >> 8, g.s32(b + 0x20) >> 8))
    print(f, row)
