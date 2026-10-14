// Overlay UI: key binding editor and notifications, drawn with SDL + GDI-rendered text.
#pragma once
#include <SDL.h>
#include <string>
#include <unordered_map>
#include "input.h"

class TextCache {
public:
    explicit TextCache(SDL_Renderer* r) : r_(r) {}
    ~TextCache();
    // Returns a cached texture with white text; tint with SDL_SetTextureColorMod.
    SDL_Texture* get(const std::string& utf8, int px, int* w, int* h);
    void draw(const std::string& utf8, int px, int x, int y, SDL_Color c, int align = 0); // align: 0 left, 1 center, 2 right
    int width(const std::string& utf8, int px);
    void clear();
private:
    struct Entry { SDL_Texture* tex; int w, h; uint32_t lastUse; };
    SDL_Renderer* r_;
    std::unordered_map<std::string, Entry> cache_;
};

class Overlay {
public:
    Overlay(SDL_Renderer* r, Input& in, std::string bindPath);
    bool editorOpen() const { return open_; }
    void openEditor();
    void closeEditor();
    // Feed events while the editor is open; returns true if consumed.
    bool handleEvent(const SDL_Event& e);
    void toast(const std::string& msg);
    void draw(int winW, int winH);
    float uiScale = 1.0f;
private:
    void drawEditor(int w, int h);
    int rowCount() const { return (int)Act::Count; }
    SDL_Renderer* r_;
    Input& in_;
    std::string bindPath_;
    TextCache text_;
    bool open_ = false;
    bool listening_ = false;
    int sel_ = 0;
    int scroll_ = 0;
    int column_ = 0; // 0 keyboard, 1 gamepad
    std::string toast_;
    uint32_t toastUntil_ = 0;
    int rowY0_ = 0, rowH_ = 0;
};
