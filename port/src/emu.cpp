#include "emu.h"

#include "NDS.h"
#include "NDSCart.h"
#include "GPU.h"
#include "SPU.h"
#include "Savestate.h"
#include "Args.h"
#include "Platform.h"
#include "runtime.h"
#include "testhooks.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>

using namespace melonDS;

static std::vector<uint8_t> readFile(const std::string& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return {};
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), {});
}

Emu::Emu() = default;

Emu::~Emu() { flushSave(); }

bool Emu::loadRom(const std::string& romPath, std::string& err) {
    auto rom = readFile(romPath);
    if (rom.size() < 0x200) { err = "Could not read ROM: " + romPath; return false; }
    romPath_ = romPath;
    savPath_ = romPath.substr(0, romPath.find_last_of('.')) + ".sav";
    if (!savOverride.empty()) savPath_ = savOverride;  // tests use their own save file

    NDSCart::NDSCartArgs cargs{};
    auto sav = readFile(savPath_);
    if (!sav.empty()) {
        cargs.SRAM = std::make_unique<u8[]>(sav.size());
        memcpy(cargs.SRAM.get(), sav.data(), sav.size());
        cargs.SRAMLength = (u32)sav.size();
    }
    auto romdata = std::make_unique<u8[]>(rom.size());
    memcpy(romdata.get(), rom.data(), rom.size());
    auto cart = NDSCart::ParseROM(std::move(romdata), (u32)rom.size(), this, std::move(cargs));
    if (!cart) { err = "Not a valid DS ROM: " + romPath; return false; }

    useRecomp_ = recomp::available() && !forceInterpreter;
    NDSArgs args{};
    args.OutputSampleRate = kSampleRate;
    if (useRecomp_ || noJit || getenv("MSDS_TRACE") || getenv("MSDS_ITRACE")) args.JIT = std::nullopt;  // ARM7 interpreted; ARM9 recompiled (or traced)
    nds_ = std::make_unique<NDS>(std::move(args), this);
    nds_->Reset();
    nds_->SetNDSCart(std::move(cart));
    nds_->SetupDirectBoot(romPath);
    nds_->Start();
    if (useRecomp_) recomp::attach(nds_.get(), nds_->NDSCartSlot.GetCart()->GetHeader().ARM9EntryAddress);
    if (getenv("MSDS_TRACE") || getenv("MSDS_ITRACE")) recomp::traceStart(getenv("MSDS_TRACE"), !useRecomp_);
    if (!useRecomp_ && noJit) recomp::enableInterpLua();  // test scripts: `lua` in reference mode
    return true;
}

void Emu::reset() {
    if (!nds_) return;
    nds_->Reset();
    nds_->SetupDirectBoot(romPath_);
    nds_->Start();
    if (useRecomp_) recomp::attach(nds_.get(), nds_->NDSCartSlot.GetCart()->GetHeader().ARM9EntryAddress);
}

void Emu::runFrame(uint32_t keyMask, bool touching, int tx, int ty) {
    if (!nds_) return;
    nds_->SetKeyMask(keyMask);
    if (touching) nds_->TouchScreen((u16)tx, (u16)ty); else nds_->ReleaseScreen();
    nds_->RunFrame();
    if (saveDirty_ && Platform::GetMSCount() - lastSaveWriteMs_ > 1000) flushSave();
}

const uint32_t* Emu::screen(int which) const {
    if (!nds_) return nullptr;
    int fb = nds_->GPU.FrontBuffer;
    return nds_->GPU.Framebuffer[fb][which].get();
}

int Emu::audioAvailable() const { return nds_ ? nds_->SPU.GetOutputSize() : 0; }

int Emu::readAudio(int16_t* out, int maxFrames) {
    if (!nds_) return 0;
    return nds_->SPU.ReadOutput(out, maxFrames);
}

// State file: "MSDSST01", then the hardware state (melonDS savestate) and the recompiled code's CPU
// state, each as u32 length + bytes (the CPU part is empty for states taken in --interp mode).
bool Emu::canSaveState(std::string* why) const {
    if (!nds_) { if (why) *why = "no game running"; return false; }
    return !useRecomp_ || recomp::canSaveState(why);
}

bool Emu::saveState(const std::string& path) {
    if (!canSaveState()) return false;
    return writeState(path, useRecomp_ ? recomp::saveState() : std::vector<uint8_t>());
}

int Emu::saveStateSoon(const std::string& path) {
    if (useRecomp_) {  // a save requested earlier was taken (or failed) during the last frame
        int r = recomp::saveAtCallResult();
        if (r == 1 || r == -1) { recomp::cancelSaveAtCall(); return r; }
    }
    if (canSaveState()) { if (useRecomp_) recomp::cancelSaveAtCall(); return saveState(path) ? 1 : -1; }
    if (!useRecomp_) return -1;
    if (recomp::saveAtCallResult() != 0) recomp::requestSaveAtCall([this, path](const std::vector<uint8_t>& rt) { return writeState(path, rt); });
    return 0;
}

void Emu::cancelSaveStateSoon() {
    if (useRecomp_) recomp::cancelSaveAtCall();
}

bool Emu::writeState(const std::string& path, const std::vector<uint8_t>& rt) {
    Savestate st;
    if (!nds_->DoSavestate(&st) || st.Error) return false;
    std::string tmp = path + ".tmp";
    FILE* f = fopen(tmp.c_str(), "wb");
    if (!f) return false;
    uint32_t n1 = st.Length(), n2 = (uint32_t)rt.size();
    fwrite("MSDSST01", 1, 8, f);
    fwrite(&n1, 4, 1, f);
    fwrite(st.Buffer(), 1, n1, f);
    fwrite(&n2, 4, 1, f);
    if (n2) fwrite(rt.data(), 1, n2, f);
    bool ok = fclose(f) == 0;
    if (ok) { remove(path.c_str()); ok = rename(tmp.c_str(), path.c_str()) == 0; }
    return ok;
}

bool Emu::loadState(const std::string& path, std::string* why) {
    auto fail = [&](const char* w) { if (why) *why = w; return false; };
    if (!nds_) return fail("no game running");
    auto b = readFile(path);
    if (b.empty()) return fail("no saved state");
    if (b.size() < 16 || memcmp(b.data(), "MSDSST01", 8) != 0) return fail("not a state of this version");
    uint32_t n1, n2;
    memcpy(&n1, &b[8], 4);
    if (12 + (size_t)n1 + 4 > b.size()) return fail("damaged state file");
    memcpy(&n2, &b[12 + n1], 4);
    if (16 + (size_t)n1 + n2 > b.size()) return fail("damaged state file");
    if (useRecomp_ && n2 == 0) return fail("state was saved in --interp mode");
    if (!useRecomp_ && n2 != 0) return fail("state was saved by the native build (run without --interp)");
    Savestate st(&b[12], n1, false);
    if (st.Error || !nds_->DoSavestate(&st) || st.Error) return fail("could not load the hardware state");
    if (useRecomp_ && !recomp::loadState(&b[16 + n1], n2)) return fail("could not restore the CPU state");
    return true;
}

uint16_t Emu::masterBrightness(int screen) const {
    if (!nds_) return 0;
    const bool aOnTop = nds_->PowerControl9 & 0x8000;
    const GPU2D::Unit& u = (screen == 0) == aOnTop ? nds_->GPU.GPU2D_A : nds_->GPU.GPU2D_B;
    return u.MasterBrightness;
}

bool Emu::dumpRam(const std::string& path) const {
    if (!nds_) return false;
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    fwrite(nds_->MainRAM, 1, 0x400000, f);
    fclose(f);
    return true;
}

bool Emu::dumpGpu(const std::string& path) const {
    if (!nds_) return false;
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    GPU& g = nds_->GPU;
    // header: magic, POWCNT1, then per engine: DispCnt, BGCnt[4], BGXPos[4], BGYPos[4]
    fwrite("MSGPU1\0\0", 1, 8, f);
    u32 pow = nds_->PowerControl9;
    fwrite(&pow, 4, 1, f);
    for (const GPU2D::Unit* u : {&g.GPU2D_A, &g.GPU2D_B}) {
        fwrite(&u->DispCnt, 4, 1, f);
        fwrite(u->BGCnt, 2, 4, f);
        fwrite(u->BGXPos, 2, 4, f);
        fwrite(u->BGYPos, 2, 4, f);
    }
    fwrite(g.Palette, 1, sizeof g.Palette, f);
    fwrite(g.OAM, 1, sizeof g.OAM, f);
    std::vector<u8> buf;
    auto dump = [&](u32 size, auto rd) {
        buf.resize(size);
        for (u32 a = 0; a < size; a += 4) { u32 v = rd(a); memcpy(&buf[a], &v, 4); }
        fwrite(buf.data(), 1, size, f);
    };
    dump(0x80000, [&](u32 a) { return g.ReadVRAM_ABG<u32>(a); });
    dump(0x40000, [&](u32 a) { return g.ReadVRAM_AOBJ<u32>(a); });
    dump(0x20000, [&](u32 a) { return g.ReadVRAM_BBG<u32>(a); });
    dump(0x20000, [&](u32 a) { return g.ReadVRAM_BOBJ<u32>(a); });
    fclose(f);
    return true;
}

void Emu::onSaveWrite(const uint8_t* data, uint32_t len) {
    pendingSave_.assign(data, data + len);
    saveDirty_ = true;
    lastSaveWriteMs_ = Platform::GetMSCount();
}

void Emu::flushSave() {
    if (!saveDirty_ || savPath_.empty()) return;
    std::string tmp = savPath_ + ".tmp";
    FILE* f = fopen(tmp.c_str(), "wb");
    if (!f) return;
    fwrite(pendingSave_.data(), 1, pendingSave_.size(), f);
    fclose(f);
    remove(savPath_.c_str());
    rename(tmp.c_str(), savPath_.c_str());
    saveDirty_ = false;
}
