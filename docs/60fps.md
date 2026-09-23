# 60 fps investigation

Branch `60fps`. Notes as the work goes; addresses are in the original
executable (SCUS_947.02), unchanged by the v0.1 patch unless noted.

## How the game paces itself

- `0x8001177C wait(n)` — the frame wait used everywhere (172 callers). Reads
  root counter 1 (hblanks) into a running total at `0x800C90AC`, then n times:
  `VSync(0)` (`0x800C2780`) and the per-vblank handler `0x800115CC`.
- `0x800115CC` per-vblank handler, every vblank:
  - restarts root counter 1 (so the counter measures CPU work since the last
    vblank — the game's own load meter; `0x800F99B8` enables an on-screen
    readout);
  - reads the pad (`0x8001133C`, our rewritten input routine);
  - **only when bit 0 of `0x800C90A4` is set** (it flips every frame, write
    at `0x800115C8`): runs `0x8007E6F0`, `0x800A8838` and the callback
    dispatcher `0x80010B54` → table `0x800DB4E0` (16 slots, enable flags at
    `0x800DB520`);
  - always runs `0x80010EB0` → second callback table `0x800DB530` (flags at
    `0x800DB570`), which is **empty** on the field.
- So all field logic *and* drawing run at 30 Hz, and the screen shows each
  picture for two vblanks.

Field callbacks (30 Hz table) at Marion church:

| Callback | What |
|---|---|
| `0x80085EFC` | (to identify) |
| `0x80086550` | object physics `0x800894CC`, sprite setup `0x80088D7C`, camera `0x80085BD8` |
| `0x80047684` | (to identify; walks a 12-byte-entry table at `0x800FC580`) |

## CPU budget

Measured in Beetle with the game's meter, walking and running in town:

| | hblanks |
|---|---|
| One field update (logic + display list) | 135–190 |
| Idle second vblank | 1–2 |
| One NTSC frame | 263 |

A whole field update fits in one frame (50–70 %), so the CPU could run it
every vblank. GPU time is not measured yet.

## GPU budget

`debug/gpu_time_build.py` + `gpu_time_log.py`: a test disc that stores
GPUSTAT and DMA2 CHCR at the start of every vblank. In Beetle, walking and
running in Marion town, the GPU was ready for commands and DMA2 idle at the
start of all 300 vblanks sampled, including the one right after each picture
was submitted: one picture draws in under a frame.

Waiting on the GPU from inside the vblank handler does not work (DrawSync
or polling GPUSTAT/CHCR hangs after the first picture): the draw queue
advances in interrupt callbacks. Measure passively.

Still to check: heavier scenes (world map, big towns), and real hardware
(MiSTer core GPU timing).

## Options

1. **Run the callbacks every vblank** (drop the parity gate on the field) and
   halve every per-update quantity: movement (accel/friction), animation
   counters, script waits, camera, timers. Real 60 Hz, but every system tuned
   to 30 Hz has to be found and rescaled — high risk in scripted scenes.
2. **Keep logic at 30 Hz, draw an in-between picture** on the other vblank:
   positions and camera halfway between the last two updates. Needs the
   drawing part of the callbacks split from the logic part, and a second
   display list per update. Logic timing stays exactly as shipped.

## Drawing pipeline (found)

On each 30 Hz vblank, `0x800115CC` (when `0x800F99B8` graphics-enable is set
and the parity bit is set):

1. optional load-meter printout (event flag 0x10, `FntPrint` `0x800AFF74`);
2. `DrawSync(0)` — `0x800ACAFC`;
3. `PutDispEnv(db+0x5C)` `0x800AD130`, `PutDrawEnv(db)` `0x800AD040`,
   `DrawOTag(db+0x70)` `0x800ACFD8`, where `db` = `*(0x800F9988)`;
4. swap the double buffer — `0x800114BC`;
5. read the pad, then the callbacks build the next picture into the new
   buffer.

So a picture built on vblank N is shown from vblank N+2; the in-between
vblank draws nothing and swaps nothing.

Field callbacks:

- `0x80085EFC` — camera + map. Moves the camera struct at `0x8010DF80`
  (position `+0/+4`, target `+8/+0xC`, velocity `+0x34/+0x38`, shake
  `+0x40/+0x42`), then draws each map layer through `0x80084534` →
  six layer renderers (jump table `0x800C7F50`: `0x80083C94`, `0x80082EB4`,
  `0x800825BC`, `0x80084054`, `0x80083854`, `0x80082A48`).
- `0x80086550` — object physics (logic), sprite setup `0x80088D7C` (draw,
  but also advances animation counters `+0x58`, `+0x5B`), camera follow
  `0x80085BD8` (logic).
- `0x80047684` — (to identify).

## Plan for option 2

On the in-between vblank:

1. keep the previous and current positions of the camera and every visible
   object (or last velocity);
2. set them to the midpoint, run only the drawing parts (map layers + sprite
   setup without advancing animation counters) into the other buffer;
3. `DrawSync`/`PutDispEnv`/`PutDrawEnv`/`DrawOTag` + swap, as the 30 Hz path
   does;
4. put the real positions back.

The hard part is step 2: separating drawing from state changes inside the
layer renderers and `0x80088D7C`, and finding room for the new code (the
executable has no free space; a code cave has to come from compacting
existing routines or from unused RAM loaded by an overlay).

Next steps: identify `0x80047684`; list every state write inside the six
layer renderers and `0x80088D7C`; find room for the in-between-frame code
(RAM that stays zero on the field: `0x800D5C00`-`0x800D9C00` (16 KB),
`0x801E4800`-`0x801E9800`, `0x801F7800`-`0x801FC000` — to be checked in
battles and menus); prototype with the camera only (map layers at the
interpolated camera, sprites unchanged).

## Prototype status (interp60.py, `build_patch.py --smooth`)

Works in Beetle. On the field the screen shows a new picture every vblank:
the scroll moves 2 px per frame instead of 4 px every other frame.
Random-input soaks ran without a freeze: 5 seeds of 20–30k frames each,
covering town, graveyard, houses, menus, dialogs and doors. The soaks never
reached the world map or a battle. Battles keep the original code because
they use other callbacks.

- Code cave: `0x8009A670` (476 words). Nothing on the disc calls it, jumps
  into it or points to it (`work/deadcode.py`). Its last word holds the
  warm-up streak, so only this code writes the streak.
- Scratch RAM: `0x801F8000..0x801F9F54` (positions, snapshots).
  `debug/ramuse.py` showed the game never writes `0x801F7800..0x801FC000`.
  That range is the gap between the sound bank and the deepest stack use.
  The sound bank is fixed file 0xF at `0x801F3A00` and never changes size.
- Hooks:
  - idle vblank → `idle` (trampoline in the dropped debug load-meter block);
  - tick vblank environments → `tick_env`;
  - before the tick callbacks → `save_prev`.
- Tick vblank (field): the finished picture is drawn into the top half, and
  the bottom half is shown.
- Idle vblank:
  1. `DrawSync`, then show the top half (GP1 05) right away.
  2. Draw the in-between picture into the other buffer: positions halfway,
     map layers + sprites; everything is snapshotted first and put back
     after.
  3. Send it straight through DMA channel 2, not through libgpu.
- Only active in plain field play: field callback set, no window, double
  buffering, after a 45-tick warm-up.

### Bugs found on the way (worth remembering)

- **Load delay slot.** `lw $ra, 16($sp)` directly followed by `jr $ra`
  returns to the *old* `$ra`. blend_draw's epilogue did that:
  - after its last `jal copy` it jumped back into its own tail and popped its
    frame twice;
  - idle then restored garbage and jumped to 0xF2000001;
  - it only happened when blend_draw called anything. That looked like "any
    jal freezes", and before that like a libgpu queue race.

  `check_load_delays` now refuses any load whose next instruction uses the
  loaded register.
- **keystone is nondeterministic with `jal label`.** The same source
  sometimes assembles to a `$gp`-relative PIC call (`lw $t9, ($gp); jalr
  $t9`). `resolve_calls` turns every `jal/j label` into an absolute target
  before keystone sees it. A guard also refuses `$gp` loads and `jalr $t9`.
- **Tearing.** The display switch (GP1 05) came after the in-between
  picture was drawn, ~115 lines into the frame. The switch now comes first.
- **Scratch RAM.** `0x801E4800..` is free in Marion but holds map data
  elsewhere, because per-map files load at `0x801E2000`. A soak overwrote
  the streak there, and the game crashed after a map change.

Debugging tools:

- Beetle has no register access, but the BIOS saves the interrupted context
  in the TCB on every interrupt. Read it from RAM to get the PC of a hung
  main thread (`debug/tcb_probe.py`):
  - TCB at `*(*0x80000108)`;
  - epc at +0x88, ra at +0x84, sp at +0x7C.
- `debug/soak.py`: random inputs, freeze detector, state trail.
- `debug/stability.py`, `debug/ramuse.py`.
- `debug/smooth_build.py`, options `noblend`, `trace`, `skip=<piece>`,
  `pad=<words>`.
- `debug/hang_probe.lua`/`.bat` (PCSX-Redux).

Next: manual testing on the MiSTer (world map, dungeons, battles in and
out, running, followers). Then decide whether `--smooth` becomes a build
default.
