"""OR the masks of debug/ramfree.py runs and list the never-used ranges.
    python debug/ramfree_sum.py [min KB]"""
import glob, sys
import numpy as np

used = None
for f in glob.glob("work/ramfree_*.npy"):
    m = np.load(f)
    used = m if used is None else used | m
MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 2
start = None
for b in range(len(used) + 1):
    if b < len(used) and not used[b]:
        start = b if start is None else start
    elif start is not None:
        if (b - start) * 256 >= MIN * 1024:
            print(f"{0x80000000 + start * 256:#x}..{0x80000000 + b * 256:#x}  {(b - start) * 256 / 1024:.1f} KB")
        start = None
