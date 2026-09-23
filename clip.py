import os, subprocess, sys
from emu import Game
img, state, out, *hold = sys.argv[1:]
g = Game(img, "card.mcd")
g.restore(open(state, "rb").read()); g.step(2)
os.makedirs("clips", exist_ok=True)
w, h = g.emu.image().size
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                       "-s", f"{w}x{h}", "-r", "60", "-i", "-", "-vf", "scale=iw*2:ih*2:flags=neighbor",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12", f"clips/{out}.mp4"],
                      stdin=subprocess.PIPE)
for f in range(150):
    g.step(1, hold=tuple(hold)); ff.stdin.write(g.emu.image().convert("RGB").tobytes())
ff.stdin.close(); ff.wait()
print(out, "ok")
