// Rebindable input: maps keyboard keys / gamepad buttons to DS buttons and frontend actions.
#pragma once
#include <SDL.h>
#include <cstdint>
#include <string>
#include <vector>

namespace ds {
enum Key : uint32_t {
    A = 1u << 0, B = 1u << 1, SELECT = 1u << 2, START = 1u << 3, RIGHT = 1u << 4, LEFT = 1u << 5,
    UP = 1u << 6, DOWN = 1u << 7, R = 1u << 8, L = 1u << 9, X = 1u << 10, Y = 1u << 11,
};
}

enum class Act {
    // game actions
    Left, Right, Up, Down, Jump, Attack, ClassAction,
    Skill1, Skill2, Skill3, Skill4, Skill5, Skill6,
    Talk, Menu, Confirm, Cancel, Select,
    // frontend actions
    KeybindEditor, Fullscreen, NextLayout, QuickSave, QuickLoad, FastForward, Pause, Screenshot, Mute, TogglePrompts,
    Count
};

struct ActionInfo {
    const char* id;        // config key
    const char* label;     // shown in the editor
    const char* group;
    uint32_t dsMask;       // DS buttons held while active
    bool upCombo;          // hold Up one frame before the button (skills 4-6)
};

const ActionInfo& actionInfo(Act a);

enum class Device { Keyboard, Pad };
// Face-button naming of the connected controller (SDL reports buttons by position: A = bottom).
enum class PadStyle { Xbox, PlayStation, Nintendo };

struct Binding {
    enum Type { Key, PadButton, PadAxis, Mouse } type;
    int code;   // SDL_Scancode, SDL_GameControllerButton, SDL_GameControllerAxis or SDL mouse button
    bool keyboardSide() const { return type == Key || type == Mouse; }  // keyboard & mouse vs controller
    int dir;    // axis direction (-1/+1)
    std::string name() const;
    bool operator==(const Binding& o) const { return type == o.type && code == o.code && dir == o.dir; }
};

class Input {
public:
    Input();
    void setDefaults();
    bool load(const std::string& path);
    bool save(const std::string& path) const;

    std::vector<Binding>& bindings(Act a) { return binds_[(int)a]; }
    void addBinding(Act a, const Binding& b);   // removes the same binding from other actions
    void clearBindings(Act a);

    // Event handling. Returns true if the event was consumed.
    void handleEvent(const SDL_Event& e);
    void releaseAll();

    // Per-frame: update() samples all actions; dsKeyMask() returns the DS key mask
    // (active-low, 12 bits); pressed()/held() report action state.
    void update();
    uint32_t dsKeyMask();
    bool pressed(Act a) const;       // went down this frame (frontend actions)
    bool held(Act a) const;
    void endFrame();

    SDL_GameController* pad = nullptr;
    void openPads();  // open the first connected controller (start-up)
    void setTestDevice(Device d, PadStyle s);  // headless tests: fixed device, no auto-switching

    // Which device the player is using, for on-screen prompts: the last one that produced input,
    // starting with the controller when one is connected. promptVersion() changes whenever the
    // prompts would change (device switch or new bindings).
    Device device() const { return device_; }
    PadStyle padStyle() const;
    uint32_t promptVersion() const { return promptVersion_; }
    void bindingsChanged() { promptVersion_++; }
    // First binding of `a` usable on device `d` (nullptr if none)
    const Binding* firstBinding(Act a, Device d) const;

private:
    bool active(Act a) const;
    void useDevice(Device d);
    Device device_ = Device::Keyboard;
    bool testDevice_ = false;
    PadStyle testStyle_ = PadStyle::Xbox;
    uint32_t promptVersion_ = 1;
    std::vector<Binding> binds_[(int)Act::Count];
    bool keyDown_[SDL_NUM_SCANCODES] = {};
    bool padBtn_[SDL_CONTROLLER_BUTTON_MAX] = {};
    bool mouseBtn_[8] = {};  // right, middle, side buttons (left is the touch screen)
    int padAxis_[SDL_CONTROLLER_AXIS_MAX] = {};
    bool prev_[(int)Act::Count] = {};
    bool cur_[(int)Act::Count] = {};
    int comboFrames_[(int)Act::Count] = {};
};
