"""Build the --smooth disc with interp60 options for debugging.
    python debug/smooth_build.py [noblend] -> work/smooth.bin/.cue"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_patch as bp
import interp60
if "noblend" in sys.argv:
    interp60.BLEND = False
interp60.TRACE = "trace" in sys.argv
for a in sys.argv:
    if a.startswith("pad="):
        interp60.PAD_TO = int(a[4:])
for a in sys.argv:
    if a.startswith("late="):
        interp60.LATE = int(a[5:])
    if a.startswith("submit="):
        interp60.SUBMIT_LIMIT = int(a[7:])
interp60.SKIP = tuple(a[5:] for a in sys.argv if a.startswith("skip="))
bp.SMOOTH = True
bp.main("original.bin", "work/smooth.bin")
open("work/smooth.cue", "w").write('FILE "smooth.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
