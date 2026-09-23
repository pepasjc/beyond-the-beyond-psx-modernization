"""60 Hz presentation for Beyond the Beyond (work in progress, branch 60fps).

The game runs its logic and builds one picture per 30 Hz tick; the other
vblank draws nothing.  This module draws and shows a picture on every
vblank:

  tick vblank (parity bit set): on the field, draw the finished tick picture
      into the top half of VRAM (buffer 0's DRAWENV, y=8) and show the
      bottom half (buffer 0's DISPENV, y=240) -- always the same halves,
      instead of alternating with the double buffer.
  idle vblank: draw an in-between picture into the bottom half (buffer 1's
      DRAWENV, y=248) and show the top half (buffer 1's DISPENV, y=0).

So the screen shows P(t-1), mid(t-1,t), P(t), mid(t,t+1), ...

The in-between picture (field only, no window open): before each tick's
callbacks run, the camera layers' draw positions and every object's
position are saved (SAVEPREV, hooked in front of the callback dispatcher).
On the idle vblank the object array, camera layers and the globals the
drawing code touches are snapshotted; positions are set halfway between the
saved and the current value (a move of a tile or more in one tick -- map
changes, warps -- keeps the current value); the three map layers
(0x80084534, 0x80084600) and the sprites (0x80088D7C) are drawn into the
buffer the GPU finished with on the tick vblank; then everything is put
back.  Anywhere else (battle, menus, dialog, logos, loading) both vblanks
behave exactly as in the original: drawing on the idle vblank outside the
field hangs loaders (the display buffers are not set up there).

Space: the code lives in a function nothing on the disc calls or points to
(0x8009A670, 476 words); scratch RAM at 0x801F8000 (see SCRATCH).
The per-vblank handler's debug load-meter printout (0x80011648, only shown
with debug event flag 0x10) is dropped to make room for a trampoline.
"""
import re
import struct

DB0, DB1 = 0x800DB890, 0x800EA90C          # double-buffer structs
DRAWSYNC, PUTDISP, PUTDRAW, DRAWOTAG = 0x800ACAFC, 0x800AD130, 0x800AD040, 0x800ACFD8
CLEAROT = 0x800ACE58                        # ClearOTag(ot, n)
EXEQUE = 0x800AE928                         # libgpu: start the next queued transfer if DMA 2 is free
DISPATCH = 0x80010B54                       # 30 Hz callback dispatcher
LAYER_DRAW, MAP_FINISH, SPRITES = 0x80084534, 0x80084600, 0x80088D7C
FIELD_CBS = (0x80085EFC, 0x80086550, 0x80047684)
CAVE = 0x8009A670                           # dead function, 476 words
CAVE_WORDS = 476
CAVE2 = 0x800B4954                          # second dead function, 251 words:
CAVE2_WORDS = 251                           # blend_draw, save_prev
TRAMP = 0x80011650

# Scratch RAM: 0x801F7800..0x801FC000 is never written by the game (random
# soaks through towns, the world map, battles and menus): it lies between the
# highest fixed file load (a table at 0x801F3A00) and the deepest the stack
# goes (~0x801FC000).  0x801E4800.., used at first, is free in Marion town but
# holds map data elsewhere (files load at 0x801E2000 and 0x801E9800).
SCRATCH = 0x801F8000
PREV_LAYERS = SCRATCH                       # 3 x (x, y)
PREV_OBJS = SCRATCH + 0x20                  # 64 x (x, y)
SNAP_OBJS = SCRATCH + 0x220                 # 0x1C00
SNAP_LAYERS = SCRATCH + 0x1E20              # 0xF0
SNAP_G1 = SCRATCH + 0x1F10                  # 0x800CDD94, 0x18
SNAP_G2 = SCRATCH + 0x1F30                  # 0x800D0030, 0x1C
SNAP_CNT = SCRATCH + 0x1F50                 # 0x800CE040
assert SNAP_CNT + 4 <= 0x801FA000
JUMP = 0x1800                               # one tile: larger moves are not blended
# consecutive ticks of plain field play: the cave's last word, so nothing but
# this code can ever write it
STREAK = CAVE + 4 * (CAVE_WORDS - 1)
SHOWN = CAVE + 4 * (CAVE_WORDS - 2)         # half on screen (0 top, 1 bottom)
NEXT = CAVE + 4 * (CAVE_WORDS - 3)          # half with the newest finished picture
MID = CAVE + 4 * (CAVE_WORDS - 4)           # in-between picture in flight: half + 1
COOL = CAVE + 4 * (CAVE_WORDS - 5)          # ticks left without in-between pictures
FAILS = CAVE + 4 * (CAVE_WORDS - 6)         # misses on this map (cooldown doubles each)
DATA_WORDS = 6
WAIT_LIMIT = 8        # lines into the tick frame an in-between picture may still finish
SUBMIT_LIMIT = 200    # no in-between picture submitted this late in the idle frame
IDLE_LATE = 240       # the idle vblank's work ending this late counts as a miss
COOLDOWN = 30         # cooldown unit: a first miss pauses 30 << 1 ticks (2 s), up to 30 << 5 (32 s)
WARMUP = 45                                 # ticks before in-between pictures start


def jal(t):
    return struct.pack("<I", (3 << 26) | (t >> 2 & 0x3FFFFFF))


def hi_lo(addr):
    lo = addr & 0xFFFF
    if lo >= 0x8000:
        lo -= 0x10000
    return (addr - lo) >> 16, lo


def la(reg, addr):
    h, l = hi_lo(addr)
    return f"lui {reg}, {hex(h)}\n    addiu {reg}, {reg}, {l}"


CODE = """
# entry points at fixed offsets: +0 idle, +8 tick_env, +16 save_prev, +24 tick_pre
    j     idle
    nop
    j     tick_env
    nop
    j     save_prev
    nop
    j     tick_pre
    nop
# ---------------------------------------------------------------- idle vblank
# Show the tick picture (half NEXT) and draw an in-between picture into the
# other half -- but only when that costs the game nothing: the tick picture
# must already be finished (no waiting), no cooldown, and the drawing must
# end early enough in the frame for the GPU to finish it by the next vblank.
idle:
    addiu $sp, $sp, -40
    sw    $ra, 16($sp)
    sw    $s0, 20($sp)
    sw    $s1, 24($sp)
    sw    $s2, 28($sp)
    sw    $s3, 32($sp)
    jal   blend_ok
    nop
    beqz  $v0, idle_out
    move  $a0, $zero
    jal   settle
    move  $a1, $zero
    beqz  $v0, idle_out
    lui   $t0, 0x800d
    lw    $t1, -0xdc0($t0)
    lw    $t2, -0xdbc($t0)
    lui   $t3, 0x1f80
    bne   $t1, $t2, idle_out
    lw    $t4, 0x10a8($t3)
    lui   $t5, 0x0100
    and   $t4, $t4, $t5
    bnez  $t4, idle_out
    lw    $t4, 0x1814($t3)
    lui   $t5, 0x0400
    and   $t4, $t4, $t5
    beqz  $t4, idle_out
    nop
    # show half h = NEXT through DB(1-h)'s DISPENV (GP1 05, display start)
    {LA_T0_NEXT}
    lw    $t1, 0($t0)
    {LA_T2_SHOWN}
    sw    $t1, 0($t2)
    {LA_T3_DB1}
    beqz  $t1, id_disp
    nop
    {LA_T3_DB0}
id_disp:
    lhu   $t4, 0x5c($t3)
    lhu   $t5, 0x5e($t3)
    lui   $t6, 0x0500
    sll   $t5, $t5, 10
    or    $t6, $t6, $t5
    or    $t6, $t6, $t4
    lui   $t0, 0x1f80
    sw    $t6, 0x1814($t0)
    jal   can_blend
    nop
    beqz  $v0, idle_out
    nop
    {LA_T0_COOL}
    lw    $t1, 0($t0)
    nop
    bnez  $t1, idle_out
    # OT and packets: the buffer the tick picture came from (finished)
    lui   $s0, 0x8010
    lw    $s0, -0x6678($s0)
    {LA_T1_DB0}
    bne   $s0, $t1, other_db0
    nop
    {LA_S0_DB1}
    b     have_other
    nop
other_db0:
    move  $s0, $t1
have_other:
    jal   blend_draw
    nop
show:
    # Submit through libgpu like the tick picture (PutDrawEnv + DrawOTag),
    # queued behind the CLUT upload the sprite setup queued.  libgpu must
    # see every DMA 2 transfer: libetc hands each DMA 2 completion to it.
    # Too late in the frame for the GPU to finish: submit nothing.
    lui   $t0, 0x1f80
    lw    $t1, 0x1110($t0)
    nop
    andi  $t1, $t1, 0xffff
    slti  $t1, $t1, {SUBMIT_LIMIT}
    beqz  $t1, idle_out
    nop
    # draw half m = 1 - SHOWN with DB(m)'s DRAWENV
    {LA_T7_SHOWN}
    lw    $t7, 0($t7)
    {LA_A0_DB1}
    beqz  $t7, have_denv
    xori  $s1, $t7, 1
    {LA_A0_DB0}
have_denv:
    jal   {PUTDRAW}
    nop
    jal   {DRAWOTAG}
    addiu $a0, $s0, 0x70
    addiu $s1, $s1, 1
    {LA_T1_MID}
    sw    $s1, 0($t1)
    # the idle vblank's own work ran close to the next vblank: a miss
    lui   $t0, 0x1f80
    lw    $t1, 0x1110($t0)
    nop
    andi  $t1, $t1, 0xffff
    slti  $t1, $t1, {IDLE_LATE}
    bnez  $t1, idle_out
    nop
    jal   blend_fail
    nop
idle_out:
    lw    $ra, 16($sp)
    lw    $s0, 20($sp)
    lw    $s1, 24($sp)
    lw    $s2, 28($sp)
    lw    $s3, 32($sp)
    jr    $ra
    addiu $sp, $sp, 40

# ------------------------------------------- tick vblank, instead of DrawSync(0)
# An in-between picture still drawing at line WAIT_LIMIT of the tick frame
# is a miss: the tick waits for it (stopping DMA 2 half way through a list
# wedged libgpu's queue) and the in-between pictures pause (blend_fail).
tick_pre:
    addiu $sp, $sp, -24
    sw    $ra, 16($sp)
    jal   settle
    addiu $a0, $zero, {WAIT_LIMIT}
    bnez  $v0, tp_sync
    nop
    jal   blend_fail
    nop
    lui   $a0, 0x7fff
    jal   settle
    ori   $a0, $a0, 0xffff
tp_sync:
    lw    $ra, 16($sp)
    addiu $sp, $sp, 24
    j     {DRAWSYNC}
    move  $a0, $zero

# Settle the in-between picture in flight (MID = half + 1), if any: wait
# while it draws until line a0 of the frame (hblanks since the handler
# started), pumping libgpu's queue the way DrawSync does (the queue does not
# advance on interrupts alone; the world map queues far more than a town).
# Finished (queue empty, DMA 2 idle, GPU ready): its half is the newest
# picture.  v0 = 1 when nothing is in flight any more, 0 when still drawing.
settle:
    addiu $sp, $sp, -32
    sw    $ra, 16($sp)
    sw    $s0, 20($sp)
    sw    $s1, 24($sp)
    sw    $s2, 28($sp)
    move  $s0, $a0
    {LA_S1_MID}
    lw    $s2, 0($s1)
    nop
    beqz  $s2, st_yes
    nop
st_wait:
    jal   {EXEQUE}
    nop
    lui   $t7, 0x800d
    lw    $t4, -0xdc0($t7)
    lw    $t5, -0xdbc($t7)
    lui   $t2, 0x1f80
    lw    $t6, 0x10a8($t2)
    bne   $t4, $t5, st_busy
    lui   $t3, 0x0100
    and   $t6, $t6, $t3
    bnez  $t6, st_busy
    lui   $t6, 0x0400
    lw    $t5, 0x1814($t2)
    nop
    and   $t5, $t5, $t6
    bnez  $t5, st_done
    nop
st_busy:
    lui   $t2, 0x1f80
    lw    $t4, 0x1110($t2)
    nop
    andi  $t4, $t4, 0xffff
    slt   $t4, $t4, $s0
    bnez  $t4, st_wait
    nop
    b     st_out
    move  $v0, $zero
st_done:
    addiu $s2, $s2, -1
    {LA_T4_NEXT}
    sw    $s2, 0($t4)
    sw    $zero, 0($s1)
st_yes:
    addiu $v0, $zero, 1
st_out:
    lw    $ra, 16($sp)
    lw    $s0, 20($sp)
    lw    $s1, 24($sp)
    lw    $s2, 28($sp)
    jr    $ra
    addiu $sp, $sp, 32

# A miss (an in-between picture late for the tick, or an idle vblank whose
# work ran close to the next vblank): no in-between pictures
# for COOLDOWN << FAILS ticks, FAILS going up to 5 (2 s, 4 s, ... 32 s) until
# the next map.  Uses t8/t9 only.
blend_fail:
    {LA_T8_FAILS}
    lw    $t9, 0($t8)
    nop
    sltiu $t9, $t9, 5
    beqz  $t9, bf_cool
    lw    $t9, 0($t8)
    nop
    addiu $t9, $t9, 1
    sw    $t9, 0($t8)
bf_cool:
    lw    $t9, 0($t8)
    addiu $t8, $zero, {COOLDOWN}
    sllv  $t9, $t8, $t9
    {LA_T8_COOL}
    jr    $ra
    sw    $t9, 0($t8)

# ----------------------------------------------------- tick vblank environments
# Field: show the newest finished picture (NEXT) and draw the tick picture
# into the other half; both come from the same buffer struct DB(1-h).
# Anywhere else: the current buffer's, as the original does (it draws half k
# of buffer k and shows the other), keeping NEXT/SHOWN in step.
tick_env:
    addiu $sp, $sp, -24
    sw    $ra, 16($sp)
    sw    $s0, 20($sp)
    jal   blend_ok
    nop
    beqz  $v0, te_plain
    nop
    {LA_T0_NEXT}
    lw    $t1, 0($t0)
    {LA_T2_SHOWN}
    sw    $t1, 0($t2)
    {LA_S0_DB1}
    beqz  $t1, te_have
    xori  $t3, $t1, 1
    {LA_S0_DB0}
te_have:
    b     te_put
    sw    $t3, 0($t0)
te_plain:
    lui   $s0, 0x8010
    lw    $s0, -0x6678($s0)
    {LA_T1_DB0}
    {LA_T0_NEXT}
    xor   $t2, $s0, $t1
    sltu  $t2, $zero, $t2
    sw    $t2, 0($t0)
    xori  $t2, $t2, 1
    {LA_T0_SHOWN}
    sw    $t2, 0($t0)
te_put:
    jal   {PUTDISP}
    addiu $a0, $s0, 0x5c
    jal   {PUTDRAW}
    move  $a0, $s0
    lw    $ra, 16($sp)
    lw    $s0, 20($sp)
    jr    $ra
    addiu $sp, $sp, 24

# v0 = 1 once the field has been in plain play for WARMUP ticks in a row
# (drawing extra pictures while a map is still loading hangs the loader)
blend_ok:
    {LA_T0_STREAK}
    lw    $v0, 0($t0)
    nop
    slti  $v0, $v0, {WARMUP}
    jr    $ra
    xori  $v0, $v0, 1

# v0 = 1 when the field callbacks are the active set, no window is open, the
# map is drawn by the town layer renderer only and no fade/tint is on
can_blend:
    lui   $t0, 0x800d
    lw    $t0, -0x6f44($t0)
    nop
    lb    $t0, 0x2b($t0)
    nop
    bnez  $t0, cb_no
    nop
    {LA_T0_CBS}
    lw    $t1, 0($t0)
    {LA_T2_CB0}
    bne   $t1, $t2, cb_no
    lw    $t1, 4($t0)
    {LA_T2_CB1}
    bne   $t1, $t2, cb_no
    lw    $t1, 8($t0)
    {LA_T2_CB2}
    bne   $t1, $t2, cb_no
    nop
    {LA_T0_WIN}
    addiu $t3, $t0, 0xc0
win_loop:
    lw    $t1, 0($t0)
    addiu $t0, $t0, 12
    bnez  $t1, cb_no
    nop
    bne   $t0, $t3, win_loop
    nop
    # every enabled map layer must use renderer 1 (towns, 0x80083C94): the
    # world map's renderer 2 keeps state between frames, and drawing it at
    # an in-between camera corrupted the screen on the MiSTer
    {LA_T0_LAYERS}
    addiu $t3, $t0, 0xf0
lay_loop:
    lbu   $t1, 0x4a($t0)
    lbu   $t2, 0x49($t0)
    addiu $t0, $t0, 0x50
    beqz  $t1, lay_next
    addiu $t2, $t2, -1
    bnez  $t2, cb_no
    nop
lay_next:
    bne   $t0, $t3, lay_loop
    nop
    # no screen fade or tint (0x8007E6F0: fade length 0x800CCC4C, current
    # tint 0x800C90D0, neutral 0x80 0x80 0x80): the fade is an overlay the
    # in-between picture would lack, so it flashed during fades
    lui   $t0, 0x800d
    lh    $t1, -0x33b4($t0)
    lbu   $t2, -0x6f30($t0)
    lbu   $t3, -0x6f2f($t0)
    bnez  $t1, cb_no
    lbu   $t4, -0x6f2e($t0)
    addiu $t5, $zero, 0x80
    bne   $t2, $t5, cb_no
    nop
    bne   $t3, $t5, cb_no
    nop
    bne   $t4, $t5, cb_no
    nop
    jr    $ra
    addiu $v0, $zero, 1
cb_no:
    jr    $ra
    move  $v0, $zero

# copy a2 bytes (multiple of 4) from a1 to a0
copy:
    beqz  $a2, copy_done
    lw    $t0, 0($a1)
    addiu $a1, $a1, 4
    sw    $t0, 0($a0)
    addiu $a2, $a2, -4
    b     copy
    addiu $a0, $a0, 4
copy_done:
    jr    $ra
    nop

# midpoint of *a0 (current) and *a1 (previous) into *a0, unless far apart
blend_word:
    lw    $t0, 0($a0)
    lw    $t1, 0($a1)
    nop
    subu  $t2, $t0, $t1
    bgez  $t2, bw_abs
    nop
    negu  $t2, $t2
bw_abs:
    slti  $t2, $t2, {JUMP}
    beqz  $t2, bw_out
    addu  $t0, $t0, $t1
    sra   $t0, $t0, 1
    sw    $t0, 0($a0)
bw_out:
    jr    $ra
    nop

@CAVE2
# draw the in-between picture into buffer s0
blend_draw:
    addiu $sp, $sp, -24
    sw    $ra, 16($sp)
    {LA_A0_SNAPO}
    {LA_A1_OBJS}
    jal   copy
    addiu $a2, $zero, 0x1c00
    {LA_A0_SNAPL}
    {LA_A1_LAYERS}
    jal   copy
    addiu $a2, $zero, 0xf0
    {LA_A0_SNAPG1}
    {LA_A1_G1}
    jal   copy
    addiu $a2, $zero, 0x18
    {LA_A0_SNAPG2}
    {LA_A1_G2}
    jal   copy
    addiu $a2, $zero, 0x1c
    lui   $t0, 0x800d
    lw    $t0, -0x1fc0($t0)
    {LA_T1_SNAPC}
    sw    $t0, 0($t1)
    # redirect the drawing to buffer s0
    lui   $at, 0x8010
    lw    $s2, -0x6678($at)
    lw    $s3, -0x6674($at)
    sw    $s0, -0x6678($at)
    sw    $zero, -0x6674($at)
    addiu $a0, $s0, 0x70
    jal   {CLEAROT}
    addiu $a1, $zero, 0x800
    # camera layers: +0x10 / +0x14
    {LA_S1_LAYERS}
    {LA_T9_PREVL}
    addiu $t8, $zero, 3
bl_layers:
    addiu $a0, $s1, 0x10
    jal   blend_word
    move  $a1, $t9
    addiu $a0, $s1, 0x14
    jal   blend_word
    addiu $a1, $t9, 4
    addiu $s1, $s1, 0x50
    addiu $t8, $t8, -1
    bnez  $t8, bl_layers
    addiu $t9, $t9, 8
    # objects: +0x1c / +0x20
    {LA_S1_OBJS}
    {LA_T9_PREVO}
    addiu $t8, $zero, 64
bl_objs:
    addiu $a0, $s1, 0x1c
    jal   blend_word
    move  $a1, $t9
    addiu $a0, $s1, 0x20
    jal   blend_word
    addiu $a1, $t9, 4
    addiu $s1, $s1, 0x70
    addiu $t8, $t8, -1
    bnez  $t8, bl_objs
    addiu $t9, $t9, 8
    # map layers 0..2 at (x + [0x34], y + [0x38]), then the map finish
    {LA_S1_LAYERS}
    move  $t8, $zero
draw_layers:
    lw    $a1, 0x10($s1)
    lw    $t0, 0x34($s1)
    lw    $a2, 0x14($s1)
    lw    $t1, 0x38($s1)
    addu  $a1, $a1, $t0
    addu  $a2, $a2, $t1
    sw    $t8, 20($sp)
    jal   {LAYER_DRAW}
    move  $a0, $t8
    lw    $t8, 20($sp)
    addiu $s1, $s1, 0x50
    addiu $t8, $t8, 1
    slti  $at, $t8, 3
    bnez  $at, draw_layers
    nop
    jal   {MAP_FINISH}
    nop
    jal   {SPRITES}
    nop
    # put everything back
    lui   $at, 0x8010
    sw    $s2, -0x6678($at)
    sw    $s3, -0x6674($at)
    {LA_A0_OBJS}
    {LA_A1_SNAPO}
    jal   copy
    addiu $a2, $zero, 0x1c00
    {LA_A0_LAYERS}
    {LA_A1_SNAPL}
    jal   copy
    addiu $a2, $zero, 0xf0
    {LA_A0_G1}
    {LA_A1_SNAPG1}
    jal   copy
    addiu $a2, $zero, 0x18
    {LA_A0_G2}
    {LA_A1_SNAPG2}
    jal   copy
    addiu $a2, $zero, 0x1c
    {LA_T1_SNAPC}
    lw    $t0, 0($t1)
    lui   $at, 0x800d
    sw    $t0, -0x1fc0($at)
    lw    $ra, 16($sp)
    nop                         # load delay: jr would still see the old $ra
    jr    $ra
    addiu $sp, $sp, 24

# ------------------------------------------- tick vblank, before callbacks
save_prev:
    addiu $sp, $sp, -8
    sw    $ra, 0($sp)
    jal   can_blend
    nop
    {LA_T0_STREAK}
    lw    $t1, 0($t0)
    beqz  $v0, sp_reset
    addiu $t1, $t1, 1
    slti  $t2, $t1, 0x7fff
    bnez  $t2, sp_store
    nop
    addiu $t1, $zero, 0x7fff
    b     sp_store
    nop
sp_reset:
    {LA_T2_FAILS}
    sw    $zero, 0($t2)
    {LA_T2_COOL}
    sw    $zero, 0($t2)
    move  $t1, $zero
sp_store:
    sw    $t1, 0($t0)
    {LA_T0_COOL}
    lw    $t1, 0($t0)
    nop
    beqz  $t1, sp_cool
    addiu $t1, $t1, -1
    sw    $t1, 0($t0)
sp_cool:
    lw    $ra, 0($sp)
    addiu $sp, $sp, 8
    {LA_T0_LAYERS}
    {LA_T1_PREVL}
    addiu $t2, $zero, 3
sp_layers:
    lw    $t3, 0x10($t0)
    lw    $t4, 0x14($t0)
    addiu $t0, $t0, 0x50
    sw    $t3, 0($t1)
    sw    $t4, 4($t1)
    addiu $t2, $t2, -1
    bnez  $t2, sp_layers
    addiu $t1, $t1, 8
    {LA_T0_OBJS}
    {LA_T1_PREVO}
    addiu $t2, $zero, 64
sp_objs:
    lw    $t3, 0x1c($t0)
    lw    $t4, 0x20($t0)
    addiu $t0, $t0, 0x70
    sw    $t3, 0($t1)
    sw    $t4, 4($t1)
    addiu $t2, $t2, -1
    bnez  $t2, sp_objs
    addiu $t1, $t1, 8
    j     {DISPATCH}
    nop
"""

LAYERS = 0x8010DF80
OBJS = 0x800FE700
CBS = 0x800DB4E0
WINDOWS = 0x800FC580
G1, G2 = 0x800CDD94, 0x800D0030


BLEND = True       # False: idle vblank draws nothing new (debug)
SKIP = ()          # debug: drop pieces of the in-between drawing, see SKIPS
TRACE = False      # debug: counters and progress markers at 0x801E6760..
LATE = None        # debug: stall the idle vblank until this line before submitting (a slow machine)
PAD_TO = None      # debug: pad the code with nops up to this many words

NL = chr(10)
TRACE_COUNT = NL.join(["    lui   $at, 0x801e", "    lw    $v1, {off}($at)", "    nop",
                       "    addiu $v1, $v1, 1", "    sw    $v1, {off}($at)"]) + NL
TRACE_MARK = NL.join(["    lui   $at, 0x801e", "    addiu $v1, $zero, {n}",
                      "    sw    $v1, 0x6760($at)"]) + NL
TRACE_COUNTERS = (("idle:", 0x6770), ("tick_env:", 0x6774), ("save_prev:", 0x6778), ("blend_draw:", 0x677C))
TRACE_MARKS_SHOW = (("have_denv:", 21),)
TRACE_MARKS = (("    jal   {DRAWOTAG}", 1), ("    jal   blend_draw", 2), ("    # redirect the drawing to buffer s0", 3),
               ("    jal   {CLEAROT}", 4), ("    # objects: +0x1c / +0x20", 5), ("    jal   {MAP_FINISH}", 6),
               ("    jal   {SPRITES}", 7), ("    # put everything back", 8), ("show:", 9), ("idle_out:", 10))


def _pair(a0, a1):
    return NL.join(["    {" + a0 + "}", "    {" + a1 + "}", "    jal   copy"])


NOP3 = NL.join(["    nop"] * 3)
SKIPS = {
    "layers": [("    jal   {LAYER_DRAW}", "    nop")],
    "finish": [("    jal   {MAP_FINISH}", "    nop")],
    "sprites": [("    jal   {SPRITES}", "    nop")],
    "clear": [("    jal   {CLEAROT}", "    nop")],
    "blend": [("    jal   blend_word", "    nop")],
    "redirect": [("    sw    $s0, -0x6678($at)", "    nop")],
    "snapobj": [(_pair("LA_A0_SNAPO", "LA_A1_OBJS"), NOP3), (_pair("LA_A0_OBJS", "LA_A1_SNAPO"), NOP3)],
    "snaplayers": [(_pair("LA_A0_SNAPL", "LA_A1_LAYERS"), NOP3), (_pair("LA_A0_LAYERS", "LA_A1_SNAPL"), NOP3)],
    "snapg1": [(_pair("LA_A0_SNAPG1", "LA_A1_G1"), NOP3), (_pair("LA_A0_G1", "LA_A1_SNAPG1"), NOP3)],
    "g2": [(_pair("LA_A0_SNAPG2", "LA_A1_G2"), NOP3), (_pair("LA_A0_G2", "LA_A1_SNAPG2"), NOP3)],
    "testjal": [("    # redirect the drawing to buffer s0", "    jal   blend_ok" + NL + "    nop" + NL + "    # redirect the drawing to buffer s0")],
    "hwprobe": [("show:" + NL + "    # Submit", "show:" + NL + "    lui   $t0, 0x1f80" + NL + "    lw    $t1, 0x1814($t0)" + NL + "    lw    $t2, 0x10a8($t0)" + NL + "    lui   $at, 0x801e" + NL + "    sw    $t1, 0x6790($at)" + NL + "    sw    $t2, 0x6794($at)" + NL + "    lw    $t1, 0x10f4($t0)" + NL + "    nop" + NL + "    sw    $t1, 0x6798($at)" + NL + "    # Submit")],
    # hblanks since the handler started (root counter 1), last and max, at:
    # 0 tick_env entry (tick waited for the in-between picture), 1 idle after
    # its first DrawSync, 2 idle end -> 0x801F9F80 + 8n (last, max)
    "timing": [(needle, repl.replace("@", NL.join([
        "    lui   $at, 0x1f80", "    lw    $v1, 0x1110($at)", "    lui   $at, 0x8020", "    andi  $v1, $v1, 0xffff",
        f"    sw    $v1, {-0x6080 + 8 * n}($at)", f"    lw    $t9, {-0x6080 + 8 * n + 4}($at)", "    nop",
        "    sltu  $t9, $t9, $v1", f"    beqz  $t9, tm_{n}", "    nop", f"    sw    $v1, {-0x6080 + 8 * n + 4}($at)", f"tm_{n}:"])))
        for n, (needle, repl) in enumerate([
            ("tick_env:" + NL, "tick_env:" + NL + "@" + NL),
            ("id_disp:" + NL, "id_disp:" + NL + "@" + NL),
            ("idle_out:" + NL, "@" + NL + "idle_out:" + NL)])],
    "g1zero": [("    jal   copy" + NL + "    addiu $a2, $zero, 0x18", "    jal   copy" + NL + "    addiu $a2, $zero, 0")],
}


def source():
    s = CODE
    if TRACE:
        for label, off in TRACE_COUNTERS:
            s = s.replace(label + NL, label + NL + TRACE_COUNT.format(off=hex(off)), 1)
        for needle, n in TRACE_MARKS_SHOW:
            assert needle in s, needle
            s = s.replace(needle, TRACE_MARK.format(n=n) + needle, 1)
        for needle, n in TRACE_MARKS:
            assert needle in s, needle
            s = s.replace(needle, TRACE_MARK.format(n=n) + needle, 1)
    if not BLEND:
        s = s.replace("    jal   blend_draw", "    nop")
    if LATE:
        s = s.replace("show:" + NL, "show:" + NL + NL.join([
            "    lui   $t0, 0x1f80", "late_wait:", "    lw    $t1, 0x1110($t0)", "    nop", "    andi  $t1, $t1, 0xffff",
            f"    slti  $t1, $t1, {LATE}", "    bnez  $t1, late_wait", "    nop"]) + NL, 1)
    for key in SKIP:
        for old, new in SKIPS[key]:
            assert old in s, (key, old)
            s = s.replace(old, new)
    subs = {
        "LA_T1_DB0": la("$t1", DB0), "LA_T3_DB0": la("$t3", DB0), "LA_T3_DB1": la("$t3", DB1),
        "LA_T3_DRENV0": la("$t3", DB0 + 0x1C), "LA_T3_DRENV1": la("$t3", DB1 + 0x1C),
        "WAIT_LIMIT": str(WAIT_LIMIT), "SUBMIT_LIMIT": str(SUBMIT_LIMIT), "IDLE_LATE": str(IDLE_LATE), "COOLDOWN": str(COOLDOWN), "LA_S0_DB0": la("$s0", DB0), "LA_S0_DB1": la("$s0", DB1),
        "LA_A0_DB1D": la("$a0", DB1 + 0x5C), "LA_A0_DB1": la("$a0", DB1), "LA_A0_DB0": la("$a0", DB0),
        "LA_T0_CBS": la("$t0", CBS), "LA_T0_WIN": la("$t0", WINDOWS),
        "LA_T2_CB0": la("$t2", FIELD_CBS[0]), "LA_T2_CB1": la("$t2", FIELD_CBS[1]),
        "LA_T2_CB2": la("$t2", FIELD_CBS[2]),
        "LA_A0_SNAPO": la("$a0", SNAP_OBJS), "LA_A1_SNAPO": la("$a1", SNAP_OBJS),
        "LA_A0_OBJS": la("$a0", OBJS), "LA_A1_OBJS": la("$a1", OBJS),
        "LA_S1_OBJS": la("$s1", OBJS), "LA_T0_OBJS": la("$t0", OBJS),
        "LA_A0_SNAPL": la("$a0", SNAP_LAYERS), "LA_A1_SNAPL": la("$a1", SNAP_LAYERS),
        "LA_A0_LAYERS": la("$a0", LAYERS), "LA_A1_LAYERS": la("$a1", LAYERS),
        "LA_S1_LAYERS": la("$s1", LAYERS), "LA_T0_LAYERS": la("$t0", LAYERS),
        "LA_A0_SNAPG1": la("$a0", SNAP_G1), "LA_A1_SNAPG1": la("$a1", SNAP_G1),
        "LA_A0_SNAPG2": la("$a0", SNAP_G2), "LA_A1_SNAPG2": la("$a1", SNAP_G2),
        "LA_A0_G1": la("$a0", G1), "LA_A1_G1": la("$a1", G1),
        "LA_A0_G2": la("$a0", G2), "LA_A1_G2": la("$a1", G2),
        "LA_T1_SNAPC": la("$t1", SNAP_CNT), "LA_T0_STREAK": la("$t0", STREAK), "WARMUP": str(WARMUP),
        "LA_T9_PREVL": la("$t9", PREV_LAYERS), "LA_T1_PREVL": la("$t1", PREV_LAYERS),
        "LA_T9_PREVO": la("$t9", PREV_OBJS), "LA_T1_PREVO": la("$t1", PREV_OBJS),
        "DRAWSYNC": hex(DRAWSYNC), "PUTDISP": hex(PUTDISP), "PUTDRAW": hex(PUTDRAW),
        "DRAWOTAG": hex(DRAWOTAG), "EXEQUE": hex(EXEQUE), "CLEAROT": hex(CLEAROT), "DISPATCH": hex(DISPATCH),
        "LAYER_DRAW": hex(LAYER_DRAW), "MAP_FINISH": hex(MAP_FINISH),
        "SPRITES": hex(SPRITES), "JUMP": hex(JUMP),
    }
    for var, addr in (("NEXT", NEXT), ("SHOWN", SHOWN), ("MID", MID), ("COOL", COOL), ("FAILS", FAILS)):
        for r in range(10):
            subs[f"LA_T{r}_{var}"] = la(f"$t{r}", addr)
        subs[f"LA_S1_{var}"] = la("$s1", addr)
    for k, v in subs.items():
        s = s.replace("{" + k + "}", v)
    assert "{" not in s, s[s.index("{"):s.index("{") + 30]
    # keystone: drop comments
    return "\n".join(line.split("#")[0] for line in s.splitlines())


def label_addrs(src, base):
    """Every source line is one instruction (no expanding pseudo-ops), so a
    label's address is its line count.  Returns (labels, instruction count)."""
    labels, n = {}, 0
    for line in src.splitlines():
        t = line.strip()
        if t.endswith(":"):
            labels[t[:-1]] = base + 4 * n
        elif t:
            n += 1
    return labels, n


def resolve_calls(src, labels):
    """Replace "jal label" / "j label" with absolute targets (also across the
    two caves).  keystone resolves them nondeterministically (see apply);
    branches are PC-relative and fine."""
    out = []
    for line in src.splitlines():
        m = re.fullmatch(r"\s*(jal|j)\s+([A-Za-z_]\w*)\s*", line)
        out.append(f"    {m.group(1)} {labels[m.group(2)]:#x}" if m else line)
    return NL.join(out)


def check_load_delays(code):
    """R3000 load delay: the instruction right after a load still sees the
    register's old value (lw $ra; jr $ra returns to the *previous* $ra).
    Refuse any load whose next instruction reads or writes the loaded
    register.  A load in the delay slot of an unconditional jump is followed
    by the jump target instead, so it is skipped."""
    words = struct.unpack(f"<{len(code) // 4}I", code)
    for i in range(len(words) - 1):
        w, nxt = words[i], words[i + 1]
        op, rt = w >> 26, (w >> 16) & 0x1F
        if op not in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26) or rt == 0:
            continue
        if i > 0:
            p = words[i - 1]
            pop = p >> 26
            if pop in (2, 3) or (pop == 0 and (p & 0x3F) in (8, 9)) or (pop == 4 and (p >> 16) & 0x3FF == 0):
                continue
        nop_, nrs, nrt, nrd = nxt >> 26, (nxt >> 21) & 0x1F, (nxt >> 16) & 0x1F, (nxt >> 11) & 0x1F
        reads = {nrs}
        if nop_ in (0, 4, 5) or 0x28 <= nop_ <= 0x2E:
            reads.add(nrt)
        writes = {nrd} if nop_ == 0 else ({nrt} if 0x08 <= nop_ <= 0x0F or 0x20 <= nop_ <= 0x26 else set())
        if op in (0x22, 0x26) and nop_ in (0x22, 0x26):
            continue                                    # lwl/lwr pair
        assert rt not in reads | writes, f"load delay hazard at +{i * 4:#x}: register {rt} used by the next instruction"


def apply(exe, base, assemble, branch, BEQ):
    def at(a, n=4):
        return exe[a - base:a - base + n]

    def put(a, code):
        exe[a - base:a - base + len(code)] = code

    assert at(CAVE) == assemble("addiu $sp, $sp, -0x188", 0), "0x8009A670 is not the expected dead function"
    assert at(CAVE2) == assemble("addiu $sp, $sp, -0x38", 0), "0x800B4954 is not the expected dead function"
    src_a, src_b = source().split("@CAVE2")
    labels_a, words_a = label_addrs(src_a, CAVE)
    labels_b, words_b = label_addrs(src_b, CAVE2)
    labels = {**labels_a, **labels_b}
    for src, org, words, limit in ((src_a, CAVE, words_a, CAVE_WORDS - DATA_WORDS), (src_b, CAVE2, words_b, CAVE2_WORDS)):
        code = assemble(resolve_calls(src, labels), org)
        assert len(code) == 4 * words, (len(code) // 4, words)
        # keystone sometimes turns a call to a label into a $gp-relative PIC
        # call ("lw $t9, 0($gp); jalr $t9"), even for the same source that
        # assembled fine a moment earlier: refuse that.
        for i in range(0, len(code), 4):
            w = struct.unpack_from("<I", code, i)[0]
            assert ((w >> 21) & 0x1F) != 28 or (w >> 26) not in (0x23, 0x2B), f"$gp access at +{i:#x}: unresolved label?"
            assert w != 0x0320F809, f"jalr $t9 at +{i:#x}: unresolved label?"
        check_load_delays(code)
        if PAD_TO and org == CAVE:
            code += assemble("nop", 0) * (PAD_TO - len(code) // 4)
        assert len(code) <= limit * 4, (hex(org), len(code) // 4, limit)
        put(org, code)
    for a in (STREAK, SHOWN, NEXT, MID, COOL, FAILS):
        put(a, struct.pack("<I", 0))
    idle_entry, tick_env, save_prev, tick_pre = CAVE, CAVE + 8, CAVE + 16, CAVE + 24

    # debug load-meter printout -> skipped; its space holds the trampoline
    assert at(0x80011648) == jal(0x80079DC0)
    put(0x80011648, branch(BEQ, 0, 0x80011648, 0x800116C4))
    put(0x8001164C, assemble("nop", 0))
    tramp = jal(idle_entry) + assemble("nop", 0) + branch(BEQ, 0, TRAMP + 8, 0x8001171C) + assemble("nop", 0)
    put(TRAMP, tramp)

    # idle vblank: "beqz $t0, 0x8001171c" -> "beqz $t0, TRAMP"
    assert at(0x80011640) == branch(BEQ, 8, 0x80011640, 0x8001171C)
    put(0x80011640, branch(BEQ, 8, 0x80011640, TRAMP))

    # tick vblank: DrawSync(0) -> tick_pre (bounded wait for the in-between picture)
    assert at(0x800116C4) == jal(DRAWSYNC)
    put(0x800116C4, jal(tick_pre))

    # tick vblank: environments chosen by tick_env
    assert at(0x800116EC) == jal(PUTDISP) and at(0x800116FC) == jal(PUTDRAW)
    put(0x800116E4, jal(tick_env) + assemble("nop", 0) * 7)

    # tick vblank: save the previous positions just before the callbacks
    assert at(0x8001175C) == jal(DISPATCH)
    put(0x8001175C, jal(save_prev))
    return words_a + words_b
