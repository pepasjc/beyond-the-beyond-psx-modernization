# Beyond the Beyond — PSX Modernization

Quality-of-life patch for **Beyond the Beyond** (PlayStation, USA, SCUS-94702),
built on top of the fan patch **Beyond the Beyond – Reunion** by Skiller and
Shadow501.

## Features

- **Modern confirm/cancel layout:** ✕ and △ are swapped everywhere (field,
  menus and battle).
- **Run button:** hold ○ on the field or world map to move at 2× speed.
  The whole party runs, not just the leader. Running reaches full speed
  within one update, so the scroll stays even from tile to tile. A 1.5×
  preset is available for smaller scroll steps.
- **Faster battle walk-up:** the plain melee attack reaches the enemy in half
  the time (6 updates instead of 12, same distance). The swing, hit and
  damage timing after the walk are unchanged.
- **Smooth followers:** party followers such as the dragon move at the
  leader's speed and keep a steady distance, instead of rushing a tile and
  stopping. This works both walking and running.
- **HP instead of VP:** menus, status screens and item/spell names ("HP Up",
  "Everyone's HP Heal") say HP.
- **Rebalanced rewards:** EXP ×2.5, gold ×4.
- **Random encounters:** the original per-step roll against each area's rate
  is restored. After every fight there is a 25-step grace period, so there
  are no back-to-back battles. On average there is a fight every ~36–50
  steps instead of Reunion's fixed one every 70.
- **Bug fix:** in Reunion, one of the two enemy-defeat paths looked up gold
  with a stale monster id. Every enemy now pays its own gold.

## Credits

- **Original patch: [Beyond the Beyond – Reunion](https://www.romhacking.net/hacks/9516/)**
  - **Skiller:** 1.0 (reduced encounter rate, encounters disabled through
    the picture-puzzle escape until Zalagoon) and 1.2 (double experience).
  - **Shadow501:** 1.1 (increased gold, Percy stays in the party),
    1.3 (character rebalance, Samson no longer affected by the Ramue curse)
    and 1.4 (gold ×3, Samson's armor colours to match the cover art).

  This project applies on top of **Reunion 1.4** (`Beyond the Beyond - Reunion
  (Ver 1.4).PPF`, 158 records / 237 bytes). All of Reunion's changes are kept:
  the stat rebalance (`SYSTEM/RESIUS.DAT`), the dialog and battle-graphics
  edits, and the executable changes. Only its reward multipliers and its
  encounter rule are adjusted here (see Features). In the executable, Reunion
  multiplies both EXP and gold by 4 (`sll $v0,$v0,2`) and replaces the
  random encounter roll with one battle every 70 steps.
- **Beyond the Beyond** © 1995/1996 Sony Computer Entertainment, developed by
  Camelot Software Planning. This repository contains no game data.
- **Emulator test harness:** built on `emurun.py` from the Snatcher translation
  project, which hosts the [Beetle PSX](https://github.com/libretro/beetle-psx-libretro)
  libretro core.
- **Libraries:** [Keystone](https://www.keystone-engine.org/) (assembler) and
  [Capstone](https://www.capstone-engine.org/) (disassembler).

## Building

You need:

- A dump of Beyond the Beyond (USA) as a single-track `MODE2/2352` `.bin`,
  CRC32 `453917AF`, with the Reunion 1.4 PPF applied (e.g. with PPF-O-Matic
  or ppfdev).
- Python 3.10+ with `pip install keystone-engine capstone`.
- `chdman` (MAME tools) to convert CHD ↔ BIN/CUE.

```sh
chdman extractcd -i "Beyond the Beyond (USA).chd" -o reunion.cue -ob reunion.bin
python build_patch.py reunion.bin modern.bin          # run speed 2x (default)
python build_patch.py reunion.bin modern.bin 1.5x     # gentler run
# write a cue for modern.bin, then:
chdman createcd -i modern.cue -o "Beyond the Beyond (USA).chd"
```

`build_patch.py` asserts it is patching the expected code before touching
anything, and rewrites the EDC/ECC of every sector it changes.

Keep the output's file name the same as your old image (or rename your save
to match). Emulators and the MiSTer name memory cards after the game file.

## How it works

All code changes are in `SCUS_947.02`. The executable has no free space, so
new code comes from rewriting existing routines more compactly. See the
docstring at the top of `build_patch.py` for each change.

| What | Address |
|---|---|
| `PadRead()` (libetc) | `0x800C21A8` |
| Pad 1 held / pressed / repeat | `0x800C9070` / `78` / `74` |
| Per-frame input routine (✕/△ swap) | `0x80011350` |
| Field objects (`0x70` bytes each) | `0x800FE700` |
| Player object index | `0x800CDDB8` |
| Field object physics loop | `0x800894CC` |
| Object script opcode table (`0x25` = follow) | `0x800CE050` |
| Random encounter check | `0x8006DCA0` (roll at `0x8006E040`) |
| Enemy-defeat rewards | `0x800423F8`, `0x80042490` |
| Battle EXP / gold totals | `0x800F9B08` / `0x800F9B0C` |
| Battle actors (`0x48` bytes each: x/y/z, velocity at `+8`, state `+0x14`, counter `+0x16`) | `0x800F9B20` |
| Battle actor update loop (works on a stack copy at `sp+0xC0`) | `0x8001E208` |
| Battle state jump table (`0x140` = walk-up, `0x10E` = walk back) | `0x800C4C6C` |
| Walk-up setup by attack type / timing by attack type | `0x800C51D8` / `0x800C5218` |

The field logic and battle actors both update at 30 Hz. Walking moves 4 px per update, running at 2×
moves 8 px.

## Tools

| File | Purpose |
|---|---|
| `build_patch.py` | Applies every change to a disc image |
| `disc.py` | ISO9660 file lookup and in-place file rewrite for MODE2/2352 images, with EDC/ECC |
| `mips.py` | Capstone disassembly helpers for the executable |
| `scan.py` | Finds a word (default `VP`) in every file on the disc |
| `emu.py` | Headless emulator harness: boots the disc with a memory card, reads RAM, drives input |
| `measure_run.py` | Boots to the field and logs per-update movement while running |
| `clip.py` | Records an MP4 from a savestate while holding buttons |

The harness needs the Beetle PSX libretro core, a PS1 BIOS, and `emurun.py`
(set `EMURUN_DIR`).

`debug/` holds test-only tools:

| File | Purpose |
|---|---|
| `test_build.py` | Builds `work/test.bin`, where every step starts a battle (fixed encounter area, set with `AREA`), even in towns |
| `nav.py` | Restores a Beetle savestate, plays a list of moves, saves a state and a screenshot |
| `battle_attack.py` | Starts a battle, attacks with everyone, logs Finn's walk and records an MP4 |
| `battle_walk_watch.lua` | PCSX-Redux script: write breakpoints on the party's battle position/velocity, logs every writer PC |
| `play_redux.bat` | Opens PCSX-Redux with the test disc and that script, for someone to play while it records |

## Known limits

- NPC dialog (`.TLK` files) is compressed. Any "VP" said in dialog is still VP.
- Holding ○ also speeds up characters that use the follow command during
  cutscenes.
- Reunion redirects a flag write at `0x80073B80` (byte `0x44` bit 1 of a
  monster/party table entry → byte `7`). This is probably its "Samson is no
  longer affected by the Ramue curse" change. It is left as is.
