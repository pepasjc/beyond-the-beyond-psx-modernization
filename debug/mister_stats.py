"""Print the 60 Hz presentation statistics (interp60.STATS) from a MiSTer PSX
savestate (main RAM sits at file offset 0x200000) or from a Beetle RAM dump.

    python debug/mister_stats.py <file.ss>
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import interp60 as I  # noqa: E402

MISTER_RAM = 0x200000


def report(u32):
    if u32(I.STATS + 4 * I.STAT_MAGIC) != I.STAT_MAGIC_VALUE:
        print("no statistics in this RAM (not a stats build, or not booted to a map yet)")
        return
    for i, name in I.STAT_NAMES.items():
        print(f"{name:40s} {u32(I.STATS + 4 * i):8d}")
    for base, title, width in ((I.STAT_HIST_DONE, "in-between picture finished at tick line", 4),
                               (I.STAT_HIST_SUBMIT, "in-between picture submitted at idle line", 16)):
        print(title + ":")
        for b in range(16):
            n = u32(I.STATS + 4 * (base + b))
            if n:
                hi = f"{(b + 1) * width - 1:3d}" if b < 15 else "  +"
                print(f"  {b * width:3d}-{hi} {n:8d}")
    names = ("STREAK", "SHOWN", "NEXT", "MID", "COOL", "FAILS")
    print("state", {n: u32(getattr(I, n)) for n in names})


def main():
    d = open(sys.argv[1], "rb").read()
    base = MISTER_RAM if len(d) > 0x200000 else 0
    report(lambda a: struct.unpack_from("<I", d, base + (a & 0x1FFFFF))[0])


if __name__ == "__main__":
    main()
