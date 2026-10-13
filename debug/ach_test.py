"""End-to-end test of the built-in achievements on a built disc (Beetle, emu.py):
    python debug/ach_test.py [cue] [card]
1. boot with a copy of the card: the achievements file BASCUS-94702ACH is created;
2. "Rise of the Hero" is forced (Finn's class byte 0x801149C8 = 1, 0x801149C9 0 -> 1):
   it unlocks, the popup shows, the card file gets the bit at once (no save);
3. field menu > Achievements: the list shows it unlocked; Circle closes the list;
4. boot again with the card as it is now: the bit is read back and nothing triggers again.
Screenshots: shots/achtest_*.png."""
import ctypes, os, shutil, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from emu import boot_to_field

cue = sys.argv[1] if len(sys.argv) > 1 else "work/ach.cue"
card = sys.argv[2] if len(sys.argv) > 2 else "card.mcd"
sym = {l.split()[2]: int(l.split()[0], 16) & 0xFFFFFFFF for l in open("ra/src/gen/ra.map") if len(l.split()) == 3}
RISE = 49                                   # "Rise of the Hero" in the set's order
os.makedirs("work/ra", exist_ok=True)
tmp = "work/ra/achtest.mcd"
shutil.copy(card, tmp)


def card_files(path):
    d = open(path, "rb").read()
    out = {}
    for i in range(1, 16):
        e = d[i * 0x80:(i + 1) * 0x80]
        if struct.unpack_from("<I", e, 0)[0] == 0x51:
            out[e[0x0A:0x1E].split(b"\0")[0].decode()] = d[i * 0x2000:(i + 1) * 0x2000]
    return out


def bit_on_card(path):
    f = card_files(path).get("BASCUS-94702ACH")
    return f is not None and f[0x200:0x204] == b"BBAC" and f[0x208 + RISE // 8] >> (RISE % 8) & 1


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        sys.exit(1)


g = boot_to_field(cue, tmp)
poke = lambda a, v: ctypes.memmove(g._ram + (a & 0x1FFFFF), bytes([v]), 1)
bits = lambda: g.ram(sym["bits"], 8)
check(g.s32(sym["rt_port"]) == 0, "achievements file found or made in slot 1")
check(not bits()[RISE // 8] >> (RISE % 8) & 1, "starts locked")
poke(0x801149C8, 1); poke(0x801149C9, 0); g.step(3); poke(0x801149C9, 1); g.step(20)
check(bits()[RISE // 8] >> (RISE % 8) & 1, "unlocked")
check(g.s16(sym["pop_h"]) >= 0, "popup window open")
g.shot("achtest_popup")
g.step(10); g.emu.save_card(tmp)
check(bit_on_card(tmp), "card file has the bit right away")
g.step(300)
check(g.s16(sym["pop_h"]) < 0, "popup closed")
g.press("triangle", 4, 40)
for _ in range(g.u32(sym["ra_cfg"])):         # menu_index: 6 with save anywhere, else 5
    g.press("down", 4, 15)
g.press("triangle", 4, 30)
check(g.u32(sym["page_open"]) == 1, "list open")
for _ in range(8):
    g.press("right", 4, 8)
g.press("down", 4, 8)
g.step(10); g.shot("achtest_list")
g.press("circle", 4, 30)
check(g.u32(sym["page_open"]) == 0, "Circle closes the list")
g.emu.save_card(tmp)
del g

g = boot_to_field(cue, tmp)
check(g.ram(sym["bits"], 8)[RISE // 8] >> (RISE % 8) & 1, "bit read back at boot")
check(g.u8(sym["ra_st"] + RISE) == 3, "and not evaluated again")
g.step(120)
check(g.u32(sym["nqueue"]) == 0 and g.s16(sym["pop_h"]) < 0, "no popup after the reboot")
print("all ok")
