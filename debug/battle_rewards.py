import os, sys
sys.path.insert(0, os.getcwd())
from emu import boot_to_field
g = boot_to_field("work/test.cue")
g.step(30, hold=("down",)); g.step(300)
for rnd in range(6):
    for _ in range(7):
        g.step(4, hold=("triangle",)); g.step(24)
    g.step(700)
    print("round", rnd, "EXP total", g.u32(0x800F9B08), "gold total", g.u32(0x800F9B0C))
