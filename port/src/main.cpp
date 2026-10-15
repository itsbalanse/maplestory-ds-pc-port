// MapleStory DS for PC — frontend entry point.
#define SDL_MAIN_HANDLED
#include <SDL.h>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commdlg.h>

#include <algorithm>
#include <cstdio>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "emu.h"
#include "input.h"
#include "ui.h"
#include "prompts.h"
#include "hudprompts.h"
#include "testhooks.h"
#include "runtime.h"
#include "testscript.h"

namespace fs = std::filesystem;

// ------------------------------------------------------------------ settings
struct Settings {
    std::string rom;
    int layout = 0;          // 0 stacked, 1 side by side, 2 large top
    bool integerScale = false;
    bool smooth = false;
    bool fullscreen = false;
    bool mute = false;
    bool pcPrompts = true;   // show bound keys/buttons instead of the DS button icons
    int winW = 768, winH = 1152;

    void load(const std::string& p) {
        std::ifstream f(p);
        std::string line;
        while (std::getline(f, line)) {
            auto eq = line.find('=');
            if (eq == std::string::npos || line[0] == '#') continue;
            std::string k = line.substr(0, eq), v = line.substr(eq + 1);
            while (!k.empty() && k.back() == ' ') k.pop_back();
            while (!v.empty() && v.front() == ' ') v.erase(0, 1);
            while (!v.empty() && (v.back() == '\r' || v.back() == ' ')) v.pop_back();
            if (k == "rom") rom = v;
            else if (k == "layout") layout = std::atoi(v.c_str()) % 3;
            else if (k == "integer_scale") integerScale = v == "1";
            else if (k == "smooth") smooth = v == "1";
            else if (k == "fullscreen") fullscreen = v == "1";
            else if (k == "mute") mute = v == "1";
            else if (k == "pc_prompts") pcPrompts = v == "1";
            else if (k == "window_width") winW = std::max(256, std::atoi(v.c_str()));
            else if (k == "window_height") winH = std::max(192, std::atoi(v.c_str()));
        }
    }
    void save(const std::string& p) const {
        std::ofstream f(p);
        f << "# MapleStory DS settings\n"
          << "rom = " << rom << "\n"
          << "layout = " << layout << "        # 0 stacked, 1 side by side, 2 large top screen\n"
          << "integer_scale = " << integerScale << "\n"
          << "smooth = " << smooth << "\n"
          << "fullscreen = " << fullscreen << "\n"
          << "mute = " << mute << "\n"
          << "pc_prompts = " << pcPrompts << "\n"
          << "window_width = " << winW << "\n"
          << "window_height = " << winH << "\n";
    }
};

static std::string exeDir() {
    char* b = SDL_GetBasePath();
    std::string s = b ? b : "./";
    SDL_free(b);
    return s;
}

static std::string findRom(const std::string& dir) {
    const char* preferred[] = {"MapleStory DS (English).nds", "MapleStory DS (Japan).nds"};
    std::vector<fs::path> dirs = {fs::u8path(dir), fs::u8path(dir) / "..", fs::u8path(dir) / ".." / "..",
                                  fs::u8path(dir) / ".." / ".." / "build", fs::u8path(dir) / ".." / "build"};
    for (auto* name : preferred)
        for (auto& d : dirs)
            if (fs::exists(d / name)) return fs::canonical(d / name).u8string();
    for (auto& d : dirs) {
        std::error_code ec;
        for (auto& e : fs::directory_iterator(d, ec))
            if (e.path().extension() == ".nds") return fs::canonical(e.path()).u8string();
    }
    return {};
}

static std::string pickRomDialog() {
    wchar_t file[MAX_PATH] = L"";
    OPENFILENAMEW ofn{};
    ofn.lStructSize = sizeof ofn;
    ofn.lpstrFilter = L"Nintendo DS ROM (*.nds)\0*.nds\0All files\0*.*\0";
    ofn.lpstrFile = file;
    ofn.nMaxFile = MAX_PATH;
    ofn.lpstrTitle = L"Select your MapleStory DS ROM";
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST;
    if (!GetOpenFileNameW(&ofn)) return {};
    return fs::path(file).u8string();
}

// ------------------------------------------------------------------ layout
struct Layout { SDL_Rect top, bottom; };

static Layout computeLayout(int mode, int w, int h, bool integer) {
    int cw = 256, ch = 384;
    if (mode == 1) { cw = 512; ch = 192; }
    if (mode == 2) { cw = 384; ch = 192; }
    double s = std::min((double)w / cw, (double)h / ch);
    if (integer && s >= 1.0) s = std::floor(s);
    int ow = (int)(cw * s), oh = (int)(ch * s);
    int ox = (w - ow) / 2, oy = (h - oh) / 2;
    auto R = [&](double x, double y, double ww, double hh) {
        return SDL_Rect{ox + (int)(x * s), oy + (int)(y * s), (int)(ww * s), (int)(hh * s)};
    };
    Layout L;
    if (mode == 0) { L.top = R(0, 0, 256, 192); L.bottom = R(0, 192, 256, 192); }
    else if (mode == 1) { L.top = R(0, 0, 256, 192); L.bottom = R(256, 0, 256, 192); }
    else { L.top = R(0, 0, 256, 192); L.bottom = R(256, 96, 128, 96); }
    return L;
}

static const char* kLayoutNames[] = {"Stacked screens", "Side by side", "Large top screen"};

// ------------------------------------------------------------------ main
int main(int argc, char** argv) {
    SetProcessDPIAware();
    SDL_SetHint(SDL_HINT_WINDOWS_ENABLE_MENU_MNEMONICS, "0");   // Alt is Jump, not a menu key
    SDL_SetHint(SDL_HINT_WINDOWS_NO_CLOSE_ON_ALT_F4, "0");
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_GAMECONTROLLER) != 0) {
        MessageBoxA(nullptr, SDL_GetError(), "MapleStory DS", MB_ICONERROR);
        return 1;
    }

    std::string base = exeDir();
    std::string settingsPath = base + "settings.ini", bindPath = base + "keybinds.ini";
    Settings cfg;
    cfg.load(settingsPath);
    Input input;
    if (!input.load(bindPath)) input.save(bindPath);
    const bool savedMute = cfg.mute;
    bool muteForRun = false;
    Prompts prompts(input);

    // Self-test options (used by tools to verify rendering without user interaction)
    int testFrames = 0;
    std::string testShot;
    bool testEditor = false;
    std::string testScriptPath, testSave, promptIn, promptOut;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "--verbose") Emu::verbose = true;
        else if (a == "--interp") Emu::forceInterpreter = true;
        else if (a == "--test-frames" && i + 1 < argc) testFrames = std::atoi(argv[++i]);
        else if (a == "--test-shot" && i + 1 < argc) testShot = argv[++i];
        else if (a == "--test-editor") testEditor = true;
        else if (a == "--mute") { cfg.mute = true; muteForRun = true; }  // this run only, not saved
        else if (a == "--device" && i + 1 < argc) {  // tests: show prompts for this device
            std::string d = argv[++i];
            input.setTestDevice(d == "keyboard" ? Device::Keyboard : Device::Pad,
                                d == "ps" ? PadStyle::PlayStation : d == "switch" ? PadStyle::Nintendo : PadStyle::Xbox);
        }
        else if (a == "--test-script" && i + 1 < argc) testScriptPath = argv[++i];
        else if (a == "--test-save" && i + 1 < argc) testSave = argv[++i];
        else if (a == "--prompt-image" && i + 2 < argc) {  // tests: redraw the button icons of a 256x384 BMP
            promptIn = argv[++i];
            promptOut = argv[++i];
        }
        else cfg.rom = a;
    }
    if (!promptIn.empty()) {
        SDL_Surface* raw = SDL_LoadBMP(promptIn.c_str());
        if (!raw) { fprintf(stderr, "cannot read %s\n", promptIn.c_str()); return 1; }
        SDL_Surface* img = SDL_ConvertSurfaceFormat(raw, SDL_PIXELFORMAT_ARGB8888, 0);
        SDL_FreeSurface(raw);
        if (!img || img->w != 256 || img->h != 384) { fprintf(stderr, "need a 256x384 image\n"); return 1; }
        prompts.update();
        uint32_t* px = (uint32_t*)img->pixels;  // pitch is 1024 for 256 ARGB pixels
        std::vector<uint32_t> copy(px, px + 256 * 384);
        Uint64 t0 = SDL_GetPerformanceCounter();
        for (int i = 0; i < 50; i++) { std::vector<uint32_t> c = copy; hudprompts::apply(c.data(), c.data() + 256 * 192, prompts); }
        double ms = (double)(SDL_GetPerformanceCounter() - t0) * 1000.0 / SDL_GetPerformanceFrequency() / 50;
        int n = hudprompts::apply(px, px + 256 * 192, prompts);
        printf("%.3f ms per frame, ", ms);
        SDL_SaveBMP(img, promptOut.c_str());
        SDL_FreeSurface(img);
        printf("%d icons redrawn\n", n);
        return 0;
    }
    // reference-mode test scripts may run Lua through an instruction hook: needs the pure interpreter
    if (Emu::forceInterpreter && !testScriptPath.empty()) Emu::noJit = true;
    if (cfg.rom.empty() || !fs::exists(fs::u8path(cfg.rom))) cfg.rom = findRom(base);
    if (cfg.rom.empty()) cfg.rom = pickRomDialog();
    if (cfg.rom.empty()) return 0;

    // Self-tests never touch the player's save: they start from an empty one unless --test-save is given.
    if (testFrames > 0 || !testScriptPath.empty()) {
        if (testSave.empty()) { testSave = base + "test.sav"; remove(testSave.c_str()); }
        Emu::savOverride = testSave;
    }
    Emu emu;
    std::string err;
    if (!emu.loadRom(cfg.rom, err)) {
        MessageBoxA(nullptr, err.c_str(), "MapleStory DS", MB_ICONERROR);
        return 1;
    }

    // Self-tests run in the background: hidden window, no sound, no frame pacing.
    TestScript script;
    if (!testScriptPath.empty() && !script.load(testScriptPath)) {
        fprintf(stderr, "cannot read test script %s\n", testScriptPath.c_str());
        return 1;
    }
    const bool headless = testFrames > 0 || !testScriptPath.empty();
    script.luaPending = [] { return recomp::luaPending(); };
    script.pixel = [&emu](int x, int y) -> uint32_t {
        if (x < 0 || x > 255 || y < 0 || y > 383) return 0;
        const uint32_t* scr = emu.screen(y >= 192 ? 1 : 0);
        return scr ? scr[(y % 192) * 256 + x] & 0xFFFFFF : 0;
    };
    SDL_Window* win = SDL_CreateWindow("MapleStory DS", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                       cfg.winW, cfg.winH,
                                       SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI | (headless ? SDL_WINDOW_HIDDEN : 0));
    SDL_Renderer* ren = headless ? SDL_CreateRenderer(win, -1, SDL_RENDERER_SOFTWARE)
                                 : SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!ren) ren = SDL_CreateRenderer(win, -1, 0);
    if (cfg.fullscreen) SDL_SetWindowFullscreen(win, SDL_WINDOW_FULLSCREEN_DESKTOP);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, cfg.smooth ? "linear" : "nearest");
    SDL_Texture* scr[2];
    for (auto& t : scr) t = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, 256, 192);

    SDL_AudioSpec want{}, have{};
    want.freq = Emu::kSampleRate;
    want.format = AUDIO_S16SYS;
    want.channels = 2;
    want.samples = 1024;
    SDL_AudioDeviceID audio = headless ? 0 : SDL_OpenAudioDevice(nullptr, 0, &want, &have, 0);
    if (audio) SDL_PauseAudioDevice(audio, 0);

    Overlay ui(ren, input, bindPath);
    ui.toast("F1: key bindings   F2: screen layout   F11: fullscreen");

    input.openPads();

    const double frameSec = 1.0 / 59.8261;
    const int frameBytes = (int)(Emu::kSampleRate * frameSec) * 4;
    std::vector<int16_t> abuf(8192 * 2);
    Uint64 freq = SDL_GetPerformanceFrequency(), next = SDL_GetPerformanceCounter();
    bool running = true, paused = false;
    int exitCode = 0;
    bool touching = false;
    int tx = 0, ty = 0;
    std::string statePath = cfg.rom.substr(0, cfg.rom.find_last_of('.')) + ".state";

    // Frame as shown: the emulator's screens with the DS button icons redrawn for the player's bindings
    std::vector<uint32_t> frame[2] = {std::vector<uint32_t>(256 * 192), std::vector<uint32_t>(256 * 192)};
    auto compose = [&]() {
        for (int i = 0; i < 2; i++) {
            const uint32_t* px = emu.screen(i);
            if (px) memcpy(frame[i].data(), px, 256 * 192 * 4);
        }
        if (cfg.pcPrompts) hudprompts::apply(frame[0].data(), frame[1].data(), prompts);
    };
    auto saveFrame = [&](const std::string& path) {
        SDL_Surface* s = SDL_CreateRGBSurfaceWithFormat(0, 256, 384, 32, SDL_PIXELFORMAT_ARGB8888);
        memcpy(s->pixels, frame[0].data(), 256 * 192 * 4);
        memcpy((uint8_t*)s->pixels + 256 * 192 * 4, frame[1].data(), 256 * 192 * 4);
        SDL_SaveBMP(s, path.c_str());
        SDL_FreeSurface(s);
    };

    prompts.setEnabled(cfg.pcPrompts);
    if (testEditor) ui.openEditor();
    int frameNo = 0;
    while (running) {
        if (testFrames && ++frameNo > testFrames) {
            if (recomp::active()) recomp::dumpStats();
            recomp::traceStop();
            if (!testShot.empty()) {
                int rw, rh;
                SDL_GetRendererOutputSize(ren, &rw, &rh);
                SDL_Surface* s = SDL_CreateRGBSurfaceWithFormat(0, rw, rh, 32, SDL_PIXELFORMAT_ARGB8888);
                SDL_RenderReadPixels(ren, nullptr, SDL_PIXELFORMAT_ARGB8888, s->pixels, s->pitch);
                SDL_SaveBMP(s, testShot.c_str());
                SDL_FreeSurface(s);
            }
            break;
        }
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) running = false;
            if (ui.editorOpen()) {
                if (e.type == SDL_CONTROLLERDEVICEADDED || e.type == SDL_CONTROLLERDEVICEREMOVED) input.handleEvent(e);
                ui.handleEvent(e);
                continue;
            }
            input.handleEvent(e);
            if (e.type == SDL_WINDOWEVENT && e.window.event == SDL_WINDOWEVENT_RESIZED &&
                !(SDL_GetWindowFlags(win) & SDL_WINDOW_FULLSCREEN_DESKTOP)) {
                cfg.winW = e.window.data1; cfg.winH = e.window.data2;
            }
            if ((e.type == SDL_MOUSEBUTTONDOWN || e.type == SDL_MOUSEMOTION || e.type == SDL_MOUSEBUTTONUP)) {
                int ww, wh, rw, rh;
                SDL_GetWindowSize(win, &ww, &wh);
                SDL_GetRendererOutputSize(ren, &rw, &rh);
                int mx = (e.type == SDL_MOUSEMOTION ? e.motion.x : e.button.x) * rw / std::max(1, ww);
                int my = (e.type == SDL_MOUSEMOTION ? e.motion.y : e.button.y) * rh / std::max(1, wh);
                Layout L = computeLayout(cfg.layout, rw, rh, cfg.integerScale);
                bool inside = mx >= L.bottom.x && my >= L.bottom.y && mx < L.bottom.x + L.bottom.w && my < L.bottom.y + L.bottom.h;
                bool leftDown = SDL_GetMouseState(nullptr, nullptr) & SDL_BUTTON(SDL_BUTTON_LEFT);
                if (e.type == SDL_MOUSEBUTTONUP && e.button.button == SDL_BUTTON_LEFT) touching = false;
                else if (leftDown && (inside || touching)) {
                    touching = true;
                    tx = std::clamp((mx - L.bottom.x) * 256 / std::max(1, L.bottom.w), 0, 255);
                    ty = std::clamp((my - L.bottom.y) * 192 / std::max(1, L.bottom.h), 0, 191);
                }
            }
        }

        input.update();
        prompts.update();
        if (ui.editorOpen()) {
            // game paused while editing bindings
        } else {
            if (input.pressed(Act::KeybindEditor)) { ui.openEditor(); touching = false; }
            if (input.pressed(Act::Fullscreen)) {
                cfg.fullscreen = !cfg.fullscreen;
                SDL_SetWindowFullscreen(win, cfg.fullscreen ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0);
            }
            if (input.pressed(Act::NextLayout)) { cfg.layout = (cfg.layout + 1) % 3; ui.toast(kLayoutNames[cfg.layout]); }
            if (input.pressed(Act::Mute)) {
                cfg.mute = !cfg.mute;
                muteForRun = false;  // the player chose: remember it
                if (cfg.mute && audio) SDL_ClearQueuedAudio(audio);
                ui.toast(cfg.mute ? "Sound muted (F3)" : "Sound on (F3)");
            }
            if (input.pressed(Act::TogglePrompts)) {
                cfg.pcPrompts = !cfg.pcPrompts;
                prompts.setEnabled(cfg.pcPrompts);
                ui.toast(cfg.pcPrompts ? "Showing your keys and buttons (F4)" : "Showing the original DS buttons (F4)");
            }
            if (input.pressed(Act::Pause)) { paused = !paused; ui.toast(paused ? "Paused" : "Resumed"); }
            if (input.pressed(Act::QuickSave))
                ui.toast(emu.recompiled() ? "Save states need --interp mode (use the in-game save)" : emu.saveState(statePath) ? "State saved" : "Could not save state");
            if (input.pressed(Act::QuickLoad))
                ui.toast(emu.recompiled() ? "Save states need --interp mode (use the in-game save)" : emu.loadState(statePath) ? "State loaded" : "No saved state");
            if (input.pressed(Act::Screenshot)) {
                fs::create_directories(fs::u8path(base + "screenshots"));
                char name[64];
                std::time_t t = std::time(nullptr);
                std::strftime(name, sizeof name, "screenshots/%Y%m%d_%H%M%S.bmp", std::localtime(&t));
                saveFrame(base + name);
                ui.toast(std::string("Saved ") + name);
            }
        }

        bool ff = !ui.editorOpen() && input.held(Act::FastForward);
        if (!paused && !ui.editorOpen()) {
            uint32_t mask = input.dsKeyMask();
            int frames = ff ? 4 : 1;
            if (!testScriptPath.empty()) {
                std::vector<std::string> shots;
                script.frame(mask, touching, tx, ty, shots);
                frames = 1;
                emu.runFrame(mask, touching, tx, ty);
                if (!shots.empty()) compose();
                for (auto& name : shots) {
                    if (name.rfind("gpu:", 0) == 0) { emu.dumpGpu(name.substr(4) + ".gpu"); continue; }
                    if (name.rfind("lua:", 0) == 0) { recomp::queueLua(name.substr(4)); continue; }
                    if (name.rfind("ram:", 0) == 0) { emu.dumpRam(name.substr(4) + ".ram"); continue; }
                    if (name.rfind("raw:", 0) == 0) {  // the game's own frame, DS icons not redrawn
                        for (int i = 0; i < 2; i++)
                            if (const uint32_t* px = emu.screen(i)) memcpy(frame[i].data(), px, 256 * 192 * 4);
                        saveFrame(name.substr(4) + ".bmp");
                        compose();
                        continue;
                    }
                    saveFrame(name + ".bmp");
                }
                if (script.done()) {
                    running = false;
                    if (recomp::active()) recomp::dumpStats();
                    recomp::traceStop();
                    if (script.failed()) {
                        exitCode = 2;
                        compose();
                        saveFrame("fail.bmp");
                    }
                }
                frames = 0;
            }
            for (int i = 0; i < frames; i++) emu.runFrame(mask, touching, tx, ty);
            int n;
            while ((n = emu.readAudio(abuf.data(), (int)abuf.size() / 2)) > 0) {
                if (audio && !ff && !cfg.mute && SDL_GetQueuedAudioSize(audio) < (Uint32)frameBytes * 6)
                    SDL_QueueAudio(audio, abuf.data(), n * 4);
            }
        }
        input.endFrame();

        // draw
        int rw, rh;
        SDL_GetRendererOutputSize(ren, &rw, &rh);
        ui.uiScale = std::max(1.0f, rh / 720.0f);
        SDL_SetRenderDrawColor(ren, 0, 0, 0, 255);
        SDL_RenderClear(ren);
        Layout L = computeLayout(cfg.layout, rw, rh, cfg.integerScale);
        compose();
        for (int i = 0; i < 2; i++) {
            SDL_UpdateTexture(scr[i], nullptr, frame[i].data(), 256 * 4);
            SDL_SetTextureScaleMode(scr[i], cfg.smooth ? SDL_ScaleModeLinear : SDL_ScaleModeNearest);
            SDL_RenderCopy(ren, scr[i], nullptr, i == 0 ? &L.top : &L.bottom);
        }
        ui.draw(rw, rh);
        if (testFrames && frameNo == testFrames && !testShot.empty()) {
            SDL_Surface* s = SDL_CreateRGBSurfaceWithFormat(0, rw, rh, 32, SDL_PIXELFORMAT_ARGB8888);
            SDL_RenderReadPixels(ren, nullptr, SDL_PIXELFORMAT_ARGB8888, s->pixels, s->pitch);
            SDL_SaveBMP(s, testShot.c_str());
            SDL_FreeSurface(s);
            testShot.clear();
        }
        SDL_RenderPresent(ren);

        // pacing: audio queue depth when available, otherwise wall clock
        if (!ff && !headless) {
            if (audio && !cfg.mute && !paused && !ui.editorOpen()) {
                while (SDL_GetQueuedAudioSize(audio) > (Uint32)frameBytes * 3) SDL_Delay(1);
            } else {
                next += (Uint64)(frameSec * freq);
                Uint64 now = SDL_GetPerformanceCounter();
                if (next > now) SDL_Delay((Uint32)((next - now) * 1000 / freq));
                else next = now;
            }
        }
    }

    emu.flushSave();
    // Self-tests (and --mute) never change the player's settings or bindings
    if (!headless) {
        if (muteForRun) cfg.mute = savedMute;
        cfg.save(settingsPath);
        input.save(bindPath);
    }
    if (audio) SDL_CloseAudioDevice(audio);
    SDL_DestroyRenderer(ren);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return exitCode;
}
