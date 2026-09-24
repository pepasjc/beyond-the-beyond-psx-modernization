"""Boot the GPU probe disc to the field; per vblank, report whether the GPU
was still busy when the next vblank started."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import boot_to_field
g = boot_to_field("work/gpu.cue")
rows = []
for f in range(300):
    hold = ("down",) if f < 100 else ("down", "circle") if f < 200 else ("up", "circle")
    g.step(1, hold=hold)
    stat, chcr, gate = g.u32(0x801E4800), g.u32(0x801E4804), g.u32(0x800C90A4)
    rows.append((gate, bool(stat >> 26 & 1), bool(chcr >> 24 & 1), bool(stat >> 28 & 1)))
busy = sum(1 for r in rows if (not r[1]) or r[2])
print("vblanks", len(rows), "GPU/DMA busy at vblank start:", busy)
print("by parity:", {p: sum(1 for r in rows if r[0] == p and ((not r[1]) or r[2])) for p in (0, 1)})
print("first 12 (gate, gpu_ready_cmd, dma2_busy, ready_dma):", rows[:12])
