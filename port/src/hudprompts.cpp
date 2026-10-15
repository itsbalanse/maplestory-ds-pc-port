#include "hudprompts.h"

#include <algorithm>
#include <cstring>
#include <vector>

#include "promptfont.inc"
#include "prompt_templates.inc"

namespace hudprompts {
namespace {

constexpr int W = 256, H = 192;
constexpr int kChipH = 12;  // all chips are as tall as the DS keycap icons

// Fades: the DS brightens/darkens colours per 6-bit channel, either for the whole screen (master
// brightness) or per layer (colour effects). Variant 0 is "no fade"; 1-64 are (mode, factor 1-16)
// with modes master up, master down, effect up, effect down (they differ only in rounding).
constexpr int kVariants = 65;
uint32_t fade(uint32_t rgb, int v) {
    if (v <= 0) return rgb;
    const int mode = (v - 1) / 16, f = (v - 1) % 16 + 1;
    static const uint32_t bias[4] = {0, 15, 8, 7};
    uint32_t out = 0;
    for (int sh = 0; sh < 24; sh += 8) {
        uint32_t c = (rgb >> sh & 0xFF) >> 2;
        c = (mode & 1) == 0 ? c + (((63 - c) * f + bias[mode]) >> 4) : c - ((c * f + bias[mode]) >> 4);
        out |= ((c << 2) | (c >> 4)) << sh;
    }
    return out;
}
inline uint32_t key18(uint32_t rgb) { return (rgb >> 18 & 0x3F) << 12 | (rgb >> 10 & 0x3F) << 6 | (rgb >> 2 & 0x3F); }

int g_fade = 0;  // fade of the icon being drawn

inline void put(uint32_t* s, int x, int y, uint32_t rgb) {
    if (x >= 0 && x < W && y >= 0 && y < H) s[y * W + x] = 0xFF000000u | fade(rgb, g_fade);
}

const PromptChar* glyph(char c) {
    if (c >= 'a' && c <= 'z') c = (char)(c - 32);
    for (const auto& g : kPromptFont)
        if (g.c == c) return &g;
    return nullptr;
}

// 5-row bitmap (bit x of rows[y]) at (x, y)
void blit5(uint32_t* s, int x, int y, const PromptChar& g, uint32_t rgb) {
    for (int yy = 0; yy < 5; yy++)
        for (int xx = 0; xx < g.w; xx++)
            if (g.rows[yy] >> xx & 1) put(s, x + xx, y + yy, rgb);
}

int textWidth(const std::string& t) {
    int w = 0;
    for (char c : t)
        if (const PromptChar* g = glyph(c)) w += g->w + 1;
    return w ? w - 1 : 0;
}

int chipWidth(const Chip& c) {
    switch (c.kind) {
    case Chip::Keycap: return std::max(11, (c.sym >= 0 ? 5 : textWidth(c.text)) + 6);
    case Chip::Round: case Chip::PSShape: case Chip::DPad: return 11;
    case Chip::Plus: return 3;
    case Chip::UpArrow: return 7;
    }
    return 0;
}

// Keycap: rounded box, highlight on the top-left, two shade rows at the bottom (like the DS [L] icon)
void keycap(uint32_t* s, int x, int y, int w, const Style& st) {
    const int h = kChipH;
    for (int yy = 0; yy < h; yy++) {
        for (int xx = 0; xx < w; xx++) {
            bool cornerOut = (yy == 0 || yy == h - 1) ? (xx < 2 || xx >= w - 2) : (yy == 1 || yy == h - 2) && (xx == 0 || xx == w - 1);
            if (cornerOut) continue;
            bool edge = yy == 0 || yy == h - 1 || xx == 0 || xx == w - 1 ||
                        ((yy == 1 || yy == h - 2) && (xx == 1 || xx == w - 2));
            uint32_t c = st.face;
            if (edge) c = st.outline;
            else if (yy == h - 3) c = st.shade2;
            else if (yy == h - 4) c = st.shade1;
            else if (xx == 1 || yy == 1) c = st.light;
            put(s, x + xx, y + yy, c);
        }
    }
}

// 11x11 disc in the style of the DS A/B/X/Y icons
const char* kDisc[11] = {"   #####   ", "  #.....#  ", " #.......# ", "#.........#", "#.........#", "#.........#",
                         "#.........#", "#,.......,#", " #,,...,,# ", "  #,,,,,#  ", "   #####   "};
void disc(uint32_t* s, int x, int y, const Style& st) {
    for (int yy = 0; yy < 11; yy++)
        for (int xx = 0; xx < 11; xx++) {
            char c = kDisc[yy][xx];
            if (c != ' ') put(s, x + xx, y + yy, c == '#' ? st.outline : c == ',' ? st.light : st.face);
        }
}

// 11x11 d-pad with the pressed direction dark
const char* kPad[11] = {"   #####   ", "   #...#   ", "   #.0.#   ", "####...####", "#.........#", "#2.......3#",
                        "#.........#", "####...####", "   #.1.#   ", "   #...#   ", "   #####   "};
void dpad(uint32_t* s, int x, int y, int dir, const Style& st) {
    // arm cells per direction (3x3 blocks around the marker digits): 0 up 1 down 2 left 3 right
    const int want = dir == 2 ? 0 : dir == 3 ? 1 : dir == 0 ? 2 : 3;
    for (int yy = 0; yy < 11; yy++)
        for (int xx = 0; xx < 11; xx++) {
            char c = kPad[yy][xx];
            if (c == ' ') continue;
            uint32_t col = c == '#' ? st.outline : st.face;
            // darken the whole pressed arm
            bool inArm = false;
            switch (want) {
            case 0: inArm = yy >= 1 && yy <= 3 && xx >= 4 && xx <= 6; break;
            case 1: inArm = yy >= 7 && yy <= 9 && xx >= 4 && xx <= 6; break;
            case 2: inArm = xx >= 1 && xx <= 3 && yy >= 4 && yy <= 6; break;
            case 3: inArm = xx >= 7 && xx <= 9 && yy >= 4 && yy <= 6; break;
            }
            if (c != '#' && inArm) col = st.ink;
            put(s, x + xx, y + yy, col);
        }
}

// 7x7 symbols for the face buttons (letters for Xbox/Nintendo, shapes for PlayStation)
const char* kFace7[8][7] = {
    {".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"},          // A
    {"####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."},          // B
    {"#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"},          // X
    {"#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."},          // Y
    {"#.....#", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", "#.....#"},  // cross
    {"..###..", ".#...#.", "#.....#", "#.....#", "#.....#", ".#...#.", "..###.."},  // circle
    {"#######", "#.....#", "#.....#", "#.....#", "#.....#", "#.....#", "#######"},  // square
    {"...#...", "...#...", "..#.#..", "..#.#..", ".#...#.", ".#...#.", "#######"},  // triangle
};
void face7(uint32_t* s, int x, int y, int which, uint32_t ink) {
    const char* const* rows = kFace7[which];
    const int w = (int)strlen(rows[0]);
    const int ox = x + (11 - w) / 2;
    for (int yy = 0; yy < 7; yy++)
        for (int xx = 0; xx < w; xx++)
            if (rows[yy][xx] == '#') put(s, ox + xx, y + 2 + yy, ink);
}

// The DS's own "Up" arrow (7x12), used for Up + button combos on the skill bar
const char* kUp[12] = {"...#...", "..#.#..", ".#...#.", "#.....#", "###.###", "..#.#..", "..#.#..",
                       "..#.#..", "..#,#..", "..#,#..", "..###..", "......."};
void upArrow(uint32_t* s, int x, int y, const Style& st) {
    for (int yy = 0; yy < 12; yy++)
        for (int xx = 0; xx < 7; xx++) {
            char c = kUp[yy][xx];
            bool inside = false;
            // fill between the outline pixels of this row
            if (c == '.') {
                int l = -1, r = -1;
                for (int i = 0; i < xx; i++) if (kUp[yy][i] == '#') l = i;
                for (int i = 6; i > xx; i--) if (kUp[yy][i] == '#') r = i;
                inside = l >= 0 && r >= 0 && yy > 0 && yy < 11;
            }
            if (c == '#') put(s, x + xx, y + yy, st.outline);
            else if (c == ',') put(s, x + xx, y + yy, st.shade1);
            else if (inside) put(s, x + xx, y + yy, st.face);
        }
}

uint32_t roundInk(const Chip& c, const Style& st) {
    // modern controllers' face-button colours
    if (c.kind == Chip::Round) {
        if (c.text == "A") return 0x2e9e3e;
        if (c.text == "B") return 0xd8342c;
        if (c.text == "X") return 0x2d6cd8;
        if (c.text == "Y") return 0xd9a600;
    } else if (c.kind == Chip::PSShape) {
        static const uint32_t ps[4] = {0x4f7fe0, 0xe0485a, 0xd060b8, 0x22a88a};
        return ps[c.sym & 3];
    }
    return st.ink;
}

int drawChip(uint32_t* s, int x, int y, const Chip& c, const Style& st) {
    const int w = chipWidth(c);
    switch (c.kind) {
    case Chip::Keycap: {
        keycap(s, x, y, w, st);
        if (c.sym >= 0) {
            blit5(s, x + (w - 5) / 2, y + 3, kPromptArrows[c.sym & 3], st.ink);
        } else {
            int tx = x + (w - textWidth(c.text) + 1) / 2;
            for (char ch : c.text)
                if (const PromptChar* g = glyph(ch)) { blit5(s, tx, y + 3, *g, st.ink); tx += g->w + 1; }
        }
        break;
    }
    case Chip::Round: case Chip::PSShape: {
        disc(s, x, y, st);
        const uint32_t ink = roundInk(c, st);
        if (c.kind == Chip::PSShape) face7(s, x, y, 4 + (c.sym & 3), ink);
        else face7(s, x, y, c.text == "B" ? 1 : c.text == "X" ? 2 : c.text == "Y" ? 3 : 0, ink);
        break;
    }
    case Chip::DPad: dpad(s, x, y, c.sym, st); break;
    case Chip::UpArrow: upArrow(s, x, y, st); break;
    case Chip::Plus:
        put(s, x + 1, y + 4, st.outline); put(s, x, y + 5, st.outline); put(s, x + 1, y + 5, st.outline);
        put(s, x + 2, y + 5, st.outline); put(s, x + 1, y + 6, st.outline);
        break;
    }
    return w;
}

struct Match { const PromptTemplate* t; int screen, x, y, fade; };

// anchor colour (18-bit) -> (template, fade variant) candidates, for every template and fade
struct AnchorIndex {
    std::vector<uint8_t> any;  // 2^18 flags
    std::vector<std::vector<std::pair<uint16_t, uint8_t>>> lists;
    std::vector<int> slot;     // 2^18 -> index into lists (-1 none)
    AnchorIndex() : any(1 << 18), slot(1 << 18, -1) {
        const int n = (int)(sizeof kPromptTemplates / sizeof kPromptTemplates[0]);
        for (int ti = 0; ti < n; ti++) {
            const PromptTemplate& t = kPromptTemplates[ti];
            if (t.shape) continue;  // matched separately (any palette)
            for (int v = 0; v < kVariants; v++) {
                // skip fade levels that wash the icon out (a black or white screen matches nothing)
                int lo = 1 << 30, hi = -1;
                for (int i = 0; i < t.w * t.h; i++) {
                    if (!t.mask[i]) continue;
                    const uint32_t c = fade(t.px[i], v);
                    const int l = (int)(c >> 16) * 3 + (int)(c >> 8 & 255) * 6 + (int)(c & 255);
                    lo = std::min(lo, l); hi = std::max(hi, l);
                }
                if (v > 0 && hi - lo < 300) continue;
                uint32_t k = key18(fade(t.px[t.anchor], v));
                if (slot[k] < 0) { slot[k] = (int)lists.size(); lists.emplace_back(); }
                auto& l = lists[slot[k]];
                if (std::find(l.begin(), l.end(), std::make_pair((uint16_t)ti, (uint8_t)v)) == l.end())
                    l.push_back({(uint16_t)ti, (uint8_t)v});
                any[k] = 1;
            }
        }
    }
};

}  // namespace

int labelWidth(const Label& l) {
    int w = 0;
    for (const Chip& c : l) w += chipWidth(c) + 1;
    return w ? w - 1 : 0;
}

int drawLabel(uint32_t* s, int x, int y, const Label& l, const Style& st) {
    int x0 = x;
    for (const Chip& c : l) {
        x += drawChip(s, x, y, c, st) + 1;
    }
    return x - x0 - (l.empty() ? 0 : 1);
}

int apply(uint32_t* top, uint32_t* bottom, const Prompts& prompts) {
    static const AnchorIndex idx;
    uint32_t* scr[2] = {top, bottom};
    std::vector<Match> found;
    for (int sc = 0; sc < 2; sc++) {
        const uint32_t* s = scr[sc];
        if (!s) continue;
        for (int y = 0; y < H; y++) {
            for (int x = 0; x < W; x++) {
                const uint32_t k = key18(s[y * W + x]);
                if (!idx.any[k]) continue;
                for (auto [ti, v] : idx.lists[idx.slot[k]]) {
                    const PromptTemplate& t = kPromptTemplates[ti];
                    if (t.screen != sc && t.screen != 2) continue;
                    const int ox = x - t.anchor % t.w, oy = y - t.anchor / t.w;
                    if (ox < 0 || oy < 0 || ox + t.w > W || oy + t.h > H) continue;
                    bool ok = true;
                    for (int i = 0; i < t.w * t.h && ok; i++)
                        if (t.mask[i] && (s[(oy + i / t.w) * W + ox + i % t.w] & 0xFFFFFF) != fade(t.px[i], v)) ok = false;
                    if (ok) { found.push_back({&t, sc, ox, oy, v}); break; }
                    if (found.size() > 64) return 0;  // something is wrong with this frame: leave it alone
                }
            }
        }
    }
    // shape templates: same rank -> same colour, ranks ordered dark to light, clear contrast
    for (const PromptTemplate& t : kPromptTemplates) {
        if (!t.shape) continue;
        int ranks = 0;
        for (int i = 0; i < t.w * t.h; i++) ranks = std::max<int>(ranks, t.mask[i]);
        // quick reject: one pixel of the darkest and one of the brightest colour must differ
        int iDark = -1, iBright = -1;
        for (int i = 0; i < t.w * t.h; i++) {
            if (t.mask[i] == 1 && iDark < 0) iDark = i;
            if (t.mask[i] == ranks && iBright < 0) iBright = i;
        }
        const int dDark = (iDark / t.w) * W + iDark % t.w, dBright = (iBright / t.w) * W + iBright % t.w;
        for (int sc = 0; sc < 2; sc++) {
            const uint32_t* s = scr[sc];
            if (!s || (t.screen != sc && t.screen != 2)) continue;
            for (int oy = 0; oy + t.h <= H; oy++) {
                for (int ox = 0; ox + t.w <= W; ox++) {
                    const uint32_t* o = s + oy * W + ox;
                    const uint32_t cd = o[dDark] & 0xFFFFFF, cb = o[dBright] & 0xFFFFFF;
                    if (cd == cb || (cd >> 16) * 3 + (cd >> 8 & 255) * 6 + (cd & 255) + 1000 >
                                        (cb >> 16) * 3 + (cb >> 8 & 255) * 6 + (cb & 255)) continue;
                    uint32_t col[16];
                    bool seen[16] = {};
                    bool ok = true;
                    for (int i = 0; i < t.w * t.h && ok; i++) {
                        const int r = t.mask[i];
                        if (!r) continue;
                        const uint32_t c = s[(oy + i / t.w) * W + ox + i % t.w] & 0xFFFFFF;
                        if (!seen[r]) { seen[r] = true; col[r] = c; }
                        else if (col[r] != c) ok = false;
                    }
                    if (!ok) continue;
                    auto lum = [](uint32_t c) { return (int)(c >> 16) * 3 + (int)(c >> 8 & 255) * 6 + (int)(c & 255); };
                    int prev = -1, lo = 1 << 30, hi = -1;
                    for (int r = 1; r <= ranks && ok; r++) {
                        if (!seen[r]) continue;
                        const int l = lum(col[r]);
                        if (l < prev) ok = false;
                        prev = l; lo = std::min(lo, l); hi = std::max(hi, l);
                    }
                    if (ok && hi - lo > 2000) found.push_back({&t, sc, ox, oy, 0});
                }
            }
        }
    }

    int n = 0;
    for (const Match& m : found) {
        const PromptTemplate& t = *m.t;
        Label l = prompts.label((Role)t.role, t.menu);
        if (l.empty()) continue;
        // Up + button on the skill bar: draw it like the DS does (arrow, no plus sign)
        if (l.size() == 3 && l[1].kind == Chip::Plus && l[0].kind == Chip::DPad && l[0].sym == 2)
            l = {Chip{Chip::UpArrow, "", -1}, l[2]};
        else
            l.erase(std::remove_if(l.begin(), l.end(), [](const Chip& c) { return c.kind == Chip::Plus; }), l.end());
        uint32_t* s = scr[m.screen];
        g_fade = m.fade;
        if (t.compact)
            for (Chip& c : l) {
                if (c.kind != Chip::Keycap || c.sym >= 0) continue;
                static const std::pair<const char*, const char*> kShort[] = {
                    {"ENTER", "\x01"}, {"BKSP", "\x02"}, {"SHIFT", "\x03"}, {"TAB", "\x04"}, {"SPACE", "\x05"},
                    {"CTRL", "CT"}, {"ALT", "AL"}};
                for (auto& [from, to] : kShort)
                    if (c.text == from) c.text = to;
            }
        if (t.text && l.size() == 1 && l[0].kind == Chip::Keycap) {
            // a button with lettering (START/SELECT): clear the old word, write the key name
            for (int y = 3; y < t.h - 3; y++)
                for (int x = 2; x < t.w - 2; x++) put(s, m.x + x, m.y + y, t.fill);
            const Chip& c = l[0];
            const int ty = m.y + (t.h - 5) / 2 - 1;
            if (c.sym >= 0) {
                blit5(s, m.x + (t.w - 5) / 2, ty, kPromptArrows[c.sym & 3], t.ink);
            } else {
                int tx = m.x + (t.w - textWidth(c.text)) / 2;
                for (char ch : c.text)
                    if (const PromptChar* g = glyph(ch)) { blit5(s, tx, ty, *g, t.ink); tx += g->w + 1; }
            }
            n++;
            continue;
        }
        if (t.rect)
            for (int y = 0; y < t.h; y++)
                for (int x = 0; x < t.w; x++) put(s, m.x + x, m.y + y, t.erase);
        const Style st{t.style.outline, t.style.face, t.style.light, t.style.ink, t.style.shade1, t.style.shade2};
        const int w = labelWidth(l);
        const int x = t.align == 1 ? m.x + t.w - w : m.x + (t.w - w) / 2;
        const int y = m.y + (t.h - kChipH + 1) / 2;
        drawLabel(s, x, y, l, st);
        n++;
    }
    g_fade = 0;
    return n;
}

}  // namespace hudprompts
