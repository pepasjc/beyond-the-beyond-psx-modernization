"""Beyond the Beyond (USA) SCUS_947.02 modernization patch.

    python build_patch.py <reunion.bin> <out.bin> [2x|1.5x]

Input is a MODE2/2352 .bin of Beyond the Beyond (USA) (CRC32 453917AF)
with "Beyond the Beyond - Reunion" 1.4 by Skiller and Shadow501 applied
(https://www.romhacking.net/hacks/9516/).  Reunion's other changes (stat
tables, dialog, battle graphics) are left untouched.  Changes, all in SCUS_947.02
except where noted:

1. Swap X and Triangle.  The game's per-frame input routine (0x80011350)
   stores pad 1 into held/pressed/repeat globals at 0x800C9070..80.  It is
   rewritten more compactly and swaps bit 4 (Triangle) with bit 6 (X) of
   the PadRead() result before anything else sees it.  Its leftover space
   holds the follower-check helper used by (2).  The secret-code reader at
   0x8007FE74 calls PadRead() directly and keeps raw buttons.

2. Run with Circle.  The map-object physics loop (0x800894CC, $s3 = object
   index, obj ptr in $t2) computes accel = obj[0x14]*obj[0x18]>>8 and
   integrates velocity with linear friction.  Running raises accel and
   friction together (see RUN_PRESETS) so the character reaches the faster
   top speed within one update instead of re-accelerating at every tile.
   It applies to the object whose index equals the player index at
   0x800CDDB8 and to party followers (objects running script opcode 0x25,
   "follow obj[0x11]"), only while Circle (0x20) is held.  Circle has no
   field function in the original game.  Inlining sin/cos (table at
   0x800CCD50) instead of calling them frees the space.

3. Rename VP to HP in menu labels and item/spell names (exe and
   SYSTEM\RESIUS.DAT).  Dialog (.TLK) is compressed and not touched.

4. Rebalance Reunion's rewards: EXP 2.5x (Reunion's code gives 4x),
   gold stays 4x, and Reunion's gold-lookup slip (a stale monster id in one
   of the two enemy-defeat paths) is fixed.

5. Random encounters: Reunion forces one battle every 70 steps.  The
   original per-step roll against the area's rate is back, with a 25-step
   grace period after each fight.

7. Followers (script opcode 0x25) always use the fast-response physics at
   the leader's speed (4 px walking, ~8 px running), so they glide behind
   the leader instead of rushing each tile at their own higher top speed
   and then waiting.  To make room, the velocity update rounds sub-pixel
   steps down (floor) instead of toward zero.

6. Faster walk-up in battle: the plain melee attack walks to the enemy in
   6 updates instead of 12 (same distance), leaving the swing untouched.
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


# --- 4. Rebalance: EXP 2.5x, gold 4x, gold-lookup bug fixed ---
# Enemy-defeat reward code, two copies (0x800423F8, 0x80042490), each ending
# in "jal FXP_GetMonsterGold".  The earlier patch added "sll $v0,$v0,2"
# before EXP is added to the battle total (0x80109B08).  2.5x
# (v*2 + v/2, rounded down) needs two more instructions: one from the
# load-delay nop after "lh $a0,0x12($t3)", one from the "sll/sra" pair that
# sign-extended the gold-lookup argument (FXP_GetMonsterGold sign-extends
# its own argument).  In the first copy the earlier patch also turned that
# lh into "lh $a1", so the gold lookup got a stale monster id; this restores
# $a0.  Gold (0x80109B0C) stays 4x.
REWARD_BLOCKS = [0x800423F8, 0x80042490]
REWARD = """
    lui   $at, 0x8010
    multu $s5, $s4
    lw    $t1, -0x64f8($at)
    sll   $t0, $v0, 1
    srl   $v0, $v0, 1
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

# --- 5. Rebalance: random encounters with a grace period ---
# The earlier patch replaced the per-step roll at 0x8006E040 with "battle
# once 70 steps have passed" ($s5 = steps since last battle).  Restore the
# original roll against the area's rate ($t6 = 1..100 roll, $s1 = rate) and
# keep only a short grace period after each fight.
GRACE_STEPS = 25
ENCOUNTER_AT = 0x8006E040
NO_BATTLE = 0x8006ED98


# --- 7. Followers (script opcode 0x25) always use the fast-response physics at
   the leader's speed (4 px walking, ~8 px running), so they glide behind
   the leader instead of rushing each tile at their own higher top speed
   and then waiting.  To make room, the velocity update rounds sub-pixel
   steps down (floor) instead of toward zero.

6. Faster walk-up in battle ---
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


def main(src_bin, out_bin):
    disc = Disc(src_bin)
    exe = bytearray(disc.read_file(EXE_NAME))
    base = struct.unpack_from("<I", exe, 0x18)[0] - 0x800

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

    for blk in REWARD_BLOCKS:
        # 4th word must be the earlier patch's "sll $v0,$v0,2"
        assert exe[blk + 12 - base:blk + 16 - base] == struct.pack("<I", 0x00021080), hex(blk)
        # ...and it must end in "sll $t4,$a0,16 / jal gold / sra $a0,$t4,16"
        assert exe[blk + 48 - base:blk + 52 - base] == struct.pack("<I", (3 << 26) | (0x80072670 >> 2 & 0x3FFFFFF)), hex(blk)
        code = assemble(REWARD, blk)
        assert len(code) == 56
        exe[blk - base:blk - base + 56] = code
    print("rewards: EXP 2.5x, gold 4x, gold lookup fixed")

    e = ENCOUNTER_AT - base
    assert exe[e:e + 4] == assemble("slti $at, $s5, 0x46", ENCOUNTER_AT)
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

    vp_to_hp(exe, [a - base for a in VP_EXE])
    resius = bytearray(disc.read_file(r"SYSTEM\RESIUS.DAT"))
    vp_to_hp(resius, VP_RESIUS)
    disc.write_file(r"SYSTEM\RESIUS.DAT", bytes(resius))
    print(f"VP->HP: {len(VP_EXE)} exe labels, {len(VP_RESIUS)} RESIUS names")

    disc.write_file(EXE_NAME, bytes(exe))
    disc.save(out_bin)
    open(out_bin.rsplit(".", 1)[0] + ".exe", "wb").write(exe)


if __name__ == "__main__":
    if len(sys.argv) > 3:
        RUN_SPEED = sys.argv[3]
    print(f"run speed: {RUN_SPEED}")
    main(sys.argv[1], sys.argv[2])
