#include "ui.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <vector>
#include <cstring>
#include <cstdlib>
#include <algorithm>

// ------------------------------------------------------------------ text (GDI)
static std::wstring widen(const std::string& s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), w.data(), n);
    return w;
}

TextCache::~TextCache() { clear(); }

void TextCache::clear() {
    for (auto& kv : cache_) SDL_DestroyTexture(kv.second.tex);
    cache_.clear();
}

SDL_Texture* TextCache::get(const std::string& utf8, int px, int* w, int* h) {
    std::string key = std::to_string(px) + "|" + utf8;
    auto it = cache_.find(key);
    if (it != cache_.end()) {
        it->second.lastUse = SDL_GetTicks();
        if (w) *w = it->second.w;
        if (h) *h = it->second.h;
        return it->second.tex;
    }
    if (cache_.size() > 512) clear();

    std::wstring ws = widen(utf8.empty() ? " " : utf8);
    HDC dc = CreateCompatibleDC(nullptr);
    HFONT font = CreateFontW(-px, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                             CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HGDIOBJ oldFont = SelectObject(dc, font);
    SIZE sz{};
    GetTextExtentPoint32W(dc, ws.c_str(), (int)ws.size(), &sz);
    int tw = sz.cx + 2, th = sz.cy + 2;

    BITMAPINFO bi{};
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = tw;
    bi.bmiHeader.biHeight = -th;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HBITMAP bmp = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ oldBmp = SelectObject(dc, bmp);
    memset(bits, 0, (size_t)tw * th * 4);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, RGB(255, 255, 255));
    TextOutW(dc, 1, 1, ws.c_str(), (int)ws.size());
    GdiFlush();

    std::vector<uint32_t> px32((size_t)tw * th);
    const uint32_t* src = (const uint32_t*)bits;
    for (size_t i = 0; i < px32.size(); i++) {
        uint32_t v = src[i];
        uint32_t a = std::max({(v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff});
        px32[i] = (a << 24) | 0x00FFFFFF;
    }
    SelectObject(dc, oldBmp);
    SelectObject(dc, oldFont);
    DeleteObject(bmp);
    DeleteObject(font);
    DeleteDC(dc);

    SDL_Texture* t = SDL_CreateTexture(r_, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STATIC, tw, th);
    SDL_UpdateTexture(t, nullptr, px32.data(), tw * 4);
    SDL_SetTextureBlendMode(t, SDL_BLENDMODE_BLEND);
    cache_[key] = {t, tw, th, SDL_GetTicks()};
    if (w) *w = tw;
    if (h) *h = th;
    return t;
}

int TextCache::width(const std::string& s, int px) { int w = 0; get(s, px, &w, nullptr); return w; }

void TextCache::draw(const std::string& s, int px, int x, int y, SDL_Color c, int align) {
    int w, h;
    SDL_Texture* t = get(s, px, &w, &h);
    if (align == 1) x -= w / 2; else if (align == 2) x -= w;
    SDL_SetTextureColorMod(t, c.r, c.g, c.b);
    SDL_SetTextureAlphaMod(t, c.a);
    SDL_Rect d{x, y, w, h};
    SDL_RenderCopy(r_, t, nullptr, &d);
}

// ------------------------------------------------------------------ overlay
Overlay::Overlay(SDL_Renderer* r, Input& in, std::string bindPath)
    : r_(r), in_(in), bindPath_(std::move(bindPath)), text_(r) {}

void Overlay::toast(const std::string& msg) { toast_ = msg; toastUntil_ = SDL_GetTicks() + 2500; }

void Overlay::openEditor() { open_ = true; listening_ = false; in_.releaseAll(); }

void Overlay::closeEditor() {
    open_ = false; listening_ = false;
    in_.save(bindPath_);
    in_.releaseAll();
    toast("Key bindings saved");
}

static std::string bindingLabel(const Binding& b) {
    if (b.type == Binding::Key) return SDL_GetScancodeName((SDL_Scancode)b.code);
    if (b.type == Binding::PadAxis) {
        switch (b.code) {
        case SDL_CONTROLLER_AXIS_LEFTX: return b.dir < 0 ? "Stick Left" : "Stick Right";
        case SDL_CONTROLLER_AXIS_LEFTY: return b.dir < 0 ? "Stick Up" : "Stick Down";
        case SDL_CONTROLLER_AXIS_RIGHTX: return b.dir < 0 ? "R-Stick Left" : "R-Stick Right";
        case SDL_CONTROLLER_AXIS_RIGHTY: return b.dir < 0 ? "R-Stick Up" : "R-Stick Down";
        case SDL_CONTROLLER_AXIS_TRIGGERLEFT: return "LT";
        case SDL_CONTROLLER_AXIS_TRIGGERRIGHT: return "RT";
        }
        return "Axis";
    }
    switch (b.code) {
    case SDL_CONTROLLER_BUTTON_A: return "A"; case SDL_CONTROLLER_BUTTON_B: return "B";
    case SDL_CONTROLLER_BUTTON_X: return "X"; case SDL_CONTROLLER_BUTTON_Y: return "Y";
    case SDL_CONTROLLER_BUTTON_BACK: return "Back"; case SDL_CONTROLLER_BUTTON_START: return "Start";
    case SDL_CONTROLLER_BUTTON_GUIDE: return "Guide";
    case SDL_CONTROLLER_BUTTON_LEFTSTICK: return "L-Stick Click"; case SDL_CONTROLLER_BUTTON_RIGHTSTICK: return "R-Stick Click";
    case SDL_CONTROLLER_BUTTON_LEFTSHOULDER: return "LB"; case SDL_CONTROLLER_BUTTON_RIGHTSHOULDER: return "RB";
    case SDL_CONTROLLER_BUTTON_DPAD_UP: return "D-Pad Up"; case SDL_CONTROLLER_BUTTON_DPAD_DOWN: return "D-Pad Down";
    case SDL_CONTROLLER_BUTTON_DPAD_LEFT: return "D-Pad Left"; case SDL_CONTROLLER_BUTTON_DPAD_RIGHT: return "D-Pad Right";
    }
    return SDL_GameControllerGetStringForButton((SDL_GameControllerButton)b.code);
}

bool Overlay::handleEvent(const SDL_Event& e) {
    if (!open_) return false;
    if (listening_) {
        if (e.type == SDL_KEYDOWN && !e.key.repeat) {
            if (e.key.keysym.scancode == SDL_SCANCODE_ESCAPE) { listening_ = false; return true; }
            in_.addBinding((Act)sel_, {Binding::Key, (int)e.key.keysym.scancode, 0});
            listening_ = false;
            return true;
        }
        if (e.type == SDL_CONTROLLERBUTTONDOWN) {
            in_.addBinding((Act)sel_, {Binding::PadButton, (int)e.cbutton.button, 0});
            listening_ = false;
            return true;
        }
        if (e.type == SDL_CONTROLLERAXISMOTION && std::abs((int)e.caxis.value) > 24000) {
            in_.addBinding((Act)sel_, {Binding::PadAxis, (int)e.caxis.axis, e.caxis.value < 0 ? -1 : 1});
            listening_ = false;
            return true;
        }
        return e.type == SDL_KEYUP || e.type == SDL_CONTROLLERBUTTONUP || e.type == SDL_MOUSEBUTTONDOWN;
    }
    if (e.type == SDL_KEYDOWN) {
        switch (e.key.keysym.scancode) {
        case SDL_SCANCODE_ESCAPE: case SDL_SCANCODE_F1: closeEditor(); return true;
        case SDL_SCANCODE_UP: sel_ = (sel_ + rowCount() - 1) % rowCount(); return true;
        case SDL_SCANCODE_DOWN: sel_ = (sel_ + 1) % rowCount(); return true;
        case SDL_SCANCODE_PAGEUP: sel_ = std::max(0, sel_ - 8); return true;
        case SDL_SCANCODE_PAGEDOWN: sel_ = std::min(rowCount() - 1, sel_ + 8); return true;
        case SDL_SCANCODE_RETURN: case SDL_SCANCODE_KP_ENTER: listening_ = true; return true;
        case SDL_SCANCODE_DELETE: case SDL_SCANCODE_BACKSPACE: in_.clearBindings((Act)sel_); return true;
        case SDL_SCANCODE_F8: in_.setDefaults(); toast("Restored default bindings"); return true;
        default: return true;
        }
    }
    if (e.type == SDL_MOUSEWHEEL) { sel_ = std::clamp(sel_ - e.wheel.y, 0, rowCount() - 1); return true; }
    if (e.type == SDL_MOUSEBUTTONDOWN && e.button.button == SDL_BUTTON_LEFT && rowH_ > 0) {
        int row = (e.button.y - rowY0_) / rowH_ + scroll_;
        if (e.button.y >= rowY0_ && row >= 0 && row < rowCount()) {
            if (row == sel_ && e.button.clicks >= 2) listening_ = true;
            sel_ = row;
        }
        return true;
    }
    return e.type == SDL_KEYUP || e.type == SDL_MOUSEBUTTONUP || e.type == SDL_MOUSEMOTION ||
           e.type == SDL_CONTROLLERBUTTONDOWN || e.type == SDL_CONTROLLERBUTTONUP;
}

void Overlay::draw(int w, int h) {
    if (open_) drawEditor(w, h);
    if (!toast_.empty() && SDL_GetTicks() < toastUntil_) {
        int px = (int)(16 * uiScale);
        int tw = text_.width(toast_, px);
        SDL_Rect bg{12, h - px * 2 - 16, tw + 24, px * 2};
        SDL_SetRenderDrawBlendMode(r_, SDL_BLENDMODE_BLEND);
        SDL_SetRenderDrawColor(r_, 20, 24, 40, 220);
        SDL_RenderFillRect(r_, &bg);
        text_.draw(toast_, px, bg.x + 12, bg.y + px / 2 - 2, {255, 236, 160, 255});
    }
}

void Overlay::drawEditor(int w, int h) {
    SDL_SetRenderDrawBlendMode(r_, SDL_BLENDMODE_BLEND);
    SDL_SetRenderDrawColor(r_, 8, 12, 28, 235);
    SDL_Rect all{0, 0, w, h};
    SDL_RenderFillRect(r_, &all);

    int px = std::max(12, std::min(20, h / 42));
    int title = px + 8;
    int y = 16;
    text_.draw("Key Bindings", title, w / 2, y, {255, 214, 90, 255}, 1);
    y += title + 12;
    if (listening_) {
        text_.draw("Press a key or gamepad button to add it   (Esc cancels)", px - 2, w / 2, y, {255, 200, 120, 255}, 1);
        y += px + 4;
        text_.draw(std::string("Binding: ") + actionInfo((Act)sel_).label, px - 2, w / 2, y, {255, 200, 120, 255}, 1);
    } else {
        text_.draw("Up/Down: select     Enter or double-click: add a key     Delete: clear", px - 2, w / 2, y, {190, 200, 230, 255}, 1);
        y += px + 4;
        text_.draw("F8: restore defaults     Esc: save and close", px - 2, w / 2, y, {190, 200, 230, 255}, 1);
    }
    y += px + 16;

    int colLabel = 24, colKeys = (int)(w * 0.40), colPad = (int)(w * 0.69);
    text_.draw("Action", px, colLabel, y, {140, 160, 210, 255});
    text_.draw("Keyboard", px, colKeys, y, {140, 160, 210, 255});
    text_.draw("Gamepad", px, colPad, y, {140, 160, 210, 255});
    y += px + 10;

    rowH_ = px + 10;
    rowY0_ = y;
    int visible = std::max(1, (h - y - 16) / rowH_);
    if (sel_ < scroll_) scroll_ = sel_;
    if (sel_ >= scroll_ + visible) scroll_ = sel_ - visible + 1;

    for (int i = scroll_; i < rowCount() && i < scroll_ + visible; i++) {
        int ry = y + (i - scroll_) * rowH_;
        const ActionInfo& info = actionInfo((Act)i);
        if (i == sel_) {
            SDL_SetRenderDrawColor(r_, listening_ ? 140 : 60, listening_ ? 90 : 80, listening_ ? 30 : 140, 200);
            SDL_Rect hl{12, ry - 3, w - 24, rowH_};
            SDL_RenderFillRect(r_, &hl);
        }
        bool newGroup = i == 0 || strcmp(actionInfo((Act)(i - 1)).group, info.group) != 0;
        SDL_Color lc = newGroup ? SDL_Color{255, 255, 255, 255} : SDL_Color{225, 228, 240, 255};
        text_.draw(info.label, px, colLabel, ry, lc);
        std::string keys, pads;
        for (auto& b : in_.bindings((Act)i)) {
            std::string& dst = b.type == Binding::Key ? keys : pads;
            if (!dst.empty()) dst += ", ";
            dst += bindingLabel(b);
        }
        auto fitPx = [&](const std::string& t, int avail) {
            int p = px;
            while (p > 9 && text_.width(t, p) > avail) p--;
            return p;
        };
        std::string k = keys.empty() ? "-" : keys, pd = pads.empty() ? "-" : pads;
        text_.draw(k, fitPx(k, colPad - colKeys - 12), colKeys, ry, {255, 236, 160, 255});
        text_.draw(pd, fitPx(pd, w - colPad - 16), colPad, ry, {170, 220, 255, 255});
    }
}
