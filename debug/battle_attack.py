"""Boot the test disc, start a battle, attack with everyone, log Finn's
movement and record the turn to an mp4.   python work/battle_attack.py <cue> <tag>"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import boot_to_field

cue, tag = sys.argv[1], sys.argv[2]
g = boot_to_field(cue)
g.step(30, hold=("down",)); g.step(300)
def tap(): g.step(4, hold=("triangle",)); g.step(24)
tap()
for _ in range(3):
    tap(); tap()
A = 0x800F9B20
w, h = g.emu.image().size
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                       "-s", f"{w}x{h}", "-r", "60", "-i", "-", "-vf", "scale=iw*2:ih*2:flags=neighbor",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", f"clips/battle_{tag}.mp4"],
                      stdin=subprocess.PIPE)
prev = None
for f in range(420):
    g.step(1)
    ff.stdin.write(g.emu.image().convert("RGB").tobytes())
    row = (g.s16(A), g.s16(A + 4), g.s16(A + 0x14), g.s16(A + 0x16))
    if row[:2] != (prev or row)[:2] or (prev and row[2] != prev[2]):
        print(f, "finn x,z", row[:2], "state", row[2], "cnt", row[3])
    prev = row
ff.stdin.close(); ff.wait()
