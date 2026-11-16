# MapleStory DS — native PC port

An unofficial, fan-made native Windows port of *MapleStory DS* (Japan, YMPJ). The game's ARM9 code is
recompiled ahead of time from Ghidra P-code into C, compiled natively and run against the melonDS
hardware model. The port adds modern MapleStory controls (Alt jump, Ctrl attack), fully rebindable
keyboard, mouse and controller input, PC button prompts, and save states (F5/F9).

**No game data is included.** This repository holds only the recompiler, runtime, frontend and
tools. You need your own legally obtained copy of the game. The Japanese script, the graphics and
anything else cut from the ROM are not distributed, so the English translation text and the HUD icon
templates (`port/src/prompt_templates.inc`, made by `tools/prompt_templates.py`) are not part of
this repository. Without the templates the port builds and runs but keeps the DS icons in the HUD.

* `port/` — the PC port: recompiler (`recomp/`), runtime (`runtime/`), frontend (`src/`).
  Build instructions, status and debugging tools are in [`port/README.md`](port/README.md);
  the architecture is described in [`port/DESIGN.md`](port/DESIGN.md).
* `tools/` — ROM unpacking and repacking, text and graphics tools, Ghidra scripts, test tools.
* `translation/` — how the English translation workflow works.

MapleStory is a trademark of NEXON Korea Corporation. This project is not affiliated with or
endorsed by NEXON or Nintendo.
