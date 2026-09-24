"""Beyond the Beyond (USA) SCUS_947.02 modernization patch.

    python build_patch.py <in.bin> <out.bin> [--run 2x|1.5x] [--exp N] [--gold N]

Input is a MODE2/2352 .bin of the original Beyond the Beyond (USA), CRC32
453917AF.  Inspired by "Beyond the Beyond - Reunion" by Skiller and
Shadow501 (https://www.romhacking.net/hacks/9516/); a Reunion 1.4 disc is
also accepted, in which case its executable changes are replaced and the
result is the same executable.
Changes, all in SCUS_947.02 except where noted:

1. Swap X and Triangle.  The game's per-frame input routine (0x80011350)
   stores pad 1 into held/pressed/repeat globals at 0x800C9070..80.  It is
   rewritten more compactly and swaps bit 4 (Triangle) with bit 6 (X) of
   the PadRead() result before anything else sees it.  Its leftover space
   holds the follower-check helper used by (2).  The secret-code reader at
   0x8007FE74 calls PadRead() directly and keeps raw buttons.

2. Run with Circle, smooth followers.  The map-object physics loop
   (0x800894CC, $s3 = object index, obj ptr in $t2) computes accel =
   obj[0x14]*obj[0x18]>>8 and integrates velocity with linear friction.
   Running raises accel and friction together (see RUN_PRESETS) so the
   player reaches the faster top speed within one update instead of
   re-accelerating at every tile.  Followers (objects whose last script
   opcode is 0x25, "follow obj[0x11]") always use that fast-response
   physics at the leader's speed, so they glide instead of rushing each tile
   and waiting.  Circle has no field function in the original game.
   Inlining sin/cos (table at 0x800CCD50) frees the space, and the velocity
   update floors sub-pixel steps instead of rounding toward zero.

3. Rename VP to HP in menu labels and item/spell names (exe and
   SYSTEM\RESIUS.DAT).  Dialog (.TLK) is compressed and not touched.

4. Rewards: EXP and gold multipliers (see EXP_PRESETS, GOLD_PRESETS).  On a
   Reunion disc this also fixes Reunion's gold-lookup slip (a stale monster
   id in one of the enemy-defeat paths).

5. Random encounters: the original per-step roll against the area's rate,
   with a 25-step grace period after each fight (Reunion instead forces one
   battle every 70 steps).

6. Faster walk-up in battle: the plain melee attack walks to the enemy in
   6 updates instead of 12 (same distance), leaving the swing untouched.

7. Curse flag as in the original game (undoes Reunion's change at
   0x80073B80, which also clobbered the last byte of character names).

8. Save anywhere: a sixth field-menu item "Save" (window 2 rows taller;
   the chooser counts items from the height; a choice past the dispatch
   table lands in our handler) and SELECT on the field (unused in the
   original) run the church's "record your journey" routine from its
   Yes/No question on, then close the message window (see SAVE_CODE).
   SELECT also halts the player like the menu does and gives control back.
   --no-save-anywhere turns it off.

9. Extras menu (Prepare > Setting > Extras): random battles Off/50%/100%/
   200%, EXP boost and gold boost On/Off, stored in unused bits of the
   settings word (saved with the game; 0 = as built).  The encounter check,
   the three reward blocks and the three gold sites call small gates that
   read those bits (see OPTIONS_CODE).  --no-options leaves them fixed.
"""
import struct
import sys

from keystone import Ks, KS_ARCH_MIPS, KS_MODE_MIPS32, KS_MODE_LITTLE_ENDIAN

from disc import Disc

ks = Ks(KS_ARCH_MIPS, KS_MODE_MIPS32 + KS_MODE_LITTLE_ENDIAN)
EXE_NAME = "SCUS_947.02"

# --- 1. input routine, pad 1 block: 0x80011350 .. 0x800113EC (40 words) ---
INPUT_START, INPUT_END = 0x80011350, 0x800113F0
INPUT = """
    nop
    move  $a0, $zero
    srl   $t0, $v0, 2
    xor   $t0, $t0, $v0
    andi  $t0, $t0, 0x10
    sll   $t1, $t0, 2
    or    $t0, $t0, $t1
    xor   $v0, $v0, $t0
    lui   $at, 0x800d
    lhu   $a0, -0x6f84($at)
    andi  $v1, $v0, 0xffff
    sh    $v0, -0x6f90($at)
    xor   $t7, $v1, $a0
    and   $t8, $t7, $v1
    sh    $t8, -0x6f88($at)
    bnez  $v1, held
    sh    $zero, -0x6f8c($at)
    b     store_timer
    addiu $v0, $zero, 0xf
held:
    bne   $v1, $a0, changed
    nop
    lhu   $v0, -0x6f80($at)
    nop
    addiu $v0, $v0, -1
    andi  $v0, $v0, 0xffff
    bnez  $v0, store_timer
    nop
    b     repeat
    addiu $v0, $zero, 3
changed:
    addiu $v0, $zero, 0xf
repeat:
    sh    $v1, -0x6f8c($at)
store_timer:
    sh    $v0, -0x6f80($at)
    nop
    sh    $v1, -0x6f84($at)
"""

# Leftover space after the input routine holds a helper for the physics
# block: $t7 = script opcode just executed by the object in $t2
# (halfword at script_base + pc*2 - 4).  Party followers run opcode 0x25
# (follow object obj[0x11]) every frame.  Result arrives in a load delay
# slot, so the caller must not read $t7 in its next instruction.
# Clobbers $t5, $t7.
PREV_OP_HELPER = """
    lhu   $t5, 8($t2)
    lw    $t7, 0($t2)
    sll   $t5, $t5, 1
    addu  $t7, $t7, $t5
    jr    $ra
    lhu   $t7, -4($t7)
"""

# --- 2. object physics: 0x80089658 .. 0x80089774 (72 words) ---
PHYS_START, PHYS_END = 0x80089658, 0x80089778
PHYS = """
    lhu   $t4, 0x14($t2)
    lhu   $t8, 0x18($t2)
    jal   HELPER
    lui   $at, 0x800d
    lbu   $a0, 0xd($t2)
    multu $t4, $t8
    lhu   $t6, -0x6f90($at)
    lh    $t9, -0x2248($at)
    andi  $t6, $t6, 0x20
    srl   $t6, $t6, 5
    mflo  $s0
    srl   $s0, $s0, 8
    bne   $t9, $s3, npc
    move  $a1, $t6
    beqz  $a1, walk
    RUN_ACCEL_1
    RUN_ACCEL_2
    b     walk
    RUN_ACCEL_3
npc:
    xori  $t7, $t7, 0x25
    bnez  $t7, walk
    move  $a1, $zero
    addiu $a1, $zero, 1
    beqz  $t6, walk
    addiu $s0, $zero, FOLLOW_WALK
    addiu $s0, $s0, FOLLOW_RUN_ADD
walk:
    sll   $t8, $a0, 1
    addu  $t8, $t8, $at
    lh    $v0, -0x32b0($t8)
    addiu $t9, $a0, 0x40
    andi  $t9, $t9, 0xff
    multu $v0, $s0
    sll   $t9, $t9, 1
    addu  $t9, $t9, $at
    lh    $v1, -0x32b0($t9)
    lh    $t3, 0x48($t2)
    mflo  $t5
    sra   $t6, $t5, 8
    addu  $t3, $t3, $t6
    sh    $t3, 0x48($t2)
    multu $v1, $s0
    lh    $t7, 0x4a($t2)
    mflo  $t9
    negu  $t9, $t9
    sra   $t5, $t9, 8
    addu  $t7, $t7, $t5
    sh    $t7, 0x4a($t2)
friction:
    lhu   $t4, 0x16($t2)
    lh    $v0, 0x48($t2)
    beqz  $a1, fr
    lhu   $t8, 0x18($t2)
    addiu $t4, $zero, RUN_FRICTION
fr:
    multu $v0, $t4
    lh    $v1, 0x4a($t2)
    mflo  $t1
    lui   $t7, 0x8011
    lui   $t6, 0x8011
    multu $t1, $t8
    mflo  $t9
    srl   $t9, $t9, 16
    subu  $v0, $v0, $t9
    sh    $v0, 0x48($t2)
    multu $v1, $t4
    mflo  $t1
    lui   $t3, 0x8011
    lui   $t0, 0x8011
    multu $t1, $t8
    mflo  $t9
    srl   $t9, $t9, 16
    subu  $v1, $v1, $t9
    sh    $v1, 0x4a($t2)
    lui   $t2, 0x8011
"""

# --- 3. "VP" -> "HP" (same length, in place) ---
# Menu/status labels in the exe (NUL-terminated "VP" strings).
VP_EXE = [0x800C65E0, 0x800C65F0, 0x800C687C, 0x800C6890, 0x800C689C,
          0x800C7198, 0x800C75BC]
# Item/spell names in SYSTEM\RESIUS.DAT: "VP Up", "Everyone's VP Heal".
VP_RESIUS = [0x8174, 0x82E8]


def vp_to_hp(buf, offsets):
    for off in offsets:
        assert buf[off:off + 2] == b"VP", hex(off)
        buf[off] = ord("H")


# --- 4. Rewards: EXP and gold multipliers ---
# Enemy-defeat reward code, one copy per death animation (0x800423F8,
# 0x80042490, 0x80042528), each adding the monster's EXP to the battle total
# (0x800F9B08) and ending in "jal FXP_GetMonsterGold".  The block is
# rewritten whole, so it works on the original code and on Reunion's.  The
# multiplier needs up to two instructions: one from the load-delay nop
# after "lh $a0,0x12($t3)", one from the "sll/sra" pair that sign-extended
# the gold-lookup argument (FXP_GetMonsterGold sign-extends its own).
# Rewriting also undoes Reunion's "lh $a1" in the first copy, which handed
# the gold lookup a stale monster id.
REWARD_BLOCKS = [0x800423F8, 0x80042490, 0x80042528]
REWARD = """
    lui   $at, 0x8010
    multu $s5, $s4
    lw    $t1, -0x64f8($at)
    EXP_OP_1
    EXP_OP_2
    addu  $t9, $t1, $t0
    mflo  $t2
    addu  $t3, $s3, $t2
    lh    $a0, 0x12($t3)
    addu  $t9, $t9, $v0
    sw    $t9, -0x64f8($at)
    jal   0x80072670
    addiu $a0, $a0, -0xa
    nop
"""

# EXP gained = v + t0 + v' where t0 and v' come from these two ops.
EXP_PRESETS = {
    "1": ("move $t0, $zero", "nop"),
    "1.5": ("srl $t0, $v0, 1", "nop"),
    "2": ("move $t0, $v0", "nop"),
    "2.5": ("sll $t0, $v0, 1", "srl $v0, $v0, 1"),     # 2v + v/2
    "3": ("sll $t0, $v0, 1", "nop"),
    "4": ("sll $t0, $v0, 1", "sll $v0, $v0, 1"),
}
EXP_MULT = "2.5"
# Gold: the three words after "jal FXP_GetMonsterGold" load the running
# total and add the monster's gold.  The original spends two lui's on the
# same base; one is enough, which leaves a slot for the multiplier.
GOLD_SITES = [0x80042430, 0x800424C8, 0x80042560]
GOLD_PRESETS = {"1": "nop", "2": "sll $v0, $v0, 1", "4": "sll $v0, $v0, 2"}
GOLD_MULT = "2"
SMOOTH = False

# --- 5. Rebalance: random encounters with a grace period ---
# The earlier patch replaced the per-step roll at 0x8006E040 with "battle
# once 70 steps have passed" ($s5 = steps since last battle).  Restore the
# original roll against the area's rate ($t6 = 1..100 roll, $s1 = rate) and
# keep only a short grace period after each fight.
GRACE_STEPS = 25
ENCOUNTER_AT = 0x8006E040
NO_BATTLE = 0x8006ED98


# --- 7. Vanilla curse flag ---
# Reunion changes the setter for status bit 1 of a character record (byte
# 0x44) to store into byte 7 instead, the last byte of the 8-byte name, so
# the bit is never set for anyone (its "Samson is not cursed by Ramue").
# Put the original store back so the curse works as in the original game.
CURSE_STORE_AT = 0x80073B80


# --- 6. Faster walk-up in battle ---
# Battle actors are updated at 30 Hz on a stack copy (0x8001E208 loop); the
# walk-up is state 0x140.  Its setup (jump table 0x800C51D8, by attack type)
# sets velocity = distance / N, and the per-type handler (table 0x800C5218)
# sets $s5 = updates spent walking and $s1 = total updates for the action.
# The plain melee attack (types 0, 12, 13, 14) walks 12 updates at d/14 and
# ends at 17.  Walking 6 updates at d/7 covers the same distance and keeps
# the 5 updates after the walk (swing, hit) unchanged, so it ends at 11.
# Types 4 and 9 share the d/14 setup but walk only 5 updates; they are moved
# to type 10's identical d/14 setup so they keep their original motion.
APPROACH_DIV_AT = 0x800228D8          # addiu $v0, $zero, 14
APPROACH_TABLE = 0x800C51D8
APPROACH_KEEP_TYPES = (4, 9)
APPROACH_KEEP_SETUP = 0x80022B48      # identical d/14 setup (type 10)
MELEE_TIMING = (0x80022C98, 0x80022CA4)   # addiu $s5,12 / b / addiu $s1,17


# Run tuning.  With friction f (x/256 per update) and accel multiplier M,
# top speed is M*(1-f)/f times walking speed (walking uses f = 1/2), and
# the higher f the quicker it gets there.  Field logic runs at 30 Hz, so the
# screen scrolls in steps of 4 px walking; 8 px steps (2x) judder visibly.
RUN_PRESETS = {
    # (player run accel from $s0, run friction, follower walk accel,
    #  follower run accel).  Steady speed with friction f is accel*(1-f)/f:
    # f = 7/8 -> accel/7, f = 3/4 -> accel/3.  Walking is 0x400 (4 px).
    # Followers move tile by tile and restart from rest at each tile, so the
    # first update is only (1-f) of top speed.  At a run they are given a
    # little extra top speed, so three updates pass the 24 px tile and the
    # game's "passed the target" snap ends it, instead of a 1 px fourth
    # update that showed as a hitch every tile.
    # 2x: M = 14 (16s - 2s) -> 8 px; followers 0x1C00/7 = 4 px, 0x3B80/7 = 8.5 px
    "2x": ("sll $t5, $s0, 4; sll $t4, $s0, 1; subu $s0, $t5, $t4", 0xE0, 0x1C00, 0x3B80),
    # 1.5x: M = 4.5 (4s + s/2) -> 6 px; followers 0xC00/3 = 4 px, 0x1380/3 = 6.5 px
    "1.5x": ("sll $t5, $s0, 2; srl $t4, $s0, 1; addu $s0, $t5, $t4", 0xC0, 0x0C00, 0x1380),
}
RUN_SPEED = "2x"


# 0x80089650: beqz $t6, 0x800896f4 -> retarget to the new friction label.
BRANCH_AT = 0x80089650


def assemble(src, addr):
    enc, _ = ks.asm(".set noreorder\n" + src, addr)
    return bytes(enc)


def beqz_t6(at, target):
    """beq $t6, $zero, target (hand-encoded: keystone mis-handles absolute targets)."""
    off = ((target - (at + 4)) >> 2) & 0xFFFF
    return struct.pack("<I", (4 << 26) | (14 << 21) | off)


def branch(op, rs, at, target, rt=0):
    off = ((target - (at + 4)) >> 2) & 0xFFFF
    return struct.pack("<I", (op << 26) | (rs << 21) | (rt << 16) | off)


BEQ, BNE, AT_REG, T6, S1, S5 = 4, 5, 1, 14, 17, 21


def label_addr(src, addr, label):
    head = src.split(label + ":")[0]
    return addr + len(assemble(head, addr)) if head.strip() else addr


def patch_region(exe, base, start, end, code):
    room = end - start
    assert len(code) <= room, f"{hex(start)}: {len(code)} > {room} bytes"
    nop_fill = code + b"\0" * (room - len(code))
    off = start - base
    exe[off:off + room] = nop_fill
    return len(code) // 4, room // 4


def phys_source(helper):
    accel, fric, fwalk, frun = RUN_PRESETS[RUN_SPEED]
    a1, a2, a3 = accel.split("; ")
    return (PHYS.replace("HELPER", hex(helper))
                .replace("RUN_ACCEL_1", a1).replace("RUN_ACCEL_2", a2)
                .replace("RUN_ACCEL_3", a3)
                .replace("RUN_FRICTION", hex(fric))
                .replace("FOLLOW_WALK", hex(fwalk))
                .replace("FOLLOW_RUN_ADD", hex(frun - fwalk)))


# Save anywhere: SELECT on the field calls the church's save routine.
SAVE_ANYWHERE = True
SAVE_ROUTINE = 0x8006877C           # "record your journey": slot choice, confirm, card write
SAVE_CAVE = 0x8003BF58              # dead function (nothing on the disc calls it), 176 words
SELECT_HOOK = 0x8008F234            # field loop: "sb $zero, SELECT flag", runs only when SELECT was pressed
MENU_WINDOW_H = 0x80053390         # field menu window: "addiu $a3, $zero, 11" (height: 5 items)
MENU_PREPARE_ITEM = 0x8005345C     # field menu: "jal 0x80047330" writing "Prepare" on row 8
MENU_RANGE_CHECK = 0x8004F4BC      # field menu dispatch: "beqz $at, 0x8004F568" (choice past the table)
MENU_LOOP_END = 0x8004F568
SAVE_CODE = f"""
# SELECT on the field: halt the player the way the field menu does (halt
# script 0x800CDDE8, then let it reach its wait op), or the d-pad walks him
# around behind the save screen; save; give control back
select:
    addiu $sp, $sp, -24
    sw    $ra, 16($sp)
    lui   $a0, 0x800d
    lh    $a0, -0x2248($a0)
    lui   $a1, 0x800d
    jal   0x8008d6d8
    addiu $a1, $a1, -0x2218
    lui   $a0, 0x800d
    lh    $a0, -0x2248($a0)
    nop
    jal   0x800866b4
    nop
    jal   core
    nop
    lui   $a0, 0x800d
    lh    $a0, -0x2248($a0)
    nop
    jal   0x800877dc
    nop
    lui   $at, 0x8010
    sb    $zero, -0x190d($at)
    lw    $ra, 16($sp)
    lui   $t7, 0x800d
    lw    $t7, -0x6f44($t7)
    lui   $t8, 0x8010
    jr    $ra
    addiu $sp, $sp, 24
# the save itself, then as the church does: message 0 closes the message
# window, the text-sound flag 0x800CC214 goes back to 0
core:
    addiu $sp, $sp, -24
    sw    $ra, 16($sp)
    jal   entry
    nop
    jal   0x80069e10
    move  $a0, $zero
    lui   $at, 0x800d
    sh    $zero, -0x3dec($at)
    lw    $ra, 16($sp)
    nop
    jr    $ra
    addiu $sp, $sp, 24
# field menu: a choice past the jump table lands here ($s2 = choice).
# "Save" (5): save, then leave the menu with nothing for the field loop to do
menu:
    addiu $at, $zero, 5
    bne   $s2, $at, menu_out
    nop
    jal   core
    nop
    move  $s0, $zero
    move  $s4, $zero
menu_out:
    j     {MENU_LOOP_END:#x}
    nop
# in place of the menu's "Prepare" line: write it, then "Save" on row 10
items:
    addiu $sp, $sp, -32
    sw    $ra, 24($sp)
    sw    $a0, 28($sp)
    jal   0x80047330
    sw    $zero, 16($sp)
    lw    $a0, 28($sp)
    addiu $a1, $zero, 1
    addiu $a2, $zero, 10
    lui   $a3, STR_HI
    addiu $a3, $a3, STR_LO
    jal   0x80047330
    sw    $zero, 16($sp)
    lw    $ra, 24($sp)
    nop
    jr    $ra
    addiu $sp, $sp, 32
# the save routine's own prologue, then into it after its first line (the
# priest's "Let me find my Book of Journeys!"): it asks "Do you wish for me
# to inscribe your adventure?" (Yes/No) and goes on as in a church
entry:
    addiu $sp, $sp, -0x188
    sw    $ra, 0x1c($sp)
    addiu $t6, $zero, 1
    sw    $s0, 0x18($sp)
    sh    $t6, 0x176($sp)
    addiu $a0, $zero, 2
    jal   0x8004bea8
    addiu $a1, $zero, 1
    j     {SAVE_ROUTINE + 0x28:#x}
    nop
"""
SAVE_ITEM_TEXT = b"Save" + bytes(4)   # NUL-terminated, word-aligned


def hi_lo(addr):
    lo = addr & 0xFFFF
    if lo >= 0x8000:
        lo -= 0x10000
    return (addr - lo) >> 16, lo


def assemble_labeled(src, addr):
    """Assemble src at addr; "jal/j label" get absolute targets first (keystone
    resolves those unreliably), branches keep their labels.  Returns
    (code, labels)."""
    import re
    lines = [l.split("#")[0].rstrip() for l in src.splitlines()]
    lines = [l for l in lines if l.strip()]
    labels, n = {}, 0
    for l in lines:
        if l.strip().endswith(":"):
            labels[l.strip()[:-1]] = addr + 4 * n
        else:
            n += 1
    out = []
    for l in lines:
        m = re.fullmatch(r"\s*(jal|j)\s+([A-Za-z_]\w*)\s*", l)
        out.append(f"    {m.group(1)} {labels[m.group(2)]:#x}" if m else l)
    code = assemble(chr(10).join(out), addr)
    assert len(code) == 4 * n, (len(code) // 4, n)
    return code, labels


# --- 9. In-game switches for the patch: Prepare > Setting > Extras ---
# Bits nothing in the game uses, in the settings word 0x80103878 (saved
# with the game; every writer masks around them, no reader looks at them,
# and they are 0 in saves made by the original game):
#   0x80103879 bits 5-6  random battles: 0 = 100% (this patch: area rate,
#                        25-step grace), 1 = 200% (the original game: no
#                        grace), 2 = off, 3 = 50% (50-step grace, half rate)
#   0x80103879 bit 7     EXP boost off
#   0x8010387B bit 7     gold boost off (bit 15 of the halfword at 0x8010387A,
#                        which its writers keep and its readers mask off)
# 0 everywhere means the patch as built, so older saves and new games start
# with everything on.
OPTIONS = True
OPTIONS_CAVE = 0x800B4E50           # dead function (nothing on the disc calls it), 234 words
OPTIONS_SLOT = 18                   # UI window slot nobody uses (Setting is 17, its On/Off popup 19)
SETTING_WINDOW_Y = 0x8005871C       # Setting window: "addiu $a1, $zero, 0x12" (row 18)
SETTING_WINDOW_H = 0x80058724       # Setting window: "addiu $a3, $zero, 9" (title + 3 items)
SETTING_WINDOW_ITEM = 0x80058844    # Setting window: "jal 0x80047330" writing "Window" on row 6
SETTING_DEFAULT = 0x800521E8        # Setting dispatch: "b 0x80052288" (choice past Message/Battle/Window)
SETTING_LOOP = 0x80052284           # "sll $a1, $fp, 16" then the loop tail at 0x80052288
OPTIONS_CODE = f"""
# random encounter check (in place of the grace/roll block at 0x8006E040):
# $at = 1 for a battle.  Roll $t6 (1-100) against the area rate $s1, $s5 =
# steps since the last battle; $t8/$t9 are scratch here
enc_gate:
    lui   $t9, 0x8010
    lbu   $t9, 0x3879($t9)
    nop
    srl   $t9, $t9, 5
    andi  $t9, $t9, 3
    addiu $at, $zero, 2
    beq   $t9, $at, eg_no
    addiu $at, $zero, 1
    beq   $t9, $at, eg_roll
    move  $t8, $s1
    slti  $at, $s5, GRACE
    beqz  $t9, eg_grace
    nop
    slti  $at, $s5, GRACE2
    srl   $t8, $s1, 1
eg_grace:
    bnez  $at, eg_no
    nop
eg_roll:
    jr    $ra
    slt   $at, $t6, $t8
eg_no:
    jr    $ra
    move  $at, $zero
# enemy-defeat EXP (in place of the two multiplier ops): $t0 = extra EXP,
# $v0 = base EXP, as the ops leave them; uses $t2 (free until the mflo)
exp_gate:
    lui   $t2, 0x8010
    lbu   $t2, 0x3879($t2)
    nop
    andi  $t2, $t2, 0x80
    bnez  $t2, xg_off
    move  $t0, $zero
    EXP_OP_1
    EXP_OP_2
xg_off:
    jr    $ra
    nop
# enemy-defeat gold (the jal's delay slot loads the running total into $t6):
# $v0 = the monster's gold, multiplied when on; uses $t7
gold_gate:
    lui   $t7, 0x8010
    lbu   $t7, 0x387b($t7)
    nop
    andi  $t7, $t7, 0x80
    bnez  $t7, gg_off
    nop
    GOLD_OP
gg_off:
    jr    $ra
    nop
# Setting window: in place of the "Window" line, write it, then "Extras"
set_items:
    addiu $sp, $sp, -32
    sw    $ra, 24($sp)
    sw    $a0, 28($sp)
    jal   0x80047330
    sw    $zero, 16($sp)
    lw    $a0, 28($sp)
    addiu $a1, $zero, 1
    addiu $a2, $zero, 8
    lui   $a3, STR_EXTRAS_HI
    addiu $a3, $a3, STR_EXTRAS_LO
    jal   0x80047330
    sw    $zero, 16($sp)
    lw    $ra, 24($sp)
    nop
    jr    $ra
    addiu $sp, $sp, 32
# Setting dispatch: a choice past Message/Battle/Window lands here ($s0)
set_choice:
    addiu $at, $zero, 3
    bne   $s0, $at, sc_back
    nop
    jal   extras
    nop
sc_back:
    j     {SETTING_LOOP:#x}
    nop
# the Extras window: title and three "label  value" lines; confirming a
# line steps its value (battles: Off, 50%, 100%, 200%; boosts: On/Off) and
# redraws it, cancel closes the window
extras:
    addiu $sp, $sp, -40
    sw    $ra, 32($sp)
    sw    $s0, 28($sp)
    addiu $a0, $zero, 16
    addiu $a1, $zero, 13
    addiu $a2, $zero, 17
    addiu $a3, $zero, 9
    sw    $zero, 16($sp)
    jal   0x8004673c
    sw    $zero, 20($sp)
    lui   $at, 0x800d
    sh    $v0, SLOT_LO($at)
    move  $s0, $zero
ex_loop:
    jal   ex_draw
    nop
    addiu $a0, $zero, {OPTIONS_SLOT}
    move  $a1, $s0
    jal   0x8004c878
    addiu $a2, $zero, 1
    bltz  $v0, ex_done
    move  $s0, $v0
    lui   $at, 0x8010
    beqz  $s0, ex_battles
    addiu $t0, $zero, 1
    bne   $s0, $t0, ex_gold
    nop
    lbu   $t1, 0x3879($at)
    nop
    xori  $t1, $t1, 0x80
    b     ex_loop
    sb    $t1, 0x3879($at)
ex_gold:
    lbu   $t1, 0x387b($at)
    nop
    xori  $t1, $t1, 0x80
    b     ex_loop
    sb    $t1, 0x387b($at)
ex_battles:
    lbu   $t1, 0x3879($at)
    nop
    andi  $t2, $t1, 0x60
    addiu $t2, $t2, 0x20
    andi  $t2, $t2, 0x60
    andi  $t1, $t1, 0x9f
    or    $t1, $t1, $t2
    b     ex_loop
    sb    $t1, 0x3879($at)
ex_done:
    addiu $a0, $zero, {OPTIONS_SLOT}
    jal   0x8004bea8
    addiu $a1, $zero, 1
    lw    $ra, 32($sp)
    lw    $s0, 28($sp)
    jr    $ra
    addiu $sp, $sp, 40
ex_draw:
    addiu $sp, $sp, -40
    sw    $ra, 32($sp)
    sw    $s1, 28($sp)
    lui   $a0, 0x800d
    lh    $a0, SLOT_LO($a0)
    addiu $a1, $zero, 1
    move  $a2, $zero
    lui   $a3, STR_EXTRAS_HI
    addiu $a3, $a3, STR_EXTRAS_LO
    jal   0x80047330
    sw    $zero, 16($sp)
    move  $s1, $zero
ed_line:
    lui   $a0, 0x800d
    lh    $a0, SLOT_LO($a0)
    addiu $a1, $zero, 1
    sll   $a2, $s1, 1
    addiu $a2, $a2, 2
    sll   $t0, $s1, 2
    sll   $t1, $s1, 3
    addu  $t0, $t0, $t1
    lui   $a3, STR_LABELS_HI
    addiu $a3, $a3, STR_LABELS_LO
    addu  $a3, $a3, $t0
    jal   0x80047330
    sw    $zero, 16($sp)
    lui   $t0, 0x8010
    bnez  $s1, ed_bit
    lbu   $t1, 0x3879($t0)
    nop
    srl   $t1, $t1, 5
    andi  $t1, $t1, 3
    sll   $t2, $t1, 2
    addu  $t2, $t2, $t1
    lui   $a3, STR_RATES_HI
    addiu $a3, $a3, STR_RATES_LO
    b     ed_val
    addu  $a3, $a3, $t2
ed_bit:
    addiu $t2, $zero, 1
    bne   $s1, $t2, ed_gold
    nop
    b     ed_test
    andi  $t1, $t1, 0x80
ed_gold:
    lbu   $t1, 0x387b($t0)
    nop
    andi  $t1, $t1, 0x80
ed_test:
    lui   $a3, STR_ON_HI
    bnez  $t1, ed_off
    addiu $a3, $a3, STR_ON_LO
    b     ed_val
    nop
ed_off:
    lui   $a3, STR_OFF_HI
    addiu $a3, $a3, STR_OFF_LO
ed_val:
    lui   $a0, 0x800d
    lh    $a0, SLOT_LO($a0)
    addiu $a1, $zero, 12
    sll   $a2, $s1, 1
    addiu $a2, $a2, 2
    jal   0x80047330
    sw    $zero, 16($sp)
    addiu $s1, $s1, 1
    slti  $t0, $s1, 3
    bnez  $t0, ed_line
    nop
    lw    $ra, 32($sp)
    lw    $s1, 28($sp)
    jr    $ra
    addiu $sp, $sp, 40
"""
# strings after the code: label rows are 12 bytes apart
OPTIONS_STRINGS = [("STR_EXTRAS", b"Extras" + bytes(2)),
                   ("STR_LABELS", b"Battles" + bytes(5) + b"EXP Boost" + bytes(3) + b"Gold Boost" + bytes(2)),
                   ("STR_ON", b"On  " + bytes(4)), ("STR_OFF", b"Off " + bytes(4)),
                   # battle rate by setting value (0-3), 5 bytes apart
                   ("STR_RATES", b"100%" + bytes(1) + b"200%" + bytes(1) + b"Off " + bytes(1) + b"50% " + bytes(1))]


def build_options(exp_ops, gold_op):
    """Assemble OPTIONS_CODE with its strings; returns (bytes, labels)."""
    n_words = len([l for l in OPTIONS_CODE.splitlines()
                   if l.split("#")[0].strip() and not l.split("#")[0].strip().endswith(":")])
    addr = OPTIONS_CAVE + 4 * n_words
    src = (OPTIONS_CODE.replace("EXP_OP_1", exp_ops[0]).replace("EXP_OP_2", exp_ops[1])
           .replace("GOLD_OP", gold_op).replace("GRACE2", str(2 * GRACE_STEPS)).replace("GRACE", str(GRACE_STEPS))
           .replace("SLOT_LO", str(0x800CBB40 + 2 * OPTIONS_SLOT - 0x800D0000)))
    blob = b""
    for name, text in OPTIONS_STRINGS:
        h, l = hi_lo(addr + len(blob))
        src = src.replace(name + "_HI", hex(h)).replace(name + "_LO", str(l))
        blob += text
    code, labels = assemble_labeled(src, OPTIONS_CAVE)
    code += blob
    assert len(code) <= 234 * 4, len(code) // 4
    return code, labels


def main(src_bin, out_bin):
    disc = Disc(src_bin)
    exe = bytearray(disc.read_file(EXE_NAME))
    base = struct.unpack_from("<I", exe, 0x18)[0] - 0x800

    reunion = exe[0x80042404 - base:0x80042408 - base] == struct.pack("<I", 0x00021080)
    print("base:", "Reunion" if reunion else "original")

    # Sanity: make sure we are patching the expected build.
    assert exe[0x80089650 - base:0x80089654 - base] == beqz_t6(0x80089650, 0x800896f4)
    assert exe[0x80011350 - base:0x80011354 - base] == struct.pack("<I", (3 << 26) | (0x800C21A8 >> 2 & 0x3FFFFFF))

    code = bytearray(assemble(INPUT, INPUT_START))
    code[0:4] = exe[INPUT_START - base:INPUT_START - base + 4]  # keep the original jal PadRead
    # the "nop" before the last store becomes "b <pad 2 block>", so the
    # routine skips over the helper placed behind it
    br_at = INPUT_START + len(code) - 8
    code[-8:-4] = branch(BEQ, 0, br_at, INPUT_END)
    helper = INPUT_START + len(code)
    code += assemble(PREV_OP_HELPER, helper)
    used, room = patch_region(exe, base, INPUT_START, INPUT_END, bytes(code))
    print(f"input routine: {used}/{room} words")
    used, room = patch_region(exe, base, PHYS_START, PHYS_END, assemble(phys_source(helper), PHYS_START))
    print(f"physics:       {used}/{room} words")

    fr = label_addr(phys_source(helper), PHYS_START, "friction")
    off = BRANCH_AT - base
    exe[off:off + 4] = beqz_t6(BRANCH_AT, fr)
    # its delay slot (a nop) clears the run flag, so objects that are not
    # walking always get their normal friction
    assert exe[off + 4:off + 8] == bytes(4)
    exe[off + 4:off + 8] = assemble("move $a1, $zero", 0)
    print(f"branch 0x80089650 -> {hex(fr)}")

    exp_1, exp_2 = EXP_PRESETS[EXP_MULT]
    if OPTIONS:
        opt_code, opt_labels = build_options((exp_1, exp_2), GOLD_PRESETS[GOLD_MULT])
        o = OPTIONS_CAVE - base
        assert exe[o:o + 4] == assemble("addiu $sp, $sp, -0x40", 0), "0x800B4E50 is not the expected dead function"
        exe[o:o + len(opt_code)] = opt_code
        exp_1, exp_2 = f"jal {opt_labels['exp_gate']:#x}", "nop"
    reward = REWARD.replace("EXP_OP_1", exp_1).replace("EXP_OP_2", exp_2)
    for blk in REWARD_BLOCKS:
        # 4th word: "lui $at" in the original, Reunion's "sll $v0,$v0,2"
        assert exe[blk + 12 - base:blk + 16 - base] in (
            assemble("lui $at, 0x8010", 0), struct.pack("<I", 0x00021080)), hex(blk)
        # ...and the block ends in "sll $t4,$a0,16 / jal gold / sra $a0,$t4,16"
        assert exe[blk + 48 - base:blk + 52 - base] == struct.pack("<I", (3 << 26) | (0x80072670 >> 2 & 0x3FFFFFF)), hex(blk)
        code = assemble(reward, blk)
        assert len(code) == 56
        exe[blk - base:blk - base + 56] = code
    for site in GOLD_SITES:
        o = site - base
        assert exe[o + 12:o + 20] == assemble("addu $t7, $t6, $v0\nsw $t7, -0x64f4($at)", 0), hex(site)
        if OPTIONS:
            # the jal's delay slot loads the total; the gate multiplies $v0
            exe[o:o + 4] = assemble("lui $at, 0x8010", site)
            exe[o + 4:o + 8] = struct.pack("<I", (3 << 26) | (opt_labels["gold_gate"] >> 2 & 0x3FFFFFF))
            exe[o + 8:o + 12] = assemble("lw $t6, -0x64f4($at)", site + 8)
        else:
            exe[o:o + 12] = assemble("lui $at, 0x8010\nlw $t6, -0x64f4($at)\n" + GOLD_PRESETS[GOLD_MULT], site)
    print(f"rewards: EXP {EXP_MULT}x, gold {GOLD_MULT}x")

    e = ENCOUNTER_AT - base
    assert exe[e:e + 4] in (assemble("slti $at, $s5, 0x46", ENCOUNTER_AT),   # Reunion
                            assemble("slt $at, $t6, $s1", ENCOUNTER_AT))     # original
    if OPTIONS:
        exe[e:e + 20] = b"".join([
            struct.pack("<I", (3 << 26) | (opt_labels["enc_gate"] >> 2 & 0x3FFFFFF)),
            assemble("move $v0, $zero", 0),
            branch(BEQ, AT_REG, ENCOUNTER_AT + 8, NO_BATTLE),
            assemble("nop", 0),
            assemble("nop", 0),
        ])
    else:
        exe[e:e + 20] = b"".join([
            assemble(f"slti $at, $s5, {GRACE_STEPS}", ENCOUNTER_AT),
            branch(BNE, AT_REG, ENCOUNTER_AT + 4, NO_BATTLE),
            assemble("move $v0, $zero", 0),
            assemble("slt $at, $t6, $s1", 0),
            branch(BEQ, AT_REG, ENCOUNTER_AT + 16, NO_BATTLE),
        ])
    print(f"encounters: original roll, {GRACE_STEPS}-step grace period")

    o = APPROACH_DIV_AT - base
    assert exe[o:o + 4] == assemble("addiu $v0, $zero, 14", 0)
    exe[o:o + 4] = assemble("addiu $v0, $zero, 7", 0)
    for t in APPROACH_KEEP_TYPES:
        o = APPROACH_TABLE + 4 * t - base
        assert struct.unpack_from("<I", exe, o)[0] == APPROACH_DIV_AT
        struct.pack_into("<I", exe, o, APPROACH_KEEP_SETUP)
    for blk in MELEE_TIMING:
        o = blk - base
        assert exe[o:o + 4] == assemble("addiu $s5, $zero, 12", 0)
        assert exe[o + 8:o + 12] == assemble("addiu $s1, $zero, 17", 0)
        exe[o:o + 4] = assemble("addiu $s5, $zero, 6", 0)
        exe[o + 8:o + 12] = assemble("addiu $s1, $zero, 11", 0)
    print("battle walk-up: melee 12 -> 6 updates")

    o = CURSE_STORE_AT - base
    vanilla_store = assemble("sb $t9, 0x44($a2)", 0)
    if exe[o:o + 4] == assemble("sb $t9, 7($a2)", 0):
        exe[o:o + 4] = vanilla_store
        print("curse flag: Reunion's change reverted")
    assert exe[o:o + 4] == vanilla_store

    if OPTIONS:
        # two rows taller for "Extras", and two rows higher to stay on screen
        o = SETTING_WINDOW_Y - base
        assert exe[o:o + 4] == assemble("addiu $a1, $zero, 0x12", 0)
        exe[o:o + 4] = assemble("addiu $a1, $zero, 0x10", 0)
        o = SETTING_WINDOW_H - base
        assert exe[o:o + 4] == assemble("addiu $a3, $zero, 9", 0)
        exe[o:o + 4] = assemble("addiu $a3, $zero, 11", 0)
        o = SETTING_WINDOW_ITEM - base
        assert exe[o:o + 4] == struct.pack("<I", (3 << 26) | (0x80047330 >> 2 & 0x3FFFFFF))
        exe[o:o + 4] = struct.pack("<I", (3 << 26) | (opt_labels["set_items"] >> 2 & 0x3FFFFFF))
        o = SETTING_DEFAULT - base
        assert exe[o:o + 4] == branch(BEQ, 0, SETTING_DEFAULT, 0x80052288)
        exe[o:o + 4] = struct.pack("<I", (2 << 26) | (opt_labels["set_choice"] >> 2 & 0x3FFFFFF))
        print(f"options: Setting > Extras (battles Off/50/100/200%, EXP boost, gold boost), {len(opt_code) // 4} words at {hex(OPTIONS_CAVE)}")

    if SAVE_ANYWHERE:
        # Save anywhere: a "Save" item in the field menu, and SELECT on the
        # field (its pressed-flag 0x800FE6F3 is set and cleared by the field
        # loop but otherwise unused).  Both run the church's "record your
        # journey" routine; the field loop and menu run on the main thread,
        # where the blocking save screen is safe.
        o = SAVE_CAVE - base
        assert exe[o:o + 4] == assemble("addiu $sp, $sp, -0x48", 0), "0x8003BF58 is not the expected dead function"
        n_words = len([l for l in SAVE_CODE.splitlines() if l.split("#")[0].strip() and not l.strip().endswith(":")])
        text_at = SAVE_CAVE + 4 * n_words
        src = SAVE_CODE.replace("STR_HI", hex(hi_lo(text_at)[0])).replace("STR_LO", str(hi_lo(text_at)[1]))
        code, labels = assemble_labeled(src, SAVE_CAVE)
        code += SAVE_ITEM_TEXT
        assert len(code) <= 176 * 4
        exe[o:o + len(code)] = code
        o = SELECT_HOOK - base
        assert exe[o:o + 8] == assemble("sb $zero, -0x190d($at)" + chr(10) + "lw $t7, -0x6f44($t7)", 0)
        exe[o:o + 4] = struct.pack("<I", (3 << 26) | (labels["select"] >> 2 & 0x3FFFFFF))
        o = MENU_WINDOW_H - base
        assert exe[o:o + 4] == assemble("addiu $a3, $zero, 0xb", 0)
        exe[o:o + 4] = assemble("addiu $a3, $zero, 0xd", 0)
        o = MENU_PREPARE_ITEM - base
        assert exe[o:o + 4] == struct.pack("<I", (3 << 26) | (0x80047330 >> 2 & 0x3FFFFFF))
        exe[o:o + 4] = struct.pack("<I", (3 << 26) | (labels["items"] >> 2 & 0x3FFFFFF))
        o = MENU_RANGE_CHECK - base
        assert exe[o:o + 4] == branch(BEQ, AT_REG, MENU_RANGE_CHECK, MENU_LOOP_END)
        exe[o:o + 4] = branch(BEQ, AT_REG, MENU_RANGE_CHECK, labels["menu"])
        print(f"save anywhere: field menu \"Save\" and SELECT ({len(code) // 4} words at {hex(SAVE_CAVE)})")

    if SMOOTH:
        import interp60
        words = interp60.apply(exe, base, assemble, branch, BEQ)
        print(f"60 Hz presentation: {words} words at {hex(interp60.CAVE)} and {hex(interp60.CAVE2)}")

    vp_to_hp(exe, [a - base for a in VP_EXE])
    resius = bytearray(disc.read_file(r"SYSTEM\RESIUS.DAT"))
    vp_to_hp(resius, VP_RESIUS)
    disc.write_file(r"SYSTEM\RESIUS.DAT", bytes(resius))
    print(f"VP->HP: {len(VP_EXE)} exe labels, {len(VP_RESIUS)} RESIUS names")

    disc.write_file(EXE_NAME, bytes(exe))
    disc.save(out_bin)
    open(out_bin.rsplit(".", 1)[0] + ".exe", "wb").write(exe)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build the modernized Beyond the Beyond disc.")
    ap.add_argument("src", help="MODE2/2352 .bin: original dump or Reunion 1.4")
    ap.add_argument("out", help="output .bin")
    ap.add_argument("--run", choices=sorted(RUN_PRESETS), default=RUN_SPEED)
    ap.add_argument("--exp", choices=sorted(EXP_PRESETS, key=float), default=EXP_MULT)
    ap.add_argument("--gold", choices=sorted(GOLD_PRESETS, key=float), default=GOLD_MULT)
    ap.add_argument("--smooth", action="store_true", help="60 Hz presentation (experimental)")
    ap.add_argument("--no-save-anywhere", action="store_true", help="no Save in the field menu / SELECT save")
    ap.add_argument("--no-options", action="store_true", help="no Setting > Extras switches (features always on)")
    args = ap.parse_args()
    RUN_SPEED, EXP_MULT, GOLD_MULT, SMOOTH = args.run, args.exp, args.gold, args.smooth
    SAVE_ANYWHERE = not args.no_save_anywhere
    OPTIONS = not args.no_options
    print(f"run speed: {RUN_SPEED}")
    main(args.src, args.out)
