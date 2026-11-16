// Scripted input for automated tests (--test-script FILE), same commands as tools/dsharness:
//   wait N | press KEY [N] | hold KEY | release KEY | touch X Y [N] | shot NAME
//   touchdown X Y | touchup                 touch and hold until touchup (shots can be taken meanwhile)
//   rawshot NAME                           like shot, without the PC button prompts (the game's own icons)
//   lua CODE                               run Lua in the game (native build), e.g. lua ChangeStage('MP030101')
//   ramdump NAME                           write main RAM (4 MB) to NAME.ram
//   savestate NAME [TIMEOUT]               save NAME.state at the next safe moment (fails after TIMEOUT frames)
//   loadstate NAME                         load NAME.state (fails the script if it cannot)
//   luawait [TIMEOUT]                      wait until queued Lua has run; fails if the game never
//                                          reaches its frame loop in time (hang, default 1800 frames)
//   until X Y RRGGBB [TIMEOUT]             wait until the pixel (X, Y on the 256x384 stack) has that colour
//   pressuntil KEY X Y RRGGBB [TIMEOUT]    press KEY every 40 frames until that pixel colour shows
// KEY: A B SELECT START RIGHT LEFT UP DOWN R L X Y
#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

class TestScript {
public:
    bool load(const std::string& path);
    // Advance one frame. Fills the DS key mask (active-low) and touch state, and returns the
    // names of screenshots to take after this frame. done() becomes true when the script ends.
    void frame(uint32_t& keyMask, bool& touching, int& tx, int& ty, std::vector<std::string>& shots);
    std::function<uint32_t(int, int)> pixel;  // reads the current frame (0x00RRGGBB)
    std::function<bool()> luaPending;          // Lua queued but not yet run
    std::function<int(const std::string&)> saveState;   // 1 saved, 0 not possible yet, -1 error
    std::function<bool(const std::string&)> loadState;
    bool failed() const { return failed_; }
    bool done() const { return pc_ >= cmds_.size() && wait_ == 0 && !waitingPixel_ && pulseLeft_ == 0 && touchLeft_ == 0 && !luaWaitLeft_ && !saveLeft_; }

private:
    struct Cmd { std::string op; std::vector<std::string> args; std::string rest; };  // rest: text after op
    std::vector<Cmd> cmds_;
    size_t pc_ = 0;
    int wait_ = 0;
    uint32_t held_ = 0;      // bits of keys held down
    uint32_t pulse_ = 0;     // key held for the current press
    int pulseLeft_ = 0, releaseLeft_ = 0;
    bool touching_ = false;
    int tx_ = 0, ty_ = 0, touchLeft_ = 0;
    // until / pressuntil
    bool waitingPixel_ = false, failed_ = false;
    int luaWaitLeft_ = 0;
    int saveLeft_ = 0;
    std::string saveName_;
    int px_ = 0, py_ = 0, pTimeout_ = 0, pTimer_ = 0;
    uint32_t pColor_ = 0, pKey_ = 0;
};
