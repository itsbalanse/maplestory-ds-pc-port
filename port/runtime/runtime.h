// Public interface of the recompiled-code runtime.
#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace melonDS { class NDS; }

namespace recomp {
bool available();                                 // generated code linked in?
void attach(melonDS::NDS* nds, uint32_t entry);   // run ARM9 as recompiled code from `entry`
void detach();                                    // back to the interpreter
bool active();
void dumpStats();
void traceStart(const char* path, bool interpreter);  // log every function entry
void traceStop();

// Save states. The recompiled code keeps each guest thread's call chain on a host stack, so a
// state can only be taken when every thread can be rebuilt from guest memory: the CPU waits for
// an interrupt in the idle thread and every other thread is parked in OS_SaveContext. That is the
// case at the end of most frames. canSaveState() says whether now is such a moment (or why not).
bool canSaveState(std::string* why = nullptr);
std::vector<uint8_t> saveState();                 // runtime part of a state (CPU registers etc.)
bool loadState(const uint8_t* data, size_t len);  // after the hardware state has been loaded

// Busy scenes never idle at a frame's end; their states are taken instead when the main thread
// enters OS_WaitVBlankIntr (once per frame, all other threads parked). `write` is called right
// there with the runtime part and must save the hardware state with it. Result: 0 still waiting,
// 1 saved, -1 the writer failed.
void requestSaveAtCall(std::function<bool(const std::vector<uint8_t>&)> write);
int saveAtCallResult();
void cancelSaveAtCall();
}
