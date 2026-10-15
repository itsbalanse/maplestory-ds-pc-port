// On-screen button prompts that follow the player's bindings and active device (keyboard or
// controller): game text tags (via recomp::setTagReplacements) and the HUD's button icons.
#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include "input.h"

// The DS buttons the game shows prompts for. UpL/UpY/UpX are skill slots 4-6 (Up + button).
enum class Role { A, B, X, Y, L, R, Up, Down, Left, Right, Start, Select, UpL, UpY, UpX, Count };

// One visual element of a prompt.
struct Chip {
    enum Kind { Keycap, Round, PSShape, DPad, Plus, UpArrow } kind;  // UpArrow: HUD only
    std::string text;  // Keycap: label (upper case); Round: letter
    int sym = -1;      // Keycap arrow / DPad direction: 0 left 1 right 2 up 3 down; PSShape: 0 cross 1 circle 2 square 3 triangle
};
using Label = std::vector<Chip>;

class Prompts {
public:
    explicit Prompts(Input& in) : in_(in) {}
    // Call once per frame; pushes new text prompts to the game when bindings or device change.
    // Returns true when the prompts changed.
    bool update();
    // How to show `r` on the active device. menu=true prefers menu actions (Confirm/Cancel) for A/B.
    Label label(Role r, bool menu = false) const;
    Device device() const { return in_.device(); }

    void setEnabled(bool on) { if (on != enabled_) { enabled_ = on; version_ = 0; } }
    bool enabled() const { return enabled_; }

    static std::u16string toGlyphs(const Label& l);  // game-font encoding (tools/promptfont.py)
    static std::string describe(const Label& l);     // plain text, for logs/tests

private:
    Label fromBinding(const Binding& b) const;
    Input& in_;
    uint32_t version_ = 0;
    bool enabled_ = true;
};
