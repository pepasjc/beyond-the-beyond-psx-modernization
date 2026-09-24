"""Test-only disc that samples the GPU state at the start of every vblank.

    python debug/gpu_time_build.py [base.bin]   ->  work/gpu.bin / work/gpu.cue

The per-vblank handler (0x800115CC) starts by resetting root counter 1
(jal 0x800C2FD0).  That call is redirected to a stub that first stores
GPUSTAT (0x1F801814) at 0x801E4800 and DMA2 CHCR (0x1F8010A8) at 0x801E4804,
then tail-jumps to the original.  A picture is submitted early in a 30 Hz
vblank; if the GPU is idle again at the start of the next vblank (GPUSTAT
bit 26 set, DMA2 busy bit 24 clear), one picture takes less than a frame.

Waiting on the GPU from inside the handler (DrawSync, or polling the same
registers) deadlocks: the draw queue advances in interrupt callbacks.  The
stub lives in the debug load-meter printout (0x80011650..), which is
skipped by turning its event-flag check into a branch.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_patch as bp  # noqa: E402
from disc import Disc  # noqa: E402

base_bin = sys.argv[1] if len(sys.argv) > 1 else "original.bin"
bp.main(base_bin, "work/gpu.bin")
d = Disc("work/gpu.bin")
exe = bytearray(d.read_file(bp.EXE_NAME))
base = struct.unpack_from("<I", exe, 0x18)[0] - 0x800


def jal(t):
    return struct.pack("<I", (3 << 26) | (t >> 2 & 0x3FFFFFF))


def put(addr, code):
    exe[addr - base:addr - base + len(code)] = code


# 0x80011648: "jal event_flag(0x10)" -> "b 0x800116c4" (skip the debug meter)
assert exe[0x80011648 - base:0x8001164C - base] == jal(0x80079DC0)
put(0x80011648, bp.branch(bp.BEQ, 0, 0x80011648, 0x800116C4))
put(0x8001164C, bp.assemble("nop", 0))

STUB = 0x80011650
code = bp.assemble("""
    lui   $t1, 0x1f80
    lw    $t0, 0x1814($t1)
    lw    $t2, 0x10a8($t1)
    lui   $at, 0x801e
    sw    $t0, 0x4800($at)
    j     0x800c2fd0
    sw    $t2, 0x4804($at)
""", STUB)
put(STUB, code)
assert STUB + len(code) <= 0x800116C4

# 0x800115D8: "jal 0x800c2fd0" (reset root counter 1) -> "jal STUB"
assert exe[0x800115D8 - base:0x800115DC - base] == jal(0x800C2FD0)
put(0x800115D8, jal(STUB))

d.write_file(bp.EXE_NAME, bytes(exe))
d.save("work/gpu.bin")
open("work/gpu.cue", "w").write('FILE "gpu.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
print("gpu probe disc ok")
