#include "input.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>

static const ActionInfo kActions[(int)Act::Count] = {
    {"Left", "Move left", "Movement", ds::LEFT, false},
    {"Right", "Move right", "Movement", ds::RIGHT, false},
    {"Up", "Climb up / look up", "Movement", ds::UP, false},
    {"Down", "Climb down / crouch", "Movement", ds::DOWN, false},
    {"Jump", "Jump", "Combat", ds::B, false},
    {"Attack", "Attack", "Combat", ds::A, false},
    {"ClassAction", "Guard / Backstep / Teleport", "Combat", ds::R, false},
    {"Skill1", "Skill slot 1 (L)", "Skills", ds::L, false},
    {"Skill2", "Skill slot 2 (Y)", "Skills", ds::Y, false},
    {"Skill3", "Skill slot 3 (X)", "Skills", ds::X, false},
    {"Skill4", "Skill slot 4 (Up+L)", "Skills", ds::L, true},
    {"Skill5", "Skill slot 5 (Up+Y)", "Skills", ds::Y, true},
    {"Skill6", "Skill slot 6 (Up+X)", "Skills", ds::X, true},
    {"Talk", "Talk to NPC / enter portal", "Interface", ds::UP, false},
    {"Menu", "Main menu", "Interface", ds::START, false},
    {"Confirm", "Confirm", "Interface", ds::A, false},
    {"Cancel", "Cancel / back", "Interface", ds::B, false},
    {"Select", "Select button", "Interface", ds::SELECT, false},
    {"KeybindEditor", "Open key bindings", "Program", 0, false},
    {"Fullscreen", "Toggle fullscreen", "Program", 0, false},
    {"NextLayout", "Change screen layout", "Program", 0, false},
    {"QuickSave", "Quick save state", "Program", 0, false},
    {"QuickLoad", "Quick load state", "Program", 0, false},
    {"FastForward", "Fast forward (hold)", "Program", 0, false},
    {"Pause", "Pause", "Program", 0, false},
    {"Screenshot", "Screenshot", "Program", 0, false},
    {"Mute", "Mute / unmute sound", "Program", 0, false},
};

const ActionInfo& actionInfo(Act a) { return kActions[(int)a]; }

std::string Binding::name() const {
    switch (type) {
    case Key: return std::string("key:") + SDL_GetScancodeName((SDL_Scancode)code);
    case PadButton: return std::string("pad:") + SDL_GameControllerGetStringForButton((SDL_GameControllerButton)code);
    case PadAxis: return std::string("pad:") + (dir < 0 ? "-" : "+") + SDL_GameControllerGetStringForAxis((SDL_GameControllerAxis)code);
    }
    return "?";
}

static bool parseBinding(const std::string& s, Binding& b) {
    if (s.rfind("key:", 0) == 0) {
        SDL_Scancode sc = SDL_GetScancodeFromName(s.substr(4).c_str());
        if (sc == SDL_SCANCODE_UNKNOWN) return false;
        b = {Binding::Key, (int)sc, 0};
        return true;
    }
    if (s.rfind("pad:", 0) == 0) {
        std::string n = s.substr(4);
        if (!n.empty() && (n[0] == '+' || n[0] == '-')) {
            SDL_GameControllerAxis ax = SDL_GameControllerGetAxisFromString(n.substr(1).c_str());
            if (ax == SDL_CONTROLLER_AXIS_INVALID) return false;
            b = {Binding::PadAxis, (int)ax, n[0] == '-' ? -1 : 1};
            return true;
        }
        SDL_GameControllerButton bt = SDL_GameControllerGetButtonFromString(n.c_str());
        if (bt == SDL_CONTROLLER_BUTTON_INVALID) return false;
        b = {Binding::PadButton, (int)bt, 0};
        return true;
    }
    return false;
}

Input::Input() { setDefaults(); }

void Input::setDefaults() {
    for (auto& v : binds_) v.clear();
    auto K = [&](Act a, SDL_Scancode s) { binds_[(int)a].push_back({Binding::Key, (int)s, 0}); };
    auto P = [&](Act a, SDL_GameControllerButton s) { binds_[(int)a].push_back({Binding::PadButton, (int)s, 0}); };
    auto X = [&](Act a, SDL_GameControllerAxis ax, int d) { binds_[(int)a].push_back({Binding::PadAxis, (int)ax, d}); };
    // Modern MapleStory layout
    K(Act::Left, SDL_SCANCODE_LEFT); K(Act::Right, SDL_SCANCODE_RIGHT);
    K(Act::Up, SDL_SCANCODE_UP); K(Act::Down, SDL_SCANCODE_DOWN);
    K(Act::Jump, SDL_SCANCODE_LALT); K(Act::Jump, SDL_SCANCODE_RALT);
    K(Act::Attack, SDL_SCANCODE_LCTRL); K(Act::Attack, SDL_SCANCODE_RCTRL);
    K(Act::ClassAction, SDL_SCANCODE_LSHIFT); K(Act::ClassAction, SDL_SCANCODE_RSHIFT);
    K(Act::Skill1, SDL_SCANCODE_A); K(Act::Skill2, SDL_SCANCODE_S); K(Act::Skill3, SDL_SCANCODE_D);
    K(Act::Skill4, SDL_SCANCODE_Z); K(Act::Skill5, SDL_SCANCODE_X); K(Act::Skill6, SDL_SCANCODE_C);
    K(Act::Talk, SDL_SCANCODE_SPACE);
    K(Act::Menu, SDL_SCANCODE_ESCAPE);
    K(Act::Confirm, SDL_SCANCODE_RETURN); K(Act::Confirm, SDL_SCANCODE_KP_ENTER);
    K(Act::Cancel, SDL_SCANCODE_BACKSPACE);
    K(Act::Select, SDL_SCANCODE_TAB);
    K(Act::KeybindEditor, SDL_SCANCODE_F1);
    K(Act::Fullscreen, SDL_SCANCODE_F11);
    K(Act::NextLayout, SDL_SCANCODE_F2);
    K(Act::QuickSave, SDL_SCANCODE_F5);
    K(Act::QuickLoad, SDL_SCANCODE_F9);
    K(Act::FastForward, SDL_SCANCODE_GRAVE);
    K(Act::Pause, SDL_SCANCODE_PAUSE);
    K(Act::Screenshot, SDL_SCANCODE_F12);
    K(Act::Mute, SDL_SCANCODE_F3);
    // Gamepad: face buttons in the same positions as on the DS
    P(Act::Left, SDL_CONTROLLER_BUTTON_DPAD_LEFT); P(Act::Right, SDL_CONTROLLER_BUTTON_DPAD_RIGHT);
    P(Act::Up, SDL_CONTROLLER_BUTTON_DPAD_UP); P(Act::Down, SDL_CONTROLLER_BUTTON_DPAD_DOWN);
    X(Act::Left, SDL_CONTROLLER_AXIS_LEFTX, -1); X(Act::Right, SDL_CONTROLLER_AXIS_LEFTX, 1);
    X(Act::Up, SDL_CONTROLLER_AXIS_LEFTY, -1); X(Act::Down, SDL_CONTROLLER_AXIS_LEFTY, 1);
    P(Act::Jump, SDL_CONTROLLER_BUTTON_A);
    P(Act::Attack, SDL_CONTROLLER_BUTTON_B);
    P(Act::Skill2, SDL_CONTROLLER_BUTTON_X);
    P(Act::Skill3, SDL_CONTROLLER_BUTTON_Y);
    P(Act::Skill1, SDL_CONTROLLER_BUTTON_LEFTSHOULDER);
    P(Act::ClassAction, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER);
    P(Act::Menu, SDL_CONTROLLER_BUTTON_START);
    P(Act::Select, SDL_CONTROLLER_BUTTON_BACK);
    X(Act::FastForward, SDL_CONTROLLER_AXIS_TRIGGERRIGHT, 1);
}

void Input::addBinding(Act a, const Binding& b) {
    for (auto& v : binds_) v.erase(std::remove(v.begin(), v.end(), b), v.end());
    binds_[(int)a].push_back(b);
}

void Input::clearBindings(Act a) { binds_[(int)a].clear(); }

bool Input::load(const std::string& path) {
    std::ifstream f(path);
    if (!f) return false;
    std::map<std::string, int> ids;
    for (int i = 0; i < (int)Act::Count; i++) ids[kActions[i].id] = i;
    std::string line;
    bool any = false;
    bool seen[(int)Act::Count] = {};
    setDefaults();
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#' || line[0] == ';' || line[0] == '[') continue;
        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        auto trim = [](std::string s) {
            s.erase(0, s.find_first_not_of(" \t\r"));
            s.erase(s.find_last_not_of(" \t\r") + 1);
            return s;
        };
        std::string k = trim(line.substr(0, eq)), v = trim(line.substr(eq + 1));
        auto it = ids.find(k);
        if (it == ids.end()) continue;
        // actions missing from the file (e.g. added in a newer version) keep their defaults
        if (!seen[it->second]) { binds_[it->second].clear(); seen[it->second] = true; }
        any = true;
        std::stringstream ss(v);
        std::string item;
        while (std::getline(ss, item, ',')) {
            Binding b;
            if (parseBinding(trim(item), b)) binds_[it->second].push_back(b);
        }
    }
    return any;
}

bool Input::save(const std::string& path) const {
    std::ofstream f(path);
    if (!f) return false;
    f << "# MapleStory DS key bindings. Edit here or in game with F1.\n"
         "# Format: Action = key:<SDL key name>, pad:<button>, pad:+axis / pad:-axis\n";
    const char* group = "";
    for (int i = 0; i < (int)Act::Count; i++) {
        if (strcmp(group, kActions[i].group) != 0) { group = kActions[i].group; f << "\n[" << group << "]\n"; }
        f << kActions[i].id << " = ";
        for (size_t j = 0; j < binds_[i].size(); j++) f << (j ? ", " : "") << binds_[i][j].name();
        f << "\n";
    }
    return true;
}

void Input::handleEvent(const SDL_Event& e) {
    switch (e.type) {
    case SDL_KEYDOWN: case SDL_KEYUP:
        if (e.key.keysym.scancode < SDL_NUM_SCANCODES) keyDown_[e.key.keysym.scancode] = e.type == SDL_KEYDOWN;
        break;
    case SDL_CONTROLLERBUTTONDOWN: case SDL_CONTROLLERBUTTONUP:
        if (e.cbutton.button < SDL_CONTROLLER_BUTTON_MAX) padBtn_[e.cbutton.button] = e.type == SDL_CONTROLLERBUTTONDOWN;
        break;
    case SDL_CONTROLLERAXISMOTION:
        if (e.caxis.axis < SDL_CONTROLLER_AXIS_MAX) padAxis_[e.caxis.axis] = e.caxis.value;
        break;
    case SDL_CONTROLLERDEVICEADDED:
        if (!pad) pad = SDL_GameControllerOpen(e.cdevice.which);
        break;
    case SDL_CONTROLLERDEVICEREMOVED:
        if (pad && SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(pad)) == e.cdevice.which) {
            SDL_GameControllerClose(pad); pad = nullptr;
            memset(padBtn_, 0, sizeof padBtn_); memset(padAxis_, 0, sizeof padAxis_);
        }
        break;
    case SDL_WINDOWEVENT:
        if (e.window.event == SDL_WINDOWEVENT_FOCUS_LOST) releaseAll();
        break;
    }
}

void Input::releaseAll() {
    memset(keyDown_, 0, sizeof keyDown_);
    memset(padBtn_, 0, sizeof padBtn_);
    memset(padAxis_, 0, sizeof padAxis_);
}

bool Input::active(Act a) const {
    for (auto& b : binds_[(int)a]) {
        switch (b.type) {
        case Binding::Key: if (keyDown_[b.code]) return true; break;
        case Binding::PadButton: if (padBtn_[b.code]) return true; break;
        case Binding::PadAxis: if (padAxis_[b.code] * b.dir > 16000) return true; break;
        }
    }
    return false;
}

void Input::update() {
    for (int i = 0; i < (int)Act::Count; i++) cur_[i] = active((Act)i);
}

uint32_t Input::dsKeyMask() {
    uint32_t down = 0;
    for (int i = 0; i < (int)Act::Count; i++) {
        const auto& info = kActions[i];
        if (!info.dsMask || !cur_[i]) { comboFrames_[i] = 0; continue; }
        if (info.upCombo) {
            // Skills 4-6: hold Up for one frame first so the game sees Up+button.
            down |= ds::UP;
            if (comboFrames_[i]++ >= 1) down |= info.dsMask;
        } else {
            down |= info.dsMask;
        }
    }
    // Opposite directions cancel out (the DS d-pad can't press both).
    if ((down & ds::LEFT) && (down & ds::RIGHT)) down &= ~(ds::LEFT | ds::RIGHT);
    if ((down & ds::UP) && (down & ds::DOWN)) down &= ~ds::DOWN;
    return ~down & 0xFFF;
}

bool Input::pressed(Act a) const { return cur_[(int)a] && !prev_[(int)a]; }
bool Input::held(Act a) const { return cur_[(int)a]; }

void Input::endFrame() { memcpy(prev_, cur_, sizeof prev_); }
