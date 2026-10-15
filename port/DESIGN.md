# MapleStory DS — native PC port design

Goal: run MapleStory DS on Windows as a native program. The game's own code is translated ahead
of time into C (static recompilation), compiled with a normal PC compiler, and connected to a
reimplementation of the DS hardware. Controls follow modern MapleStory (Alt jump, Ctrl attack,
fully rebindable).

## Layers

```
 ┌──────────────────────────────────────────────────────────────┐
 │ frontend (SDL2): window + screen layouts, audio out,          │
 │   input mapping (keyboard/mouse/gamepad), keybind editor UI   │
 ├──────────────────────────────────────────────────────────────┤
 │ runtime: guest context, memory fast paths, dispatcher,        │
 │   BIOS SWI HLE, IRQ delivery, guest threads on host fibers,   │
 │   overlay tracking, function overrides (text word-wrap, …)    │
 ├──────────────────────────────────────────────────────────────┤
 │ recompiled game code (generated C)                            │
 │   ARM9 static + ITCM/DTCM autoloads + 108 overlays            │
 ├──────────────────────────────────────────────────────────────┤
 │ DS hardware model: melonDS components (GPL-3.0)               │
 │   2D engines, 3D engine, SPU, DMA, timers, IPC, cart, RTC,    │
 │   ARM7 (sound/touch driver; interpreted for now)              │
 └──────────────────────────────────────────────────────────────┘
```

## Execution model

* melonDS' `NDS::RunFrame` loop stays the master clock. Where it would call
  `ARM9.Execute()`, the runtime switches to the **guest fiber**, which runs recompiled code
  until `ARM9Timestamp >= ARM9Target`, then switches back so timers, DMA, GPU and the ARM7
  advance exactly as in the emulator.
* Recompiled code charges approximate cycle costs per basic block and checks the target at
  block ends (loops, calls, returns). That check is also where pending IRQs are taken.
* Guest registers live in melonDS' `ARMv5` object (`R[16]`, `CPSR`, banked registers), so
  savestates, IRQ entry (`TriggerIRQ`) and CP15 stay compatible with the emulator.

## Recompiler (`port/recomp/`, Python → C)

* Decodes ARMv5TE ARM and Thumb code: data processing with all shifter forms and flags,
  multiplies (incl. long/halfword DSP variants), Q-arithmetic, CLZ, all load/store forms,
  LDM/STM, SWP, B/BL/BX/BLX, MRS/MSR, MCR/MRC (CP15), SWI, PLD.
* One C function per guest function; intra-function branches become `goto`; direct calls
  become C calls; returns become C returns. Conditional execution and flags are emitted
  as plain C so the compiler drops dead flag computation.
* Indirect branches/calls (`BX reg`, `BLX reg`, `LDR pc`, `POP {pc}` with a non-LR value,
  vtables, jump tables) go through a dispatcher: address → host function. Jump tables are
  recognised statically; unknown targets are logged so they can be added.
* Hand-written assembly with its own calling conventions (the Mobiclip movie decoder) is
  emitted as one C function over the whole code image: every instruction is a label, branches
  and calls inside it are gotos, and indirect jumps/returns go through one switch. Only
  transfers that leave the image use the call/return protocol above.
* Function discovery: Ghidra's function list as seeds, then recursive descent (BL targets,
  literal-pool code pointers, vtables), per code region (static, ITCM, DTCM, each overlay).
* Overlays share load addresses, so each overlay is compiled separately; the runtime hooks
  `FS_LoadOverlay`/`FS_UnloadOverlay` to know which overlay occupies each region and the
  dispatcher picks the matching function.

## Runtime services

* **Memory:** inline fast paths for main RAM, ITCM, DTCM; everything else goes to melonDS'
  ARM9 bus handlers (I/O registers, VRAM, palettes, OAM…).
* **BIOS:** SWIs are implemented in C (Div, Sqrt, CpuSet, CpuFastSet, LZ77/RL/Huffman
  decompression, IntrWait, VBlankIntrWait, Halt, GetCRC16, …).
* **IRQs:** taken at block-end checks: bank registers like the CPU, run the BIOS IRQ
  trampoline in C, which calls the game's handler (pointer at DTCM+0x3FFC), then return.
* **Threads:** the Nitro OS thread switches (`OS_SaveContext`/`OS_LoadContext` and the IRQ
  reschedule path) are overridden. Each guest thread runs on its own host fiber, so a
  setjmp/longjmp-style context switch becomes a fiber switch.
* **Overrides:** any guest function can be replaced by hand-written C. Used for the
  anti-tamper checksums, the text renderer (word-wrap for English) and quality-of-life
  improvements.

## Frontend

* SDL2 window, integer or smooth scaling, layouts: stacked, side by side, large top screen.
* Mouse on the bottom screen acts as the stylus.
* Input actions are bound to keys or gamepad buttons in `keybinds.ini` and an in-game editor
  (F1). Defaults follow modern MapleStory:

| Action | DS input | Default keys |
|---|---|---|
| Move / climb | D-pad | Arrow keys |
| Jump | B | Alt |
| Attack | A | Ctrl |
| Guard / Backstep / Teleport | R | Shift |
| Skill 1, 2, 3 | L, Y, X | A, S, D |
| Skill 4, 5, 6 | Up+L, Up+Y, Up+X | Z, X, C |
| Talk / portal | Up | Space |
| Menu | START | Esc |
| Confirm / Cancel | A / B | Enter / Backspace |
| Select | SELECT | Tab |

## Milestones

1. Frontend on the melonDS core with both CPUs interpreted: window, audio, controls,
   keybind editor. (The game is playable on PC with the new controls; the CPU is still
   emulated.)
2. Recompiler emits C for the ARM9 static binary; the runtime runs it in place of the ARM9
   interpreter; boots to the title screen.
3. Overlays, threads and IRQs complete; the whole game runs recompiled. Reference runs from
   `tools/dsharness` are compared frame by frame to find divergences.
4. Overrides: word-wrapping text renderer, widescreen/HD options, ARM7 HLE or recompilation.

## Licensing

The port links melonDS components, so the port's source is GPL-3.0. Game data is loaded at
runtime from the user's own ROM and is never distributed with the program.
