#include "emu.h"

#include "NDS.h"
#include "NDSCart.h"
#include "GPU.h"
#include "SPU.h"
#include "Savestate.h"
#include "Args.h"
#include "Platform.h"
#include "runtime.h"

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
    if (useRecomp_ || getenv("MSDS_TRACE") || getenv("MSDS_ITRACE")) args.JIT = std::nullopt;  // ARM7 interpreted; ARM9 recompiled (or traced)
    nds_ = std::make_unique<NDS>(std::move(args), this);
    nds_->Reset();
    nds_->SetNDSCart(std::move(cart));
    nds_->SetupDirectBoot(romPath);
    nds_->Start();
    if (useRecomp_) recomp::attach(nds_.get(), nds_->NDSCartSlot.GetCart()->GetHeader().ARM9EntryAddress);
    if (getenv("MSDS_TRACE") || getenv("MSDS_ITRACE")) recomp::traceStart(getenv("MSDS_TRACE"), !useRecomp_);
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

bool Emu::saveState(const std::string& path) {
    if (!nds_ || useRecomp_) return false;  // recompiled code keeps state on the host stack
    Savestate st;
    if (!nds_->DoSavestate(&st) || st.Error) return false;
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    fwrite(st.Buffer(), 1, st.Length(), f);
    fclose(f);
    return true;
}

bool Emu::loadState(const std::string& path) {
    if (!nds_ || useRecomp_) return false;
    auto b = readFile(path);
    if (b.empty()) return false;
    Savestate st(b.data(), (u32)b.size(), false);
    if (st.Error) return false;
    return nds_->DoSavestate(&st) && !st.Error;
}

uint16_t Emu::masterBrightness(int screen) const {
    if (!nds_) return 0;
    const bool aOnTop = nds_->PowerControl9 & 0x8000;
    const GPU2D::Unit& u = (screen == 0) == aOnTop ? nds_->GPU.GPU2D_A : nds_->GPU.GPU2D_B;
    return u.MasterBrightness;
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
