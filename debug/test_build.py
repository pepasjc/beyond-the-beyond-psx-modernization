"""Test-only disc: every step starts a battle, using a fixed encounter area.

    AREA=<n> python work/test_build.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_patch as bp  # noqa: E402
from disc import Disc  # noqa: E402

bp.GRACE_STEPS = 0
bp.main("patched.bin", "work/test.bin")
d = Disc("work/test.bin")
exe = bytearray(d.read_file(bp.EXE_NAME))
base = struct.unpack_from("<I", exe, 0x18)[0] - 0x800

# encounter roll always succeeds
o = 0x8006E04C - base
assert exe[o:o + 4] == bp.assemble("slt $at, $t6, $s1", 0)
exe[o:o + 4] = bp.assemble("addiu $at, $zero, 1", 0)

# area lookup returns a fixed encounter area, even in towns
AREA = int(os.environ.get("AREA", "1"))
o = 0x8006F778 - base
exe[o:o + 8] = bp.assemble("jr $ra\naddiu $v0, $zero, %d" % AREA, 0x8006F778)

d.write_file(bp.EXE_NAME, bytes(exe))
d.save("work/test.bin")
open("work/test.cue", "w").write('FILE "test.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
print("test disc ok, area", AREA)
