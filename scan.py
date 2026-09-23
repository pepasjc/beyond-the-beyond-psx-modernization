"""List every "VP" that stands alone as a word, in every file on the disc.

    python scan.py <image.bin> [WORD]

Used to find the text to rename (VP -> HP).  Streams, sound banks and the
padding file are skipped.  Compressed files (the .TLK dialog) cannot be seen.
"""
import re
import struct
import sys

from disc import Disc

SKIP = (".STR", ".FIL", ".VB", ".SEQ")


def walk(d, lba, size, path, out):
    for s in range((size + 2047) // 2048):
        x = d.user(lba + s)
        p = 0
        while p < 2048 and x[p]:
            ln, nl, fl = x[p], x[p + 32], x[p + 25]
            n = x[p + 33:p + 33 + nl].decode("latin1").split(";")[0]
            l2, s2 = struct.unpack_from("<I", x, p + 2)[0], struct.unpack_from("<I", x, p + 10)[0]
            if n not in ("\x00", "\x01"):
                if fl & 2:
                    walk(d, l2, s2, path + n + "\\", out)
                else:
                    out.append(path + n)
            p += ln


def main(image, word="VP"):
    d = Disc(image)
    files = []
    root = d.user(16)[156:190]
    walk(d, struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "", files)
    pat = re.compile(rb"(?<![A-Za-z])" + word.encode() + rb"(?![A-Za-z])")
    for name in files:
        if name.endswith(SKIP):
            continue
        data = d.read_file(name)
        for m in pat.finditer(data):
            print(f"{name} {m.start():#x} {data[max(0, m.start() - 24):m.start() + 24]!r}")


if __name__ == "__main__":
    main(*sys.argv[1:])
