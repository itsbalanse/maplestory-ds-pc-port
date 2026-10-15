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
    static inline bool forceInterpreter = false;  // --interp: run ARM9 in the melonDS interpreter

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

    bool saveState(const std::string& path);
    bool loadState(const std::string& path);

    void onSaveWrite(const uint8_t* data, uint32_t len);
    void flushSave();

    const std::string& romPath() const { return romPath_; }
    bool loaded() const { return nds_ != nullptr; }
    bool recompiled() const { return useRecomp_; }

private:
    std::unique_ptr<melonDS::NDS> nds_;
    bool useRecomp_ = false;
    std::string romPath_, savPath_;
    std::vector<uint8_t> pendingSave_;
    bool saveDirty_ = false;
    uint64_t lastSaveWriteMs_ = 0;
};
