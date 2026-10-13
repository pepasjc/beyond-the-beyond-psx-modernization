"""Built-in RetroAchievements: the set of RetroAchievements game 11415, evaluated on the
console, with an unlock popup, an "Achievements" list in the field menu and its own
memory card file (see ra/src/btb_ra.c).

The PS1 code is C (ra/src), cross-compiled with mipsel-linux-gnu-gcc in a docker image
inside WSL (ra/docker/Dockerfile; image name in $RA_DOCKER_IMAGE, default re2-mipsel).
The set comes from the RetroAchievements server's `r=patch` response for game 11415
(work/ra/ra_11415_patch.json, fetched with a logged-in account); ra/compile_set.py
turns it into ra/src/gen/set.c, which is kept in the repository, so the build works
without the JSON.

Room: 0x800D5A88..0x800D9E88 is the buffer of libgpu's debug font (FntOpen's string and
sprite buffers, 17 KB), part of the BSS. Only a debug menu opens the font; FntOpen is
made to fail, the startup code clears the BSS from 0x800D9E88 on instead of 0x800D51A0
(the exe file holds zeros up to there), and the exe grows to load our code. It no
longer fits in its place on the disc, so it moves into the end of MOVIE/PAD.FIL, a
padding file nothing reads.

Hooks (each asserts the instruction it replaces):
  0x80011764  jal 0x80010EB0 (frame counter, every vblank)  -> ra_vblank
  0x80010278  jal 0x8007C180 (memory card module init)      -> ra_boot
  the field menu's last item text call and its dispatch    -> ra_items, menu_choice
  the 7 + 7 calls of the game's card event open / close    -> ra_card_open / ra_card_close
"""
import os
import struct
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "ra", "src")
SET_JSON = os.path.join(HERE, "work", "ra", "ra_11415_patch.json")
IMAGE = os.environ.get("RA_DOCKER_IMAGE", "re2-mipsel")

BASE, END = 0x800D5A90, 0x800D9E88      # in libgpu's debug font buffers (0x800D5A88..)
FNT_OPEN = 0x800AFA80
BSS_CLEAR = 0x800AC5C4                  # lui $v0, 0x800d / addiu $v0, $v0, 0x51a0
VBLANK_CALL, FRAME_COUNTER = 0x80011764, 0x80010EB0
BOOT_CALL, CARD_INIT = 0x80010278, 0x8007C180
CARD_OPEN, CARD_CLOSE = 0x8007C560, 0x8007C6F4
MENU_WINDOW_W = 0x8005338C              # field menu window: "addiu $a2, $zero, 10"
MENU_WINDOW_H = 0x80053390
MENU_LAST_ITEM = 0x8005345C             # field menu: the "Prepare" text call
MENU_RANGE_CHECK, MENU_LOOP_END = 0x8004F4BC, 0x8004F568
WIN_TEXT = 0x80047330
TRAMPOLINE = 0x8003BF58 + 4 * 170       # tail of the dead function save anywhere uses (176 words)
ENT_VBLANK, ENT_BOOT, ENT_ITEMS, ENT_CHOICE, ENT_OPEN, ENT_CLOSE = 0x00, 0x08, 0x10, 0x18, 0x20, 0x28

ICON = ["................",
        "..YYYYYYYYYYYY..",
        ".YYWYYYYYYYYYYY.",
        "YY.YWYYYYYYYY.YY",
        "Y..YWYYYYYYYY..Y",
        "Y..YWYYYYYYYY..Y",
        ".YY.YWYYYYYY.YY.",
        "...YYWYYYYYYY...",
        "....YYYYYYYY....",
        ".....YYYYYY.....",
        "......YYYY......",
        "......OYYO......",
        ".....OYYYYO.....",
        "....OOOOOOOO....",
        "...BBBBBBBBBB...",
        "...BBBBBBBBBB..."]


def jal(t): return struct.pack("<I", 3 << 26 | (t >> 2) & 0x3FFFFFF)
def j(t): return struct.pack("<I", 2 << 26 | (t >> 2) & 0x3FFFFFF)


def icon_c():
    """Memory card icon: 16-colour palette (BGR555) + 16x16 4-bit trophy."""
    pal = {".": 0x0000, "Y": 0x033F, "W": 0x6BFF, "O": 0x0198, "B": 0x2108}
    keys = list(pal)
    out = bytearray()
    for c in keys + [""] * (16 - len(keys)):
        out += struct.pack("<H", pal.get(c, 0))
    for row in ICON:
        for x in range(0, 16, 2):
            out.append(keys.index(row[x]) | keys.index(row[x + 1]) << 4)
    return "#include <stdint.h>\nconst uint8_t ra_icon[] = {" + ",".join(map(str, out)) + "};\n"


def wsl_path(p):
    p = os.path.abspath(p).replace("\\", "/")
    return f"/mnt/{p[0].lower()}{p[2:]}"


def build_blob():
    gen = os.path.join(SRC, "gen")
    os.makedirs(gen, exist_ok=True)
    if os.path.exists(SET_JSON):
        import sys
        sys.path.insert(0, os.path.join(HERE, "ra"))
        from compile_set import compile_set
        compile_set(SET_JSON, os.path.join(gen, "set.c"), os.path.join(gen, "set.txt"))
    open(os.path.join(gen, "icon.c"), "w", newline="\n").write(icon_c())
    src = wsl_path(SRC)
    cmd = f"docker run --rm -v {src}:/src -w /src {IMAGE} sh -c 'sh build.sh {BASE:#x} gen/ra.bin && cp obj/ra.map gen/ra.map'"
    r = subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-lc", cmd], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    blob = open(os.path.join(gen, "ra.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(gen, "ra.map")):
        q = line.split()
        if len(q) == 3:
            sym[q[2]] = int(q[0], 16) & 0xFFFFFFFF
    assert sym["_start"] == BASE and sym["_end"] <= END, hex(sym["_end"])
    return blob, sym


def apply(exe, base, assemble, branch, BEQ, AT_REG, save_labels):
    """Patch and grow exe (bytearray, PS-X EXE). save_labels: save anywhere's labels, or None."""
    blob, sym = build_blob()
    w = lambda a: struct.unpack_from("<I", exe, a - base)[0]
    put = lambda a, b: exe.__setitem__(slice(a - base, a - base + len(b)), b)

    # the debug font never opens: FntOpen returns -1 at once
    assert w(FNT_OPEN) == 0x27BDFFC0, hex(w(FNT_OPEN))           # addiu $sp, $sp, -0x40
    put(FNT_OPEN, assemble("jr $ra\naddiu $v0, $zero, -1", FNT_OPEN))
    # the startup code clears the BSS from the end of the font buffers on
    assert exe[BSS_CLEAR - base:BSS_CLEAR - base + 8] == assemble("lui $v0, 0x800d\naddiu $v0, $v0, 0x51a0", 0)
    put(BSS_CLEAR, assemble(f"lui $v0, {(END + 0x8000) >> 16:#x}\naddiu $v0, $v0, {(END & 0xFFFF) - ((END & 0x8000) << 1)}", 0))
    # grow the exe over the font buffers, our code in them (and zeros up to there)
    t_size = struct.unpack_from("<I", exe, 0x1C)[0]
    assert struct.unpack_from("<I", exe, 0x18)[0] == 0x80010000 and 0x80010000 + t_size <= BASE
    size = (sym["_end"] - 0x80010000 + 2047) & ~2047
    exe.extend(bytes(0x800 + size - len(exe)))
    struct.pack_into("<I", exe, 0x1C, size)
    put(BASE, blob)

    cfg = sym["ra_cfg"]
    save = save_labels is not None
    for i, v in enumerate((5 + save,                                       # menu_index
                           save_labels["menu"] if save else MENU_LOOP_END,  # menu_next
                           MENU_LOOP_END,
                           save_labels["items"] if save else WIN_TEXT,      # items_prev
                           10 + 2 * save,                                   # item_row
                           FRAME_COUNTER, CARD_INIT)):
        struct.pack_into("<I", exe, cfg - base + 4 * i, v)

    assert exe[VBLANK_CALL - base:VBLANK_CALL - base + 4] == jal(FRAME_COUNTER)
    put(VBLANK_CALL, jal(BASE + ENT_VBLANK))
    assert exe[BOOT_CALL - base:BOOT_CALL - base + 4] == jal(CARD_INIT)
    put(BOOT_CALL, jal(BASE + ENT_BOOT))
    # field menu: one more item (window 2 rows taller, 5 columns wider: "Achievements" from column 1)
    h = w(MENU_WINDOW_H)
    assert h >> 16 == 0x2407 and (h & 0xFFFF) in (11, 13), hex(h)
    put(MENU_WINDOW_H, assemble(f"addiu $a3, $zero, {(h & 0xFFFF) + 2}", 0))
    assert exe[MENU_WINDOW_W - base:MENU_WINDOW_W - base + 4] == assemble("addiu $a2, $zero, 10", 0)
    put(MENU_WINDOW_W, assemble("addiu $a2, $zero, 15", 0))
    assert exe[MENU_LAST_ITEM - base:MENU_LAST_ITEM - base + 4] == jal(save_labels["items"] if save else WIN_TEXT)
    put(MENU_LAST_ITEM, jal(BASE + ENT_ITEMS))
    assert exe[MENU_RANGE_CHECK - base:MENU_RANGE_CHECK - base + 4] == branch(
        BEQ, AT_REG, MENU_RANGE_CHECK, save_labels["menu"] if save else MENU_LOOP_END)
    put(TRAMPOLINE, j(BASE + ENT_CHOICE) + bytes(4))
    put(MENU_RANGE_CHECK, branch(BEQ, AT_REG, MENU_RANGE_CHECK, TRAMPOLINE))
    # the game's card event open / close
    n = 0
    for target, ent in ((CARD_OPEN, ENT_OPEN), (CARD_CLOSE, ENT_CLOSE)):
        for a in range(0x80010000, 0x80010000 + t_size, 4):
            if exe[a - base:a - base + 4] == jal(target):
                put(a, jal(BASE + ent)); n += 1
    assert n == 14, n
    return len(blob), sym["_end"]
