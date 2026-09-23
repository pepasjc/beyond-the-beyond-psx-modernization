import sys
from emu import boot_to_field
O = 0x800FE700
img, label = sys.argv[1], sys.argv[2]
g = boot_to_field(img)
open(f"work/st_field_{label}.bin", "wb").write(g.state())
ys = []
for f in range(40):
    g.step(1, hold=("down", "circle")); ys.append(g.s32(O + 0x20))
d = [(b - a) / 256 for a, b in zip(ys, ys[1:])]
print(label, [round(x, 1) for x in d if x])
