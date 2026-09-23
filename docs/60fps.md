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
layer renderers and `0x80088D7C`; measure GPU time per picture (DrawSync
wait); find room for the in-between-frame code; prototype with the camera
only (map layers at the interpolated camera, sprites unchanged).
