// Public interface of the recompiled-code runtime.
#pragma once
#include <cstdint>

namespace melonDS { class NDS; }

namespace recomp {
bool available();                                 // generated code linked in?
void attach(melonDS::NDS* nds, uint32_t entry);   // run ARM9 as recompiled code from `entry`
void detach();                                    // back to the interpreter
bool active();
void dumpStats();
void traceStart(const char* path, bool interpreter);  // log every function entry
void traceStop();
}
