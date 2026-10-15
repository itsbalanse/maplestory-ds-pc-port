#include "prompts.h"
#include "tagprompts.h"

#include <cctype>
#include <cstring>

namespace {

struct RoleInfo {
    const char* tag;          // tag in game text, without brackets
    Act actions[2];           // gameplay meaning first
    Act menuActions[2];       // meaning in menus (A/B)
    uint16_t dsGlyph;         // the game's own icon, used when nothing is bound
};

constexpr Act kNone = Act::Count;
const RoleInfo kRoles[(int)Role::Count] = {
    {"A", {Act::Attack, Act::Confirm}, {Act::Confirm, Act::Attack}, 0xE000},
    {"B", {Act::Jump, Act::Cancel}, {Act::Cancel, Act::Jump}, 0xE001},
    {"X", {Act::Skill3, kNone}, {Act::Skill3, kNone}, 0xE002},
    {"Y", {Act::Skill2, kNone}, {Act::Skill2, kNone}, 0xE003},
    {"L", {Act::Skill1, kNone}, {Act::Skill1, kNone}, 0xE004},
    {"R", {Act::ClassAction, kNone}, {Act::ClassAction, kNone}, 0xE005},
    {"^", {Act::Up, Act::Talk}, {Act::Up, Act::Talk}, 0xE01B},
    {"v", {Act::Down, kNone}, {Act::Down, kNone}, 0xE01C},
    {"<", {Act::Left, kNone}, {Act::Left, kNone}, 0xE01A},
    {">", {Act::Right, kNone}, {Act::Right, kNone}, 0xE019},
    {"START", {Act::Menu, kNone}, {Act::Menu, kNone}, 0},
    {"SELECT", {Act::Select, kNone}, {Act::Select, kNone}, 0},
    {nullptr, {Act::Skill4, kNone}, {Act::Skill4, kNone}, 0},
    {nullptr, {Act::Skill5, kNone}, {Act::Skill5, kNone}, 0},
    {nullptr, {Act::Skill6, kNone}, {Act::Skill6, kNone}, 0},
};

Chip keycap(std::string t) { return {Chip::Keycap, std::move(t), -1}; }

std::string keyName(SDL_Scancode sc) {
    switch (sc) {
    case SDL_SCANCODE_LCTRL: case SDL_SCANCODE_RCTRL: return "CTRL";
    case SDL_SCANCODE_LALT: case SDL_SCANCODE_RALT: return "ALT";
    case SDL_SCANCODE_LSHIFT: case SDL_SCANCODE_RSHIFT: return "SHIFT";
    case SDL_SCANCODE_LGUI: case SDL_SCANCODE_RGUI: return "WIN";
    case SDL_SCANCODE_RETURN: case SDL_SCANCODE_RETURN2: return "ENTER";
    case SDL_SCANCODE_KP_ENTER: return "ENTER";
    case SDL_SCANCODE_ESCAPE: return "ESC";
    case SDL_SCANCODE_BACKSPACE: return "BKSP";
    case SDL_SCANCODE_DELETE: return "DEL";
    case SDL_SCANCODE_INSERT: return "INS";
    case SDL_SCANCODE_PAGEUP: return "PGUP";
    case SDL_SCANCODE_PAGEDOWN: return "PGDN";
    case SDL_SCANCODE_CAPSLOCK: return "CAPS";
    case SDL_SCANCODE_SPACE: return "SPACE";
    case SDL_SCANCODE_GRAVE: return "`";
    case SDL_SCANCODE_PRINTSCREEN: return "PRTSC";
    case SDL_SCANCODE_SCROLLLOCK: return "SCRLK";
    case SDL_SCANCODE_NUMLOCKCLEAR: return "NUMLK";
    case SDL_SCANCODE_PAUSE: return "PAUSE";
    case SDL_SCANCODE_APPLICATION: return "MENU";
    default: break;
    }
    std::string n = SDL_GetScancodeName(sc);
    if (n.rfind("Keypad ", 0) == 0) n = "NUM" + n.substr(7);
    std::string out;
    for (char ch : n)
        if (ch != ' ') out += (char)std::toupper((unsigned char)ch);
    if (out.size() > 6) out = out.substr(0, 6);
    return out.empty() ? "?" : out;
}

}  // namespace

Label Prompts::fromBinding(const Binding& b) const {
    const PadStyle st = in_.padStyle();
    if (b.type == Binding::Key) {
        switch (b.code) {
        case SDL_SCANCODE_LEFT: return {{Chip::Keycap, "", 0}};
        case SDL_SCANCODE_RIGHT: return {{Chip::Keycap, "", 1}};
        case SDL_SCANCODE_UP: return {{Chip::Keycap, "", 2}};
        case SDL_SCANCODE_DOWN: return {{Chip::Keycap, "", 3}};
        }
        return {keycap(keyName((SDL_Scancode)b.code))};
    }
    if (b.type == Binding::Mouse)
        return {keycap(b.code == SDL_BUTTON_RIGHT ? "RMB" : b.code == SDL_BUTTON_MIDDLE ? "MMB" : b.code == SDL_BUTTON_X1 ? "MB4" : "MB5")};
    const bool ps = st == PadStyle::PlayStation, nin = st == PadStyle::Nintendo;
    if (b.type == Binding::PadAxis) {
        switch (b.code) {
        case SDL_CONTROLLER_AXIS_LEFTX: return {{Chip::DPad, "", b.dir < 0 ? 0 : 1}};
        case SDL_CONTROLLER_AXIS_LEFTY: return {{Chip::DPad, "", b.dir < 0 ? 2 : 3}};
        case SDL_CONTROLLER_AXIS_RIGHTX: return {keycap("RS"), {Chip::Keycap, "", b.dir < 0 ? 0 : 1}};
        case SDL_CONTROLLER_AXIS_RIGHTY: return {keycap("RS"), {Chip::Keycap, "", b.dir < 0 ? 2 : 3}};
        case SDL_CONTROLLER_AXIS_TRIGGERLEFT: return {keycap(ps ? "L2" : nin ? "ZL" : "LT")};
        case SDL_CONTROLLER_AXIS_TRIGGERRIGHT: return {keycap(ps ? "R2" : nin ? "ZR" : "RT")};
        }
        return {keycap("AXIS")};
    }
    switch (b.code) {
    case SDL_CONTROLLER_BUTTON_A: return {ps ? Chip{Chip::PSShape, "", 0} : Chip{Chip::Round, "A", -1}};
    case SDL_CONTROLLER_BUTTON_B: return {ps ? Chip{Chip::PSShape, "", 1} : Chip{Chip::Round, "B", -1}};
    case SDL_CONTROLLER_BUTTON_X: return {ps ? Chip{Chip::PSShape, "", 2} : Chip{Chip::Round, "X", -1}};
    case SDL_CONTROLLER_BUTTON_Y: return {ps ? Chip{Chip::PSShape, "", 3} : Chip{Chip::Round, "Y", -1}};
    case SDL_CONTROLLER_BUTTON_DPAD_LEFT: return {{Chip::DPad, "", 0}};
    case SDL_CONTROLLER_BUTTON_DPAD_RIGHT: return {{Chip::DPad, "", 1}};
    case SDL_CONTROLLER_BUTTON_DPAD_UP: return {{Chip::DPad, "", 2}};
    case SDL_CONTROLLER_BUTTON_DPAD_DOWN: return {{Chip::DPad, "", 3}};
    case SDL_CONTROLLER_BUTTON_LEFTSHOULDER: return {keycap(ps ? "L1" : nin ? "L" : "LB")};
    case SDL_CONTROLLER_BUTTON_RIGHTSHOULDER: return {keycap(ps ? "R1" : nin ? "R" : "RB")};
    case SDL_CONTROLLER_BUTTON_LEFTSTICK: return {keycap(ps ? "L3" : "LS")};
    case SDL_CONTROLLER_BUTTON_RIGHTSTICK: return {keycap(ps ? "R3" : "RS")};
    case SDL_CONTROLLER_BUTTON_START: return {keycap(ps ? "OPTIONS" : nin ? "+" : "MENU")};
    case SDL_CONTROLLER_BUTTON_BACK: return {keycap(ps ? "SHARE" : nin ? "-" : "VIEW")};
    case SDL_CONTROLLER_BUTTON_GUIDE: return {keycap("HOME")};
    }
    return {keycap("?")};
}

Label Prompts::label(Role r, bool menu) const {
    const RoleInfo& ri = kRoles[(int)r];
    const Device d = in_.device();
    for (Act a : menu ? ri.menuActions : ri.actions) {
        if (a == kNone) continue;
        if (const Binding* b = in_.firstBinding(a, d)) return fromBinding(*b);
    }
    if (r == Role::UpL || r == Role::UpY || r == Role::UpX) {
        // no direct binding: Up + the slot 1-3 button, like on the DS
        Label l = label(Role::Up, menu);
        Label k = label(r == Role::UpL ? Role::L : r == Role::UpY ? Role::Y : Role::X, menu);
        if (l.empty() || k.empty()) return {};
        l.push_back({Chip::Plus, "+", -1});
        l.insert(l.end(), k.begin(), k.end());
        return l;
    }
    return {};
}

std::u16string Prompts::toGlyphs(const Label& l) {
    std::u16string s;
    for (const Chip& c : l) {
        switch (c.kind) {
        case Chip::Keycap: {
            s += u'';
            if (c.sym >= 0) {
                s += (char16_t)(0xE180 + c.sym);
            } else {
                // inner width of the label; short labels are padded to the width of the DS icons
                int w = 0;
                for (char ch : c.text) w += (ch == 'M' || ch == 'W') ? 6 : (ch == 'N' ? 5 : 4);
                int pad = w < 6 ? 6 - w : 0;
                for (int i = 0; i < pad / 2; i++) s += u'';
                for (char ch : c.text) s += (char16_t)(0xE100 + (unsigned char)std::toupper((unsigned char)ch));
                for (int i = 0; i < pad - pad / 2; i++) s += u'';
            }
            s += u'';
            break;
        }
        case Chip::Round: s += (char16_t)(0xE000 + (c.text == "B" ? 1 : c.text == "X" ? 2 : c.text == "Y" ? 3 : 0)); break;
        case Chip::PSShape: s += (char16_t)(0xE190 + c.sym); break;
        case Chip::DPad: s += (char16_t)(c.sym == 0 ? 0xE01A : c.sym == 1 ? 0xE019 : c.sym == 2 ? 0xE01B : 0xE01C); break;
        case Chip::Plus: s += u'+'; break;
        case Chip::UpArrow: s += u'\uE01B'; break;
        }
    }
    return s;
}

std::string Prompts::describe(const Label& l) {
    static const char* dirs[] = {"Left", "Right", "Up", "Down"};
    static const char* shapes[] = {"Cross", "Circle", "Square", "Triangle"};
    std::string s;
    for (const Chip& c : l) {
        if (c.kind == Chip::Plus) { s += "+"; continue; }
        s += "[";
        if (c.kind == Chip::DPad) s += std::string("DPad ") + dirs[c.sym];
        else if (c.kind == Chip::PSShape) s += shapes[c.sym];
        else if (c.sym >= 0) s += dirs[c.sym];
        else s += c.text;
        s += "]";
    }
    return s;
}

bool Prompts::update() {
    if (version_ == in_.promptVersion()) return false;
    version_ = in_.promptVersion();
    if (!enabled_) { recomp::setTagReplacements({}); return true; }
    const std::u16string bs = u"\\";
    recomp::TagReplacements rep;
    auto both = [&](const std::u16string& tag, const std::u16string& to) {
        rep.push_back({bs + u"[" + tag + bs + u"]", to});
        rep.push_back({u"[" + tag + u"]", to});
    };
    auto u16 = [](const char* s) { std::u16string o; while (*s) o += (char16_t)(unsigned char)*s++; return o; };
    // skills 4-6 written as Up + L/Y/X: one key when the slot has its own binding
    const Role combos[3][2] = {{Role::UpL, Role::L}, {Role::UpY, Role::Y}, {Role::UpX, Role::X}};
    for (auto& c : combos) {
        if (!in_.firstBinding(kRoles[(int)c[0]].actions[0], in_.device())) continue;
        Label l = label(c[0]);
        std::u16string to = toGlyphs(l);
        std::u16string k = u16(kRoles[(int)c[1]].tag);
        rep.push_back({bs + u"[^" + bs + u"]+" + bs + u"[" + k + bs + u"]", to});
        rep.push_back({u"[^]+[" + k + u"]", to});
    }
    for (int i = 0; i < (int)Role::Count; i++) {
        const RoleInfo& ri = kRoles[i];
        if (!ri.tag) continue;
        Label l = label((Role)i);
        std::u16string to = l.empty() ? (ri.dsGlyph ? std::u16string(1, (char16_t)ri.dsGlyph) : u16(ri.tag)) : toGlyphs(l);
        both(u16(ri.tag), to);
    }
    recomp::setTagReplacements(std::move(rep));
    return true;
}
