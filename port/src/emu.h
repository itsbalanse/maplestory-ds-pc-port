// Wrapper around the DS hardware model (melonDS) used by the frontend.
#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace melonDS { class NDS; }

class Emu {
public:
    static inline bool verbose = false;
    static inline std::string savOverride;            // save file path override (tests)
    static inline bool forceInterpreter = false;  // --interp: run ARM9 in the melonDS interpreter
    static inline bool noJit = false;             // pure interpreter (test hooks in --interp mode)

    Emu();
    ~Emu();

    bool loadRom(const std::string& romPath, std::string& err);
    void reset();
    void runFrame(uint32_t keyMask, bool touching, int touchX, int touchY);

    // 256x192 BGRA8888 framebuffers for the top (0) and bottom (1) screens
    const uint32_t* screen(int which) const;

    // Interleaved stereo s16 samples produced since the last call
    int readAudio(int16_t* out, int maxFrames);
    int audioAvailable() const;
    static constexpr int kSampleRate = 48000;

    // Save states. In the native build a state can only be taken at a safe moment between frames
    // (see recomp::canSaveState): callers retry for a few frames while canSaveState() is false.
    bool canSaveState(std::string* why = nullptr) const;
    bool saveState(const std::string& path);
    // Native build: save now if possible, otherwise at the next safe point inside the next frames
    // (busy scenes). Call once per frame: 1 saved, 0 not yet, -1 failed.
    int saveStateSoon(const std::string& path);
    void cancelSaveStateSoon();
    bool loadState(const std::string& path, std::string* why = nullptr);

    // Debug: write both 2D engines' VRAM views, palettes, OAM and registers (tools/gpudump.py)
    bool dumpGpu(const std::string& path) const;
    bool dumpRam(const std::string& path) const;  // main RAM, 4 MB
    // MASTER_BRIGHT register of the engine shown on screen 0 (top) / 1 (bottom)
    uint16_t masterBrightness(int screen) const;

    void onSaveWrite(const uint8_t* data, uint32_t len);
    void flushSave();

    const std::string& romPath() const { return romPath_; }
    bool loaded() const { return nds_ != nullptr; }
    bool recompiled() const { return useRecomp_; }

private:
    bool writeState(const std::string& path, const std::vector<uint8_t>& rt);
    std::unique_ptr<melonDS::NDS> nds_;
    bool useRecomp_ = false;
    std::string romPath_, savPath_;
    std::vector<uint8_t> pendingSave_;
    bool saveDirty_ = false;
    uint64_t lastSaveWriteMs_ = 0;
};
