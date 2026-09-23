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

Next steps: find where the display list is submitted (DrawOTag / buffer
swap) and which of the three callbacks draw; measure GPU time; prototype
option 2 for the camera + player + followers only.
