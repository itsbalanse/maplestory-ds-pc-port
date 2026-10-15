# MapleStory DS — native PC port

See `DESIGN.md` for the architecture. In short: the game's ARM9 code is recompiled ahead of time
into C (`recomp/pcode2c.py`, from Ghidra P-code), compiled natively, and run against the melonDS
hardware model (graphics, sound, DMA, timers, cart, ARM7). The frontend adds MapleStory-style
rebindable controls.

## Status

* Boots natively and plays through the intro: opening movie, title, New Data, Minerva's quiz,
  name entry, signature, saving, and into the first stage (East Perion) with the tutorial
  dialogue, HUD, movement and combat. Screens match the reference emulator.
* About 17,500 functions are recompiled (static ARM9, ITCM, all 107 overlays). The Mobiclip
  movie decoder (hand-written ARM copied into ITCM) is emitted as a single C function over its
  whole image, so its own calling conventions stay inside one C frame.
* Run in the built-in interpreter instead of natively:
  * the anti-tamper overlay 107, which decrypts its own code at runtime;
  * any code the recompiler missed (logged to `recomp.log` as `no recompiled code at …`).
* Save states (F5/F9) only work with `--interp`; the game's own save works in both modes.
* Only the intro and first stage have been played through automatically so far.

## Controls and button prompts

* Everything is rebindable in game (F1): keyboard keys, mouse buttons (right, middle, side; left
  click is the touch screen) and controller buttons/sticks/triggers. Bindings live in
  `keybinds.ini`. Defaults follow modern MapleStory: Alt jump, Ctrl attack, Shift guard,
  A/S/D and Z/X/C skills, arrows to move, Space talk, Esc menu.
* The game shows the keys you actually use. It switches to controller prompts when a controller
  is used (and when one is connected at start), and back to keyboard prompts on key or mouse
  input. Xbox, PlayStation and Nintendo controllers get their own button names and symbols.
  * Text: the port overrides the game's tag expansion (`FUN_02017a70`, `runtime/tagprompts.cpp`)
    and turns `\[A\]`, `\[START\]` etc. into keycap / button glyphs that `tools/promptfont.py`
    adds to the font. The English text reserves room for the widest keycap when wrapping.
  * HUD and menus (skill bar, START/SELECT pills also while pressed, dialogue and menu A icons,
    Skills and Map screens, list paging L/R tabs, the controller pictures of the Hint pages and
    the DS console of the prologue book): `src/hudprompts.cpp` finds the DS icons in each
    finished frame by pixel template (`tools/prompt_templates.py`, cut from test shots or straight
    from the English ROM's graphics; also during fades, in 3D-drawn colours, and in any palette
    for the small menu icons) and redraws them at DS resolution in the game's colours. It costs
    about 1 ms per frame.
  * F4 switches back to the original DS icons (`pc_prompts` in `settings.ini`).
* Tests: `--device keyboard|pad|ps|switch` fixes the prompt device; `--prompt-image IN OUT`
  redraws the icons of a 256x384 screenshot (and prints the time per frame).

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
  `rawshot NAME` saves the frame without the PC button prompts (for cutting icon templates).
  `gpudump NAME` writes both 2D engines' VRAM, palettes, OAM and registers; decode with
  `tools/gpudump.py NAME.gpu OUTDIR [x0 y0 x1 y1 screen]` (renders layers, lists what covers a rectangle).
  `lua CODE` runs Lua in the game through its own script engine between frames (native and, with the
  pure interpreter, `--interp`), e.g. `lua ChangeStage('MP030101')` to warp; `luawait [N]` fails if the
  game stops running its frame loop; `ramdump NAME` writes main RAM.
* `tools/stage_sweep.py SAVE OUTDIR [--interp] [--from-results OLD/results.json]`: whole-game test.
  Warps to every stage for every class that has scripts there (808 runs), plays a little, and flags
  crashes, hangs, black screens and code the recompiler missed; `--interp` runs the same in the
  reference interpreter to tell port bugs from the game's own behaviour.
* `tools/find_switch_tables.py`: Thumb switch tables whose case blocks Ghidra did not disassemble
  (fed to `SeedSwitchTargets.java` by `import.sh`; should report 0 missing).
* `MSDS_INTERP_LOG=addr:n`: log the first n instructions of an interpreter fallback starting at addr.
* `MSDS_TRACE=file`: log every function entry (both modes); compare with
  `tools/tracediff.py interp.trace recomp.trace [--from ADDR:LR] [--strict] [--keys addr,lr]`.
* `MSDS_WATCH=addr[:len]`: log writes to guest memory with the current function and call stack.
* `MSDS_DUMP_AT=fn:lr:n`: dump main RAM at the n-th call of a function (both modes).
* `MSDS_INTERP_FN=lo-hi,…` (+ `MSDS_INTERP_OV=id`): run chosen recompiled functions in the
  interpreter, e.g. to bisect a recompiler bug with `tools/bisect_interp.py`.
* `MSDS_ITRACE=file[:count]`: log every movie decoder instruction (pc, r0-r14, NZCV), in
  `--interp` mode and from a native build configured with `-DMSDS_IMG_STEP=ON`; compare with
  `tools/itracediff.py interp.itrace native.itrace` to find the first instruction that differs.
