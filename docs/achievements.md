# Built-in achievements

The patch runs the [RetroAchievements set for Beyond the Beyond](https://retroachievements.org/game/11415)
(63 achievements, 560 points, by tele) on the console itself, in the same way as the
Resident Evil 2 Ultimate Edition patch. Nothing is sent to retroachievements.org.

- **Real time:** achievements are tested every vblank. An unlock shows a popup at the
  top of the screen ("Achievement unlocked!", title, points) for 3.5 s, with the
  menu confirm sound, on the field, the world map and in battle. The memory card is
  written at once, without a save.
- **Menu:** the field menu has an **Achievements** item (the last one, under Save).
  It lists every achievement with the count and points at the top: unlocked ones
  in gold with a `+`, locked ones greyed. The window under the list shows the
  selected one's points, state and description. ↑/↓ move, ←/→ move six at a time,
  ○ (or START) closes.
- **Separate save:** unlocks are kept in their own memory card file,
  `BASCUS-94702ACH` ("BtB ACHIEVEMENTS", one block, trophy icon). It is shared by
  every save game and isn't listed by the game's load and save screens. At power on
  the file is read from both slots (unlocks are merged) and, if neither card has it,
  made in slot 1 (slot 2 if that fails). Without a card with a free block, unlocks
  last only until power off.

## How it works

### Room

The executable has no free space, and most of RAM is in use somewhere in the game
(`debug/ramfree.py` / `ramfree_sum.py` list the 256-byte blocks that stay zero over
random play, battles, menus, saves and the world map). The largest unused block that
nothing but debug code refers to is `0x800D5A88..0x800D9E88` (17 KB): the string and
sprite buffers of libgpu's debug font, which only `FntOpen` fills. Only a debug menu
(behind a debug flag, `0x800619A0`) opens a font. The patch:

- makes `FntOpen` (`0x800AFA80`) return -1 at once; `FntFlush` and `FntPrint` (called
  every tick by the original) do nothing without an open stream;
- starts the startup code's BSS clear (`0x800AC5C4`) at `0x800D9E88` instead of
  `0x800D51A0` (the exe file holds zeros up to there);
- grows the exe to load the achievements code at `0x800D5A90`. The bigger exe moves
  into the last sectors of `MOVIE/PAD.FIL`, a 32 MB padding file nothing reads
  ("That's All, Folks!" and `0xFF` bytes), whose directory entry shrinks by as much
  (`Disc.move_file_into`).

Everything (code, tables, texts, state) takes about 15.4 KB, so there are about
390 bytes left.

### The evaluator

`ra/compile_set.py` turns the server's `r=patch` JSON into C tables (`ra/src/gen/set.c`):

- memory references: the bytes and 16-bit words read (133), each with its value and
  last frame's value;
- operands: a reference plus the part of it read (all, bit 0-7, nibble, bit count),
  value or delta, or a constant;
- conditions: a byte stream (AddSource needs no right side), per group and
  achievement;
- texts: titles and descriptions wrapped for the menu, with a phrase dictionary
  (bytes `0x80..` stand for one of up to 128 phrases), 2.9 KB instead of 4 KB.

It refuses anything `ra/src/eval.c` doesn't implement. `eval.c` follows rcheevos 12
(`trigger.c`, `condset.c`) for the features the set uses: AddSource, SubSource,
AndNext, OrNext, ResetNextIf, AddHits, SubHits, ResetIf, Measured, Trigger, hit
counts, alt groups, and the WAITING state (a trigger that is true when it is
activated fires only after it has been false once). rcheevos tests the conditions of
a group in a different order (ResetIf first); without PauseIf the result is the
same.

Two shortcuts keep the cost down, both exact:

- an achievement without hit counts, ResetIf, AddHits or ResetNextIf ("pure", 62 of
  63) depends only on this frame's values and deltas, so testing stops at its first
  false condition (or first true alt group);
- when no memory reference changed in this frame or the last, every pure
  achievement's result is the same as last frame, so they are skipped.

On Beetle, evaluation takes about 5 hblanks per vblank on average (2% of a frame),
22-26 on frames where something changed (`ra_cost` / `ra_cost_max`, root counter 1).

`ra/host/diff.c` runs the tables against stock rcheevos frame by frame on random
RAM steered toward one achievement per session (its operands get the constants they
are compared with, values are held for hit counts and nudged for deltas). The
trigger state of every achievement must match every frame:

```sh
sh ra/host/build.sh                                  # w64devkit gcc, $RCHEEVOS = rcheevos 12
ra/host/diff.exe ra/src/gen/set.txt 3000 3000 11     # sessions, frames, seed
```

A typical run triggers 59-61 of the 63 achievements about 2900 times; the others
have the same structure (sums of chest bits) and fire with other seeds.

### Hooks

| Site | Original | Now |
|---|---|---|
| `0x80011764` (vblank handler, every vblank) | `jal 0x80010EB0` (frame counter) | `ra_vblank`: the call, evaluate, popup, card write |
| `0x80010278` (boot) | `jal 0x8007C180` (memory card module init) | `ra_boot`: the call, read/make the file |
| `0x8005345C` (field menu) | the last item's text call | `ra_items`: the call, then "Achievements" |
| `0x8004F4BC` (field menu dispatch) | branch to the loop end / save anywhere's handler | trampoline (`0x8003C200`, end of save anywhere's cave) → `menu_choice` |
| `0x8005338C` / `0x80053390` | field menu window width 10 / height | 15 / +2 |
| 7 + 7 calls | `jal 0x8007C560` / `jal 0x8007C6F4` (the game's card events open / close) | `ra_card_open` / `ra_card_close`: no card writes of ours meanwhile |

The vblank handler runs on the main thread (`wait()` calls it after each `VSync`),
so it can use the game's window functions:

| Function | Address |
|---|---|
| open window `(x, y, w, h, 0, 0)` → handle | `0x8004673C` |
| write text `(handle, col, row, text, colour)` | `0x80047330` |
| clear (border and blanks) `(handle, 0)` | `0x80046A18` |
| free `(handle)` | `0x80046928` |
| mark dirty (the renderer only redraws window cells then) | `0x80046FEC` |
| window table (16 × 12 bytes: cells, w, h, x, y, ...) | `0x800FC580` |
| sound `(id, volume)`: 0 cursor, 2 cancel, 0xE confirm | `0x800A8DA4` |

Windows must stay within rows 1..26 and columns 1..39: the renderer composes them
into a cell map at `0x800FD900..0x800FE600` without clipping, and past it are the
window heap pointer and the field objects. Text colours: 0 white, 1 red, 2 gold,
3 lilac grey, 4 light grey, 5 orange, 6 blue, 7 black. The font draws `*` as a cross.

The popup waits while no window renderer callback is active (loading, movies), and
frees its window only if the window table entry is still the one it made.

### Memory card

The file is made with BIOS `open` (create, 1 block) and `write`: a 0x200-byte header
(`SC`, one icon frame, Shift-JIS title, palette and icon) and our block in the 5th
sector (offset 0x200): `"BBAC"`, count, version, the bits, a checksum.

On an unlock, `ra_vblank` finds the file's first sector with `firstfile` (the card
may have been swapped) and writes that sector with the BIOS's queued `_card_write`
(B(4Eh)), which returns at once, while the game goes on. No write starts while the
game's card events are open or for 30 vblanks after; a game card access waits for
a write of ours that just started. Without a card or a free block it tries three
times, ten seconds apart, and again after the next game save or load.

## Building

The PS1 code is C, compiled with `mipsel-linux-gnu-gcc` in a docker image in WSL
(`ra/docker/Dockerfile`; image name `re2-mipsel` by default, `RA_DOCKER_IMAGE` to
change it):

```sh
wsl -d Ubuntu-24.04 -- docker build -t re2-mipsel ra/docker
```

`ra/src/gen/set.c` is in the repository. To rebuild it from a newer revision of the
set, put the server's `r=patch` response for game 11415 (needs a logged-in account)
in `work/ra/ra_11415_patch.json`; `achievements.py` compiles it on every build.

`--no-achievements` builds without any of this (the exe stays the same size and in
place).

## Tests

- `debug/ach_test.py [cue] [card]`: makes the file, forces "Rise of the Hero", checks
  the popup, the immediate card write, the list, and the reload after a reboot.
- `debug/ach_soak.py`: random play (field, menus, battles, saves, world map),
  checks for freezes and for writes into our code and tables.
- `debug/ramfree.py` / `ramfree_sum.py`: the RAM survey.
