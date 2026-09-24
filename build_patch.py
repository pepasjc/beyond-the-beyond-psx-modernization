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

8. Save anywhere: SELECT on the field (unused in the original) halts the
   player like the field menu does, runs the church's "record your journey"
   routine from its Yes/No question on, then closes the message window and
   gives control back (see SAVE_WRAPPER).  --no-save-anywhere turns it off.
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
SAVE_WRAPPER = f"""
    addiu $sp, $sp, -24
    sw    $ra, 16($sp)
    # halt the player the way the field menu does (halt script 0x800CDDE8,
    # then let it reach its wait op), or the d-pad walks him around behind
    # the save screen
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
    jal   ENTRY
    nop
    # as the church does: message 0 closes the message window, the
    # text-sound flag 0x800CC214 goes back to 0; then player control back on
    jal   0x80069e10
    move  $a0, $zero
    lui   $at, 0x800d
    sh    $zero, -0x3dec($at)
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
    # the save routine's own prologue, then into it after its first line
    # (the priest's "Let me find my Book of Journeys!"): it asks "Do you wish
    # for me to inscribe your adventure?" (Yes/No) and goes on as in a church
ENTRY:
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
# (the hook replaces the flag clear; its delay slot "lw $t7" runs before the
# call, so the wrapper reloads $t7 and $t8, which the field loop uses next)


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
        exe[o:o + 12] = assemble("lui $at, 0x8010\nlw $t6, -0x64f4($at)\n" + GOLD_PRESETS[GOLD_MULT], site)
    print(f"rewards: EXP {EXP_MULT}x, gold {GOLD_MULT}x")

    e = ENCOUNTER_AT - base
    assert exe[e:e + 4] in (assemble("slti $at, $s5, 0x46", ENCOUNTER_AT),   # Reunion
                            assemble("slt $at, $t6, $s1", ENCOUNTER_AT))     # original
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

    if SAVE_ANYWHERE:
        # SELECT on the field (pressed-flag 0x800FE6F3, set and cleared by
        # the field loop but otherwise unused) opens the church's "record
        # your journey" routine.  The field loop runs on the main thread,
        # where the blocking save screen is safe.
        o = SAVE_CAVE - base
        assert exe[o:o + 4] == assemble("addiu $sp, $sp, -0x48", 0), "0x8003BF58 is not the expected dead function"
        lines = [l.split("#")[0].strip() for l in SAVE_WRAPPER.splitlines()]
        lines = [l for l in lines if l]
        entry = SAVE_CAVE + 4 * lines.index("ENTRY:")
        src = chr(10).join(l for l in lines if l != "ENTRY:").replace("jal   ENTRY", f"jal   {entry:#x}")
        code = assemble(src, SAVE_CAVE)
        assert len(code) == 4 * (len(lines) - 1)
        exe[o:o + len(code)] = code
        o = SELECT_HOOK - base
        assert exe[o:o + 8] == assemble("sb $zero, -0x190d($at)" + chr(10) + "lw $t7, -0x6f44($t7)", 0)
        exe[o:o + 4] = struct.pack("<I", (3 << 26) | (SAVE_CAVE >> 2 & 0x3FFFFFF))
        print(f"save anywhere: SELECT on the field ({len(code) // 4} words at {hex(SAVE_CAVE)})")

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
    ap.add_argument("--no-save-anywhere", action="store_true", help="no SELECT save on the field")
    args = ap.parse_args()
    RUN_SPEED, EXP_MULT, GOLD_MULT, SMOOTH = args.run, args.exp, args.gold, args.smooth
    SAVE_ANYWHERE = not args.no_save_anywhere
    print(f"run speed: {RUN_SPEED}")
    main(args.src, args.out)
