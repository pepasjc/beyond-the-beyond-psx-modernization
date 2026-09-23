"""Headless Beetle PSX harness for Beyond the Beyond.

Built on the libretro host emurun.py from the Snatcher translation project,
which drives the Beetle PSX (mednafen_psx) libretro core through ctypes.
Point EMURUN_DIR at the folder that holds emurun.py.
"""
import ctypes as C
import os
import struct
import sys

sys.path.insert(0, os.environ.get("EMURUN_DIR", r"F:\Isos\Saturn\snatcher\lib"))
from emurun import Emu  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RAM_BASE = 0x80000000


class Game:
    def __init__(self, image, card=None):
        os.chdir(HERE)
        os.makedirs("work/emu", exist_ok=True)
        self.emu = Emu()
        self.emu.load(image)
        if card:
            self.emu.load_card(card)
        c = self.emu.core
        c.retro_get_memory_data.restype = C.c_void_p
        c.retro_get_memory_size.restype = C.c_size_t
        self._ram = c.retro_get_memory_data(2)
        self._ram_size = c.retro_get_memory_size(2)
        self.frame = 0

    # --- RAM ---
    def ram(self, addr, n):
        off = (addr - RAM_BASE) & 0x1FFFFF
        return C.string_at(self._ram + off, n)

    def u8(self, a): return self.ram(a, 1)[0]
    def u16(self, a): return struct.unpack("<H", self.ram(a, 2))[0]
    def s16(self, a): return struct.unpack("<h", self.ram(a, 2))[0]
    def u32(self, a): return struct.unpack("<I", self.ram(a, 4))[0]
    def s32(self, a): return struct.unpack("<i", self.ram(a, 4))[0]

    # --- time / input ---
    def step(self, n=1, hold=()):
        self.emu.held = {self._btn(b) for b in hold}
        for _ in range(n):
            self.emu.run()
            self.frame += 1

    def press(self, btn, hold_frames=4, after=20):
        self.step(hold_frames, hold=(btn,))
        self.step(after)

    def shot(self, name):
        self.emu.image().save(os.path.join(HERE, "shots", name + ".png"))

    def state(self): return self.emu.state()
    def restore(self, blob): self.emu.restore(blob)

    @staticmethod
    def _btn(b):
        from emurun import BTN
        return BTN[b] if isinstance(b, str) else b


def boot_to_field(image, card="card.mcd"):
    """Title -> Continue -> slot 1 -> first field frame (Marion church)."""
    g = Game(image, card)
    g.step(2120); g.press("start", 4, 4); g.step(480); g.press("start", 4, 4); g.step(600)
    for _ in range(12):
        g.press("triangle", 4, 40)
    g.step(240); g.press("triangle", 4, 20)
    for _ in range(60):
        g.step(30)
        if g.u32(0x8010E0D8):
            break
    g.step(120)
    return g
