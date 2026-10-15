# MapleStory DS — native PC port

See `DESIGN.md` for the architecture. In short: the game's ARM9 code is recompiled ahead of time
into C (`recomp/pcode2c.py`, from Ghidra P-code), compiled natively, and run against the melonDS
hardware model (graphics, sound, DMA, timers, cart, ARM7). The frontend adds MapleStory-style
rebindable controls.

## Status

* Boots natively and plays through the intro: opening movie, title, New Data, Minerva's quiz,
  name entry, signature, saving, and into the first stage (East Perion) with the tutorial
  dialogue, HUD, movement and combat. Screens match the reference emulator.
* About 17,500 functions are recompiled (static ARM9, ITCM, all 107 overlays).
* Run in the built-in interpreter instead of natively:
  * the Mobiclip movie decoder (hand-written ARM copied into ITCM; its custom calling
    conventions don't survive function-level recompilation yet), about 2.5× real time;
  * the anti-tamper overlay 107, which decrypts its own code at runtime;
  * any code the recompiler missed (logged to `recomp.log` as `no recompiled code at …`).
* Save states (F5/F9) only work with `--interp`; the game's own save works in both modes.
* Only the intro and first stage have been played through automatically so far.

## Build

```
port/scripts/setup.sh          # once: MSYS2 packages, melonDS 1.1 source + patches
python tools/extract_all.py    # once: unpack the Japanese ROM into extracted/
port/recomp/import.sh          # once (~5 min): Ghidra analysis of all code
port/recomp/regen.sh           # export P-code and generate build/gen/*.c
port/scripts/build.sh          # build build/port/bin/MapleStoryDS.exe
```

Run `MapleStoryDS.exe` next to (or pointed at) `MapleStory DS (English).nds`.
`--interp` runs the ARM9 in the melonDS interpreter instead (reference mode).

## Testing and debugging tools

* `--test-script FILE`: headless run with scripted input (`wait`, `press`, `hold`, `release`,
  `touch`, `shot`, `until X Y RRGGBB`, `pressuntil KEY X Y RRGGBB`). Uses its own save file.
* `MSDS_TRACE=file`: log every function entry (both modes); compare with
  `tools/tracediff.py interp.trace recomp.trace [--from ADDR:LR] [--strict]`.
* `MSDS_WATCH=addr[:len]`: log writes to guest memory with the current function and call stack.
* `MSDS_DUMP_AT=fn:lr:n`: dump main RAM at the n-th call of a function (both modes).
* `MSDS_INTERP_FN=lo-hi,…` (+ `MSDS_INTERP_OV=id`): run chosen recompiled functions in the
  interpreter, e.g. to bisect a recompiler bug with `tools/bisect_interp.py`.
