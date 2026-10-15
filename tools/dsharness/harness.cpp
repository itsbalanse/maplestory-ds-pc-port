// Headless scripted DS runner built on the melonDS core (GPL-3.0).
// Used as a reference oracle: run a ROM with a scripted input sequence and dump screenshots / RAM.
//
// usage: harness <rom.nds> <script.txt> <outdir>
// script commands (one per line, '#' comments):
//   wait N                 run N frames
//   press KEY [N]          hold KEY for N frames (default 6), then release for 6 frames
//   hold KEY / release KEY
//   touch X Y [N]          touch bottom screen at (X,Y) for N frames (default 6)
//   shot NAME              save both screens as NAME.png (256x384)
//   save FILE / load FILE  savestates
//   ram ADDR LEN FILE      dump ARM9 bus memory
//   mash KEY N             press KEY repeatedly for N frames
// KEY: A B SELECT START RIGHT LEFT UP DOWN R L X Y
#include "NDS.h"
#include "NDSCart.h"
#include "GPU.h"
#include "Platform.h"
#include "Savestate.h"
#include "Args.h"

#include <cstdio>
#include <cstdarg>
#include <cstring>
#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <chrono>
#include <map>

using namespace melonDS;

// ------------------------------------------------------------------ Platform
namespace melonDS::Platform {
struct FileHandle { FILE* f; };
void SignalStop(StopReason, void*) {}
std::string GetLocalFilePath(const std::string& f) { return f; }
FileHandle* OpenFile(const std::string& path, FileMode mode) {
    std::string m;
    if ((mode & ReadWrite) == ReadWrite) m = (mode & Preserve) ? "r+" : "w+";
    else if (mode & Write) m = (mode & Append) ? "a" : "w";
    else m = "r";
    if (!(mode & Text)) m += "b";
    if ((mode & Preserve) && (mode & Write)) {
        FILE* t = fopen(path.c_str(), "rb");
        if (!t) { if (mode & NoCreate) return nullptr; t = fopen(path.c_str(), "wb"); }
        if (t) fclose(t);
    }
    FILE* f = fopen(path.c_str(), m.c_str());
    if (!f) return nullptr;
    return new FileHandle{f};
}
FileHandle* OpenLocalFile(const std::string& p, FileMode m) { return OpenFile(p, m); }
bool FileExists(const std::string& n) { FILE* f = fopen(n.c_str(), "rb"); if (f) fclose(f); return f != nullptr; }
bool LocalFileExists(const std::string& n) { return FileExists(n); }
bool CheckFileWritable(const std::string&) { return true; }
bool CheckLocalFileWritable(const std::string&) { return true; }
bool CloseFile(FileHandle* h) { if (!h) return false; fclose(h->f); delete h; return true; }
bool IsEndOfFile(FileHandle* h) { return feof(h->f); }
bool FileReadLine(char* s, int c, FileHandle* h) { return fgets(s, c, h->f) != nullptr; }
u64 FilePosition(FileHandle* h) { return _ftelli64(h->f); }
bool FileSeek(FileHandle* h, s64 o, FileSeekOrigin org) {
    int w = org == FileSeekOrigin::Start ? SEEK_SET : org == FileSeekOrigin::Current ? SEEK_CUR : SEEK_END;
    return _fseeki64(h->f, o, w) == 0;
}
void FileRewind(FileHandle* h) { rewind(h->f); }
u64 FileRead(void* d, u64 s, u64 c, FileHandle* h) { return fread(d, s, c, h->f); }
bool FileFlush(FileHandle* h) { return fflush(h->f) == 0; }
u64 FileWrite(const void* d, u64 s, u64 c, FileHandle* h) { return fwrite(d, s, c, h->f); }
u64 FileWriteFormatted(FileHandle* h, const char* fmt, ...) { va_list a; va_start(a, fmt); int r = vfprintf(h->f, fmt, a); va_end(a); return r; }
u64 FileLength(FileHandle* h) { auto p = _ftelli64(h->f); _fseeki64(h->f, 0, SEEK_END); auto l = _ftelli64(h->f); _fseeki64(h->f, p, SEEK_SET); return l; }
static bool g_verbose = false;
void Log(LogLevel lvl, const char* fmt, ...) {
    if (lvl < Warn && !g_verbose) return;
    va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a);
}
struct Thread { std::thread t; };
Thread* Thread_Create(std::function<void()> f) { return new Thread{std::thread(f)}; }
void Thread_Free(Thread* t) { if (t->t.joinable()) t->t.detach(); delete t; }
void Thread_Wait(Thread* t) { if (t->t.joinable()) t->t.join(); }
struct Semaphore { std::mutex m; std::condition_variable cv; int count = 0; };
Semaphore* Semaphore_Create() { return new Semaphore(); }
void Semaphore_Free(Semaphore* s) { delete s; }
void Semaphore_Reset(Semaphore* s) { std::lock_guard<std::mutex> l(s->m); s->count = 0; }
void Semaphore_Wait(Semaphore* s) { std::unique_lock<std::mutex> l(s->m); s->cv.wait(l, [&]{ return s->count > 0; }); s->count--; }
bool Semaphore_TryWait(Semaphore* s, int ms) {
    std::unique_lock<std::mutex> l(s->m);
    if (!s->cv.wait_for(l, std::chrono::milliseconds(ms), [&]{ return s->count > 0; })) return false;
    s->count--; return true;
}
void Semaphore_Post(Semaphore* s, int c) { { std::lock_guard<std::mutex> l(s->m); s->count += c; } s->cv.notify_all(); }
struct Mutex { std::mutex m; };
Mutex* Mutex_Create() { return new Mutex(); }
void Mutex_Free(Mutex* m) { delete m; }
void Mutex_Lock(Mutex* m) { m->m.lock(); }
void Mutex_Unlock(Mutex* m) { m->m.unlock(); }
bool Mutex_TryLock(Mutex* m) { return m->m.try_lock(); }
void Sleep(u64 us) { std::this_thread::sleep_for(std::chrono::microseconds(us)); }
u64 GetMSCount() { return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
u64 GetUSCount() { return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
static std::string g_savpath;
void WriteNDSSave(const u8* data, u32 len, u32, u32, void*) {
    if (g_savpath.empty()) return;
    FILE* f = fopen(g_savpath.c_str(), "wb"); if (f) { fwrite(data, 1, len, f); fclose(f); }
}
void WriteGBASave(const u8*, u32, u32, u32, void*) {}
void WriteFirmware(const Firmware&, u32, u32, void*) {}
void WriteDateTime(int, int, int, int, int, int, void*) {}
void MP_Begin(void*) {}
void MP_End(void*) {}
int MP_SendPacket(u8*, int, u64, void*) { return 0; }
int MP_RecvPacket(u8*, u64*, void*) { return 0; }
int MP_SendCmd(u8*, int, u64, void*) { return 0; }
int MP_SendReply(u8*, int, u64, u16, void*) { return 0; }
int MP_SendAck(u8*, int, u64, void*) { return 0; }
int MP_RecvHostPacket(u8*, u64*, void*) { return 0; }
u16 MP_RecvReplies(u8*, u64, u16, void*) { return 0; }
int Net_SendPacket(u8*, int, void*) { return 0; }
int Net_RecvPacket(u8*, void*) { return 0; }
void Camera_Start(int, void*) {}
void Camera_Stop(int, void*) {}
void Camera_CaptureFrame(int, u32*, int, int, bool, void*) {}
void Mic_Start(void*) {}
void Mic_Stop(void*) {}
int Mic_ReadInput(s16*, int, void*) { return 0; }
struct AACDecoder {};
AACDecoder* AAC_Init() { return nullptr; }
void AAC_DeInit(AACDecoder*) {}
bool AAC_Configure(AACDecoder*, int, int) { return false; }
bool AAC_DecodeFrame(AACDecoder*, const void*, int, void*, int) { return false; }
bool Addon_KeyDown(KeyType, void*) { return false; }
void Addon_RumbleStart(u32, void*) {}
void Addon_RumbleStop(void*) {}
float Addon_MotionQuery(MotionQueryType, void*) { return 0; }
struct DynamicLibrary {};
DynamicLibrary* DynamicLibrary_Load(const char*) { return nullptr; }
void DynamicLibrary_Unload(DynamicLibrary*) {}
void* DynamicLibrary_LoadFunction(DynamicLibrary*, const char*) { return nullptr; }
}

// ------------------------------------------------------------------ PNG (stored deflate)
static u32 crc_table[256];
static void crc_init() { for (u32 n = 0; n < 256; n++) { u32 c = n; for (int k = 0; k < 8; k++) c = c & 1 ? 0xedb88320u ^ (c >> 1) : c >> 1; crc_table[n] = c; } }
static u32 crc(const u8* b, size_t n, u32 c = 0xffffffffu) { for (size_t i = 0; i < n; i++) c = crc_table[(c ^ b[i]) & 0xff] ^ (c >> 8); return c; }
static void be32(std::vector<u8>& v, u32 x) { v.push_back(x >> 24); v.push_back(x >> 16); v.push_back(x >> 8); v.push_back(x); }
static void chunk(std::vector<u8>& out, const char* type, const std::vector<u8>& data) {
    be32(out, (u32)data.size());
    std::vector<u8> td(type, type + 4); td.insert(td.end(), data.begin(), data.end());
    out.insert(out.end(), td.begin(), td.end());
    be32(out, crc(td.data(), td.size()) ^ 0xffffffffu);
}
static bool write_png(const std::string& path, const u32* rgba, int w, int h) {
    std::vector<u8> raw;
    for (int y = 0; y < h; y++) {
        raw.push_back(0);
        for (int x = 0; x < w; x++) { u32 p = rgba[y * w + x]; raw.push_back((p >> 16) & 0xff); raw.push_back((p >> 8) & 0xff); raw.push_back(p & 0xff); }
    }
    std::vector<u8> z = {0x78, 0x01};
    size_t pos = 0;
    while (pos < raw.size()) {
        size_t n = std::min<size_t>(65535, raw.size() - pos);
        z.push_back(pos + n == raw.size()); z.push_back(n & 0xff); z.push_back(n >> 8); z.push_back(~n & 0xff); z.push_back((~n >> 8) & 0xff);
        z.insert(z.end(), raw.begin() + pos, raw.begin() + pos + n); pos += n;
    }
    u32 a = 1, b = 0; for (u8 c : raw) { a = (a + c) % 65521; b = (b + a) % 65521; }
    be32(z, (b << 16) | a);
    std::vector<u8> out = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    std::vector<u8> ihdr; be32(ihdr, w); be32(ihdr, h); ihdr.push_back(8); ihdr.push_back(2); ihdr.push_back(0); ihdr.push_back(0); ihdr.push_back(0);
    chunk(out, "IHDR", ihdr); chunk(out, "IDAT", z); chunk(out, "IEND", {});
    FILE* f = fopen(path.c_str(), "wb"); if (!f) return false;
    fwrite(out.data(), 1, out.size(), f); fclose(f); return true;
}

// ------------------------------------------------------------------ main
static const std::map<std::string, int> KEYS = {
    {"A", 0}, {"B", 1}, {"SELECT", 2}, {"START", 3}, {"RIGHT", 4}, {"LEFT", 5}, {"UP", 6}, {"DOWN", 7}, {"R", 8}, {"L", 9}, {"X", 10}, {"Y", 11}};

int main(int argc, char** argv) {
    if (argc < 4) { fprintf(stderr, "usage: harness rom.nds script.txt outdir [savefile]\n"); return 1; }
    fprintf(stderr, "harness start\n"); fflush(stderr);
    crc_init();
    std::string outdir = argv[3];
    if (argc > 4) melonDS::Platform::g_savpath = argv[4];
    if (getenv("HARNESS_VERBOSE")) melonDS::Platform::g_verbose = true;

    std::ifstream rf(argv[1], std::ios::binary);
    std::vector<char> rom((std::istreambuf_iterator<char>(rf)), {});
    auto romdata = std::make_unique<u8[]>(rom.size());
    memcpy(romdata.get(), rom.data(), rom.size());

    std::unique_ptr<u8[]> sram; u32 sramlen = 0;
    if (!melonDS::Platform::g_savpath.empty()) {
        std::ifstream sf(melonDS::Platform::g_savpath, std::ios::binary);
        if (sf) { std::vector<char> s((std::istreambuf_iterator<char>(sf)), {}); sramlen = s.size(); sram = std::make_unique<u8[]>(sramlen); memcpy(sram.get(), s.data(), sramlen); }
    }
    NDSCart::NDSCartArgs cargs{};
    cargs.SRAM = std::move(sram); cargs.SRAMLength = sramlen;
    auto cart = NDSCart::ParseROM(std::move(romdata), (u32)rom.size(), nullptr, std::move(cargs));
    if (!cart) { fprintf(stderr, "bad rom\n"); return 1; }

    NDSArgs args{};
    args.JIT = std::nullopt;
    auto nds = std::make_unique<NDS>(std::move(args), nullptr);
    nds->Reset();
    nds->SetNDSCart(std::move(cart));
    nds->SetupDirectBoot("game.nds");
    nds->Start();

    u32 keymask = 0xFFF;
    bool touching = false; int tx = 0, ty = 0;
    u64 frame = 0;
    auto run = [&](int n) {
        for (int i = 0; i < n; i++) {
            nds->SetKeyMask(keymask);
            if (touching) nds->TouchScreen(tx, ty); else nds->ReleaseScreen();
            nds->RunFrame(); frame++;
        }
    };

    std::ifstream sc(argv[2]);
    std::string line;
    while (std::getline(sc, line)) {
        auto h = line.find('#'); if (h != std::string::npos) line = line.substr(0, h);
        std::istringstream ss(line);
        std::string cmd; if (!(ss >> cmd)) continue;
        if (cmd == "wait") { int n; ss >> n; run(n); }
        else if (cmd == "press" || cmd == "hold" || cmd == "release" || cmd == "mash") {
            std::string k; ss >> k; int n = 6; ss >> n;
            auto it = KEYS.find(k); if (it == KEYS.end()) { fprintf(stderr, "bad key %s\n", k.c_str()); continue; }
            u32 bit = 1u << it->second;
            if (cmd == "hold") keymask &= ~bit;
            else if (cmd == "release") keymask |= bit;
            else if (cmd == "press") { keymask &= ~bit; run(n); keymask |= bit; run(6); }
            else { for (int i = 0; i < n; i += 8) { keymask &= ~bit; run(4); keymask |= bit; run(4); } }
        }
        else if (cmd == "touch") { int n = 6; ss >> tx >> ty >> n; touching = true; run(n); touching = false; run(6); }
        else if (cmd == "shot") {
            std::string name; ss >> name;
            int fb = nds->GPU.FrontBuffer;
            std::vector<u32> img(256 * 384);
            memcpy(img.data(), nds->GPU.Framebuffer[fb][0].get(), 256 * 192 * 4);
            memcpy(img.data() + 256 * 192, nds->GPU.Framebuffer[fb][1].get(), 256 * 192 * 4);
            write_png(outdir + "/" + name + ".png", img.data(), 256, 384);
            printf("shot %s at frame %llu\n", name.c_str(), (unsigned long long)frame);
        }
        else if (cmd == "save") {
            std::string fn; ss >> fn;
            Savestate st; nds->DoSavestate(&st);
            FILE* f = fopen(fn.c_str(), "wb"); fwrite(st.Buffer(), 1, st.Length(), f); fclose(f);
        }
        else if (cmd == "load") {
            std::string fn; ss >> fn;
            std::ifstream f(fn, std::ios::binary); std::vector<char> b((std::istreambuf_iterator<char>(f)), {});
            Savestate st(b.data(), (u32)b.size(), false); nds->DoSavestate(&st);
        }
        else if (cmd == "ram") {
            std::string a, l, fn; ss >> a >> l >> fn;
            u32 addr = std::stoul(a, nullptr, 0), len = std::stoul(l, nullptr, 0);
            std::vector<u8> buf(len);
            for (u32 i = 0; i < len; i++) buf[i] = nds->ARM9Read8(addr + i);
            FILE* f = fopen(fn.c_str(), "wb"); fwrite(buf.data(), 1, len, f); fclose(f);
        }
        else if (cmd == "itcm") {  // itcm FILE: dump the ARM9's 32 KB ITCM (not visible on the bus)
            std::string fn; ss >> fn;
            FILE* f = fopen(fn.c_str(), "wb"); fwrite(nds->ARM9.ITCM, 1, ITCMPhysicalSize, f); fclose(f);
        }
        else fprintf(stderr, "unknown command %s\n", cmd.c_str());
    }
    printf("done, %llu frames\n", (unsigned long long)frame);
    return 0;
}
