"""Random-input soak of an achievements build: freezes, and whether anything wrote into
our code and tables (0x800D5A90.. up to the .data section) while the game ran.
    python debug/ach_soak.py <cue> <card> <slot 0-2> <frames> <seed> [map]"""
import os, random, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import Game

cue, card, slot, N, seed = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
to_map = len(sys.argv) > 6 and sys.argv[6] == "map"
sym = {l.split()[2]: int(l.split()[0], 16) & 0xFFFFFFFF for l in open("ra/src/gen/ra.map") if len(l.split()) == 3}
blob = open("ra/src/gen/ra.bin", "rb").read()
BASE = sym["_start"]
ro_end = sym["__data_start"] - BASE
cfg = (sym["ra_cfg"] - BASE, sym["ra_cfg"] - BASE + 7 * 4)
tmp = f"work/ra/soak_{seed}.mcd"
shutil.copy(card, tmp)
rng = random.Random(seed)
g = Game(cue, tmp)
g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
for _ in range(4):
    g.press("triangle", 4, 40)
g.step(150); g.press("triangle", 4, 60)
for _ in range(slot):
    g.press("down", 4, 30)
for _ in range(8):
    g.press("triangle", 4, 40)
if to_map:
    g.step(900, hold=("down",))


def intact():
    if os.environ.get("NOCHECK"):            # a build without achievements, for comparison
        return []
    ram = g.ram(BASE, ro_end)
    bad = [i for i in range(0, ro_end, 4) if not (cfg[0] <= i < cfg[1]) and ram[i:i + 4] != blob[i:i + 4]]
    return bad


prev, same, i, battles, last, reboots = None, 0, 0, 0, 0, 0
while i < N:
    if rng.random() < 0.10:
        hold, n = (rng.choice(["triangle", "triangle", "cross", "square", "start", "select", "circle"]),), 4
    else:
        d = rng.choice(["up", "down", "left", "right"])
        hold, n = ((d, "circle") if rng.random() < 0.5 else (d,)), rng.randint(10, 90)
    for _ in range(n):
        g.step(1, hold=hold); i += 1
        fc = g.u32(0x800C9058)
        if prev and fc < prev:
            reboots += 1                     # the game restarts itself through the BIOS (quit to title)
        same = same + 1 if fc == prev else 0
        prev = fc
        mode = g.u32(0x800DB4E4)
        if mode == 0x80011DDC and last != mode:
            battles += 1
        last = mode
        if same > 300:
            # the BIOS boot and the logos after a restart don't count frames: wait, press START
            for k in range(3000):
                g.step(1, hold=("start",) if k % 60 < 4 else ())
                if g.u32(0x800C9058) != fc:
                    break
            same = 0 if g.u32(0x800C9058) != fc else 301
            prev = g.u32(0x800C9058)
        if same > 300:
            g.shot(f"achsoak_frozen_{seed}")
            tcb = g.u32(g.u32(0x80000108))
            sys.exit(f"FROZEN at {i}: epc {g.u32(tcb + 0x88):08x} ra {g.u32(tcb + 0x84):08x}")
    if i % 5000 < n:
        bad = intact()
        if bad:
            sys.exit(f"region written at frame {i}: {[hex(BASE + b) for b in bad[:8]]}")
        g.shot(f"achsoak_{seed}_{i // 5000:02d}")
bad = intact()
print(f"seed {seed}: {'OK' if not bad else 'REGION WRITTEN ' + str([hex(BASE + b) for b in bad[:8]])} {N} frames, "
      f"{battles} battles, {reboots} restarts" + ("" if os.environ.get("NOCHECK") else
      f", cost max {g.u16(sym['ra_cost_max'])} hblanks, unlocked {g.ram(sym['bits'], 8).hex()}"))
