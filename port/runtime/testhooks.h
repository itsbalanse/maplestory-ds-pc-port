// Test hooks into the running game (native build only): run Lua through the game's own script
// engine, e.g. ChangeStage('MP030101') to warp. Used by test scripts (`lua ...`).
#pragma once
#include <string>

namespace recomp {
// Queue a Lua chunk; it runs at the game's next per-frame vblank wait, between frames.
void queueLua(const std::string& code);
bool luaPending();
// Reference (interpreter) mode: run queued Lua the same way, via a small Thumb stub. Needs the
// pure interpreter (no JIT); chains to an instruction hook already installed (tracing).
void enableInterpLua();
}
