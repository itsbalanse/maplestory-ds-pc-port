// Test hooks (see testhooks.h). OS_WaitVBlankIntr (FUN_020c4f74) is overridden: every frame loop
// of the game calls it with no Lua code running, so queued chunks run there through the game's
// own Lua: luaL_loadstring (FUN_020aefe0) + lua_pcall (FUN_020a574c) on the script engine's state.
#include "testhooks.h"
#include "recomp.h"

#include "ARM.h"
#include "NDS.h"

#include <cstdio>
#include <cstdlib>
#include <deque>

#define WEAK __attribute__((weak))
extern "C" {
WEAK void f_ram_020c4f74(Cpu*);  // OS_WaitVBlankIntr
WEAK void f_ram_020aefe0(Cpu*);  // luaL_loadstring(L, s)
WEAK void f_ram_020a574c(Cpu*);  // lua_pcall(L, nargs, nresults, errfunc)
WEAK void f_ram_020a50f0(Cpu*);  // lua_tolstring(L, idx, len*)
void ovr_WaitVBlankIntr(Cpu* c);
}

namespace {
constexpr uint32_t kScriptEngine = 0x021562c0u;  // the game's script engine object; +4: lua_State*
constexpr uint32_t kRet = 0x020c4f74u;
std::deque<std::string> g_queue;
bool g_busy = false;

uint32_t call(Cpu* c, void (*fn)(Cpu*), uint32_t a0, uint32_t a1 = 0, uint32_t a2 = 0, uint32_t a3 = 0) {
    c->r[0] = a0; c->r[1] = a1; c->r[2] = a2; c->r[3] = a3;
    c->r[14] = kRet;
    SS_PUSH(kRet);
    fn(c);
    SS_POP();
    return c->r[0];
}

std::string readCString(Cpu* c, uint32_t a, size_t max = 512) {
    std::string s;
    for (size_t i = 0; i < max; i++) {
        uint8_t ch = mem_read8(c, a + (uint32_t)i);
        if (!ch) break;
        s += (char)ch;
    }
    return s;
}

void runChunk(Cpu* c, const std::string& code) {
    const uint32_t L = mem_read32(c, kScriptEngine + 4);
    const uint32_t sp = c->r[13];
    const uint32_t len = (uint32_t)code.size() + 1;
    const uint32_t buf = (sp - 0x100 - len) & ~7u;
    for (uint32_t i = 0; i < len; i++) mem_write8(c, buf + i, i + 1 < len ? (uint8_t)code[i] : 0);
    c->r[13] = buf - 0x20;
    int err = (int)call(c, f_ram_020aefe0, L, buf);
    if (err == 0) err = (int)call(c, f_ram_020a574c, L, 0, 0, 0);
    if (err) {
        uint32_t msg = call(c, f_ram_020a50f0, L, (uint32_t)-1, 0);
        fprintf(stderr, "[lua] error %d in \"%s\": %s\n", err, code.c_str(), msg ? readCString(c, msg).c_str() : "?");
    } else {
        fprintf(stderr, "[lua] ok: %s\n", code.c_str());
    }
    c->r[13] = sp;
}
}  // namespace

// ---------------------------------------------------------------- interpreter mode
// At the entry of OS_WaitVBlankIntr (Thumb), the hook saves the registers, writes a Thumb stub,
// the string and a literal pool below the stack, and jumps to the stub:
//   r0 = luaL_loadstring(L, s); if (r0 == 0) r0 = lua_pcall(L, 0, 0, 0); *result = r0; bx 020c4f75
// When execution is back at the function entry, the result is logged and the registers restored.
namespace {
using melonDS::ARMv5;
using melonDS::u32;
using melonDS::u8;
struct Pending { bool active = false; u32 regs[16]; u32 cpsr; u32 resultAt; std::string code; } g_ip;

// The stub lives in the top of ITCM, which the game never uses (code ends below 0x01ffeaa0): the
// main thread's stack is in DTCM, which cannot hold code.
constexpr u32 kStubAt = 0x01fff000u;
u8* itcm(ARMv5* cpu, u32 a) { return &cpu->ITCM[a & (melonDS::ITCMPhysicalSize - 1)]; }
void wr32(ARMv5* cpu, u32 a, u32 v) { memcpy(itcm(cpu, a), &v, 4); }
void wr16(ARMv5* cpu, u32 a, uint16_t v) { memcpy(itcm(cpu, a), &v, 2); }
u32 rd32(ARMv5* cpu, u32 a) { u32 v; memcpy(&v, itcm(cpu, a), 4); return v; }
u32 ram32(ARMv5* cpu, u32 a) { u32 v; memcpy(&v, &cpu->NDS.MainRAM[a & cpu->NDS.MainRAMMask], 4); return v; }

void interpLuaHook(ARMv5* cpu, u32 addr) {
    if (addr != 0x020c4f74u) return;
    if (g_ip.active) {  // back from the stub
        const int err = (int)rd32(cpu, g_ip.resultAt);
        if (err) fprintf(stderr, "[lua] error %d in \"%s\"\n", err, g_ip.code.c_str());
        else fprintf(stderr, "[lua] ok: %s\n", g_ip.code.c_str());
        for (int i = 0; i < 15; i++) cpu->R[i] = g_ip.regs[i];
        cpu->CPSR = g_ip.cpsr;
        g_ip.active = false;
    }
    if (g_queue.empty()) return;
    if (g_queue.front().size() > 0xF00 - 64) { g_queue.pop_front(); return; }
    g_ip.code = g_queue.front();
    g_queue.pop_front();
    const u32 len = (u32)g_ip.code.size() + 1;
    const u32 S = kStubAt;
    static const uint16_t kStub[16] = {
        0x4807,  // ldr r0, [L]
        0x4908,  // ldr r1, [STR]
        0x4A08,  // ldr r2, [LOADSTRING]
        0x4790,  // blx r2
        0x2800,  // cmp r0, #0
        0xD105,  // bne done
        0x4804,  // ldr r0, [L]
        0x2100, 0x2200, 0x2300,  // movs r1-r3, #0
        0x4F05,  // ldr r7, [PCALL]
        0x47B8,  // blx r7
        0x4905,  // done: ldr r1, [RESULT]
        0x6008,  // str r0, [r1]
        0x4905,  // ldr r1, [RET]
        0x4708,  // bx r1
    };
    for (int i = 0; i < 16; i++) wr16(cpu, S + i * 2, kStub[i]);
    const u32 L = ram32(cpu, kScriptEngine + 4);
    const u32 str = S + 60;
    g_ip.resultAt = S + 56;
    wr32(cpu, S + 32, L);
    wr32(cpu, S + 36, str);
    wr32(cpu, S + 40, 0x020aefe0u | 1);  // luaL_loadstring
    wr32(cpu, S + 44, 0x020a574cu | 1);  // lua_pcall
    wr32(cpu, S + 48, g_ip.resultAt);
    wr32(cpu, S + 52, 0x020c4f74u | 1);  // back to OS_WaitVBlankIntr
    wr32(cpu, S + 56, 0xFFFFFFFFu);
    for (u32 i = 0; i < len; i++) *itcm(cpu, str + i) = i + 1 < len ? (uint8_t)g_ip.code[i] : 0;
    cpu->ICacheInvalidateAll();
    for (int i = 0; i < 15; i++) g_ip.regs[i] = cpu->R[i];
    g_ip.cpsr = cpu->CPSR;
    g_ip.active = true;
    if (getenv("MSDS_LUA_DEBUG")) fprintf(stderr, "[lua] stub at %08x (L %08x, cpsr %08x)\n", S, L, cpu->CPSR);
    cpu->JumpTo(S | 1);
}
}  // namespace

namespace recomp {
void queueLua(const std::string& code) { g_queue.push_back(code); }
bool luaPending() { return !g_queue.empty() || g_ip.active; }
void enableInterpLua() {
    static void (*prev)(ARMv5*, u32) = nullptr;
    prev = ARMv5::InstrHook;  // e.g. the function-entry tracer: keep it running
    ARMv5::InstrHook = [](ARMv5* cpu, u32 addr) {
        if (prev) prev(cpu, addr);
        interpLuaHook(cpu, addr);
    };
}
}

extern "C" void ovr_WaitVBlankIntr(Cpu* c) {
    if (!c->resume) rt_safe_call_point(c, 0x020c4f74u);  // save states in busy scenes
    if (!g_queue.empty() && !g_busy && f_ram_020aefe0 && !c->resume) {  // resume: see save states
        g_busy = true;
        const uint32_t lr = c->r[14], r0 = c->r[0], r1 = c->r[1], r2 = c->r[2], r3 = c->r[3];
        while (!g_queue.empty()) {
            std::string code = g_queue.front();
            g_queue.pop_front();
            runChunk(c, code);
        }
        c->r[0] = r0; c->r[1] = r1; c->r[2] = r2; c->r[3] = r3; c->r[14] = lr;
        g_busy = false;
    }
    f_ram_020c4f74(c);
}
