// Runtime for recompiled ARM9 code: connects generated C to the melonDS hardware model.
// See port/DESIGN.md for the execution model.
#include "runtime.h"
#include "recomp.h"
#include "table.h"

#include "NDS.h"
#include "ARM.h"
#include "NDSCart.h"
#include "ARMInterpreter.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdio>
#include <cstdarg>
#include <cstdlib>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <string>

using namespace melonDS;

namespace {

NDS* g_nds = nullptr;
ARMv5* g_arm9 = nullptr;
Cpu C{};
bool g_active = false;
bool g_halted = false;
struct Stats { uint64_t yields = 0, irqs = 0, halts = 0, calls = 0, swis = 0, threadSwitches = 0; } g_stats;
uint32_t g_recentCalls[64]; unsigned g_recentPos = 0;
uint32_t g_lastIrqHandler = 0;
FILE* g_log = nullptr;

// ------------------------------------------------------------------ logging
void logf(const char* fmt, ...) {
    va_list a;
    va_start(a, fmt);
    vfprintf(stderr, fmt, a);
    va_end(a);
    if (g_log) {
        va_start(a, fmt);
        vfprintf(g_log, fmt, a);
        va_end(a);
        fflush(g_log);
    }
}

[[noreturn]] void fatal(const char* fmt, ...) {
    char buf[1024];
    va_list a;
    va_start(a, fmt);
    vsnprintf(buf, sizeof buf, fmt, a);
    va_end(a);
    logf("FATAL: %s\n  r0=%08x r1=%08x r2=%08x r3=%08x r4=%08x sp=%08x lr=%08x cpsr=%08x ret=%08x\n", buf,
         C.r[0], C.r[1], C.r[2], C.r[3], C.r[4], C.r[13], C.r[14], C.cpsr, C.ret);
    if (g_nds && (C.r[0] >> 24) == 0x02) {
        uint32_t obj = C.r[0], vt = mem_read32(&C, obj);
        logf("  [r0]=%08x", vt);
        if ((vt >> 24) == 0x02) {
            logf(" vtable:");
            for (int i = 0; i < 6; i++) logf(" %08x", mem_read32(&C, vt + i * 4));
        }
        logf("\n  obj bytes:");
        for (int i = 0; i < 8; i++) logf(" %08x", mem_read32(&C, obj + i * 4));
        logf("\n");
    }
    logf("  shadow stack (%u):", C.ssp);
    for (uint32_t i = C.ssp > 12 ? C.ssp - 12 : 0; i < C.ssp && C.ss; i++) logf(" %08x", C.ss[i]);
    logf("\n");
    if (!getenv("MSDS_HEADLESS")) MessageBoxA(nullptr, buf, "MapleStory DS - recompiled code error", MB_ICONERROR);
    std::exit(3);
}

// ------------------------------------------------------------------ fibers (one per guest thread)
constexpr uint32_t kTokenBase = 0xF0000000u;  // fake PCs that stand for "resume this fiber"
constexpr uint32_t kSaveCtxResume = 0x020c3b3cu;  // OS_SaveContext's "return 1" stub (bx lr)
constexpr uint32_t kBiosIrqRet = 0xFFFF0280u;
constexpr uint32_t kRootRet = 0xFFFF0290u;
constexpr uint32_t kOvrRet = 0xFFFF02A0u;
constexpr uint32_t kColdReturn = 0xFFFF02B0u;  // fiber entry: continue at lr, as if a leaf call returned
constexpr uint32_t kColdCall = 0xFFFF02C0u;    // fiber entry: call g_coldCall (state taken at its entry)
uint32_t g_coldCall = 0;

struct Fiber {
    void* handle = nullptr;
    uint32_t id = 0;
    uint32_t token = 0;
    uint32_t entry = 0;
    std::vector<uint32_t> ss = std::vector<uint32_t>(1 << 16);  // shadow return stack
    uint32_t ssp = 0;
    uint32_t depth = 0;      // see g_depth
    bool savedAtRoot = true; // parked by OS_SaveContext with no runtime frame below (save states)
};

void* g_hostFiber = nullptr;
std::vector<Fiber*> g_fibers;
Fiber* g_cur = nullptr;
std::unordered_map<uint32_t, Fiber*> g_parkedBySp;  // guest SP saved by OS_SaveContext -> fiber
std::unordered_set<Fiber*> g_tokenParked;  // threads switched out by an IRQ (resumable only on their own fiber)
std::unordered_map<uint32_t, Fiber*> g_byToken;
uint32_t g_nextFiberId = 0;
// Save states: how a thread switched out by an IRQ can be restarted without its fiber.
// 0: it cannot; kColdReturn: it waited in a leaf `wait for interrupt` call (continue at lr);
// otherwise the entry (| Thumb bit) of the function it was about to run (call it again).
uint32_t g_yieldPark = 0;        // for the yield in progress
// Nested callExpect frames of the current thread. 1 = only its root: everything else on its host
// stack is generated code, which a save state can rebuild from return sites. Deeper means a runtime
// frame (IRQ, override, interpreter) is in the middle of something a save state cannot capture.
uint32_t g_depth = 0;
std::unordered_map<Fiber*, uint32_t> g_parkHow;           // token-parked fiber -> how (see above)
std::unordered_map<uint32_t, uint32_t> g_coldTokens;      // after a load: token -> how
bool g_haltWfi = false;  // the current thread waits in a leaf `wait for interrupt` (CP15) call

void runAt(uint32_t pc);

void WINAPI fiberMain(void* arg) {
    Fiber* f = static_cast<Fiber*>(arg);
    runAt(f->entry);
    fatal("guest thread starting at %08x ran off its root", f->entry);
}

Fiber* newFiber(uint32_t entry) {
    Fiber* f = new Fiber();
    f->id = g_nextFiberId++;
    f->token = kTokenBase + f->id * 0x10;
    g_byToken[f->token] = f;
    f->entry = entry;
    f->handle = CreateFiberEx(64 * 1024, 64 * 1024 * 1024, FIBER_FLAG_FLOAT_SWITCH, fiberMain, f);
    if (!f->handle) fatal("CreateFiberEx failed");
    g_fibers.push_back(f);
    logf("[rt] new guest thread fiber %u at %08x\n", f->id, entry);
    return f;
}

void switchTo(Fiber* f) {
    if (f == g_cur) return;
    g_stats.threadSwitches++;
    Fiber* prev = g_cur;
    prev->ssp = C.ssp;
    prev->depth = g_depth;
    g_cur = f;
    C.ss = f->ss.data();
    C.ssp = f->ssp;
    g_depth = f->depth;
    SwitchToFiber(f->handle);
    // resumed: g_cur was set back to prev by whoever switched to us
    C.ss = prev->ss.data();
    C.ssp = prev->ssp;
    g_depth = prev->depth;
}

// ------------------------------------------------------------------ CPSR / banking
int bankOf(uint32_t mode) {
    switch (mode & 0x1F) {
    case 0x11: return 1;  // fiq
    case 0x12: return 2;  // irq
    case 0x13: return 3;  // svc
    case 0x17: return 4;  // abt
    case 0x1B: return 5;  // und
    default: return 0;    // usr / sys
    }
}
uint32_t g_bankR13[6], g_bankR14[6], g_bankSpsr[6];

void switchMode(uint32_t oldMode, uint32_t newMode) {
    int ob = bankOf(oldMode), nb = bankOf(newMode);
    if (ob == nb) return;
    g_bankR13[ob] = C.r[13]; g_bankR14[ob] = C.r[14]; g_bankSpsr[ob] = C.spsr;
    C.r[13] = g_bankR13[nb]; C.r[14] = g_bankR14[nb]; C.spsr = g_bankSpsr[nb];
}

void setFlagsFrom(uint32_t psr) {
    C.NG = (psr >> 31) & 1; C.ZR = (psr >> 30) & 1; C.CY = (psr >> 29) & 1; C.OV = (psr >> 28) & 1;
    C.Q = (psr >> 27) & 1; C.TB = (psr >> 5) & 1;
}

// Move to a new full PSR value (mode switch + flags)
void loadPsr(uint32_t psr) {
    uint32_t old = C.cpsr;
    switchMode(old & 0x1F, psr & 0x1F);
    C.cpsr = psr;
    setFlagsFrom(psr);
}

void refreshTcm() {
    C.itcm = g_arm9->ITCM;
    C.itcm_size = g_arm9->ITCMSize;
    C.dtcm = g_arm9->DTCM;
    C.dtcm_base = g_arm9->DTCMBase;
    C.dtcm_mask = g_arm9->DTCMMask;
}

// ------------------------------------------------------------------ dispatch
struct Candidates { std::vector<const GuestFnEntry*> e; const GuestFnEntry* last = nullptr; };
std::unordered_map<uint32_t, Candidates> g_fnmap;

GuestFn lookup(uint32_t addr) {
    auto it = g_fnmap.find(addr);
    if (it == g_fnmap.end()) return nullptr;
    Candidates& cs = it->second;
    if (cs.e.size() == 1 && cs.e[0]->overlay < 0) return cs.e[0]->fn;
    // Overlay code lives in main RAM: compare the candidates' original bytes with what is resident.
    // (ITCM above 0x01ff8500 also swaps images: overlay 0 vs. the movie decoder)
    const uint8_t* ram = addr < C.itcm_size ? g_arm9->ITCM + (addr & (ITCMPhysicalSize - 1))
                                            : C.main_ram + (addr & C.main_ram_mask);
    auto matches = [&](const GuestFnEntry* e) {
        if (e->overlay < 0) return true;
        if (e->body) return memcmp(ram, e->body, e->body_len) == 0;
        return mem_read32(&C, addr) == e->sig[0] && mem_read32(&C, addr + 4) == e->sig[1];
    };
    if (cs.last && matches(cs.last)) return cs.last->fn;
    for (auto* e : cs.e) {
        if (matches(e)) { cs.last = e; return e->fn; }
    }
    return nullptr;
}

// Return sites -> owning functions (g_resume_points): threads restored from a save state continue
// there natively (the function is entered with c->resume set and jumps to the site).
std::unordered_map<uint32_t, std::vector<const GuestFnEntry*>> g_resumeMap;

const GuestFnEntry* resumeOwner(uint32_t site) {
    auto it = g_resumeMap.find(site);
    if (it == g_resumeMap.end()) return nullptr;
    for (const GuestFnEntry* e : it->second) {
        if (e->overlay < 0) return e;
        const uint8_t* ram = e->addr < C.itcm_size ? g_arm9->ITCM + (e->addr & (ITCMPhysicalSize - 1))
                                                   : C.main_ram + (e->addr & C.main_ram_mask);
        if (e->body ? memcmp(ram, e->body, e->body_len) == 0
                    : mem_read32(&C, e->addr) == e->sig[0] && mem_read32(&C, e->addr + 4) == e->sig[1])
            return e;
    }
    return nullptr;
}

bool resumeAt(uint32_t site) {
    const GuestFnEntry* e = resumeOwner(site & ~1u);
    if (!e) return false;
    C.resume = site & ~1u;
    e->fn(&C);
    C.resume = 0;
    return true;
}

void callExpect(uint32_t target, uint32_t expected);
}  // namespace
extern "C" { static bool forceInterp(uint32_t addr); static int residentOverlay(uint32_t addr); }
static int g_interpOverlay = getenv("MSDS_INTERP_OV") ? atoi(getenv("MSDS_INTERP_OV")) : 200;  // debug: image to force-interpret
namespace {

// ------------------------------------------------------------------ interpreter fallback
// Mirror our register model into melonDS's (current mode in R[], other modes in R_xxx banks,
// user r13/r14 parked in the current privileged mode's bank) and back.
u32* melonBank(int b) {
    switch (b) {
    case 1: return &g_arm9->R_FIQ[5];
    case 2: return g_arm9->R_IRQ;
    case 3: return g_arm9->R_SVC;
    case 4: return g_arm9->R_ABT;
    case 5: return g_arm9->R_UND;
    }
    return nullptr;
}

void syncToMelon() {
    int cur = bankOf(C.cpsr);
    for (int i = 0; i < 15; i++) g_arm9->R[i] = C.r[i];
    g_arm9->CPSR = rt_cpsr_read(&C);
    for (int b = 1; b < 6; b++) {
        u32* bk = melonBank(b);
        if (b == cur) { bk[0] = g_bankR13[0]; bk[1] = g_bankR14[0]; bk[2] = C.spsr; }
        else { bk[0] = g_bankR13[b]; bk[1] = g_bankR14[b]; bk[2] = g_bankSpsr[b]; }
    }
}

void syncFromMelon() {
    uint32_t psr = g_arm9->CPSR;
    int cur = bankOf(psr);
    for (int i = 0; i < 15; i++) C.r[i] = g_arm9->R[i];
    C.cpsr = psr;
    setFlagsFrom(psr);
    for (int b = 1; b < 6; b++) {
        u32* bk = melonBank(b);
        if (b == cur) { g_bankR13[0] = bk[0]; g_bankR14[0] = bk[1]; C.spsr = bk[2]; }
        else { g_bankR13[b] = bk[0]; g_bankR14[b] = bk[1]; g_bankSpsr[b] = bk[2]; }
    }
}

void stepInterpreter(ARMv5* a) {
    if (a->CPSR & 0x20) {
        a->R[15] += 2;
        a->CurInstr = a->NextInstr[0];
        a->NextInstr[0] = a->NextInstr[1];
        if (a->R[15] & 0x2) { a->NextInstr[1] >>= 16; a->CodeCycles = 0; }
        else a->NextInstr[1] = a->CodeRead32(a->R[15], false);
        ARMInterpreter::THUMBInstrTable[(a->CurInstr >> 6) & 0x3FF](a);
    } else {
        a->R[15] += 4;
        a->CurInstr = a->NextInstr[0];
        a->NextInstr[0] = a->NextInstr[1];
        a->NextInstr[1] = a->CodeRead32(a->R[15], false);
        if (a->CheckCondition(a->CurInstr >> 28))
            ARMInterpreter::ARMInstrTable[((a->CurInstr >> 4) & 0xF) | ((a->CurInstr >> 16) & 0xFF0)](a);
        else if ((a->CurInstr & 0xFE000000) == 0xFA000000) ARMInterpreter::A_BLX_IMM(a);
        else a->AddCycles_C();
    }
    g_nds->ARM9Timestamp += a->Cycles;
    a->Cycles = 0;
}

uint64_t g_interpSteps = 0;

void interpretAt(uint32_t target) {
    syncToMelon();
    g_arm9->JumpTo(target);  // bit 0 selects Thumb, like BX
    g_nds->ARM9Timestamp = (u64)C.cycles;
    for (;;) {
        uint32_t pc = g_arm9->R[15] - ((g_arm9->CPSR & 0x20) ? 2 : 4);
        if (rt_in_stack(&C, pc)) { C.ret = pc; break; }  // returned to a recompiled frame
        if (lookup(pc) && pc != target && !(forceInterp(pc) && residentOverlay(pc) == g_interpOverlay)) {
            // calls back into recompiled code: run it natively, then resume interpreting at lr
            syncFromMelon();
            uint32_t back = C.r[14] & ~1u, thumb = C.r[14] & 1;
            callExpect(pc, back);
            syncToMelon();
            g_arm9->JumpTo(back | thumb);
            continue;
        }
        // debug: MSDS_INTERP_LOG=<addr>:<n> logs n instructions of a fallback that starts at addr
        static uint32_t dbgAt = getenv("MSDS_INTERP_LOG") ? (uint32_t)strtoul(getenv("MSDS_INTERP_LOG"), nullptr, 16) : 0;
        static int dbgLeft = getenv("MSDS_INTERP_LOG") && strchr(getenv("MSDS_INTERP_LOG"), ':') ? atoi(strchr(getenv("MSDS_INTERP_LOG"), ':') + 1) : 0;
        if (dbgLeft > 0 && (target & ~1u) == dbgAt) {
            dbgLeft--;
            logf("[interp] pc=%08x cpsr=%08x r0=%08x r1=%08x r2=%08x r3=%08x r4=%08x sp=%08x lr=%08x\n", pc,
                 g_arm9->CPSR, g_arm9->R[0], g_arm9->R[1], g_arm9->R[2], g_arm9->R[3], g_arm9->R[4], g_arm9->R[13], g_arm9->R[14]);
        }
        stepInterpreter(g_arm9);
        g_interpSteps++;
        if (g_arm9->Halted == 1) {  // wait for interrupt inside interpreted code
            g_arm9->Halted = 0;
            syncFromMelon();
            g_halted = true;
            while (g_halted) rt_yield(&C);
            syncToMelon();
        }
        if ((int64_t)g_nds->ARM9Timestamp >= C.target || g_arm9->Halted == 2) {
            // end of the scheduler slice: let the hardware run, take IRQs natively, then continue
            g_arm9->Halted = 0;
            syncFromMelon();
            C.cycles = (int64_t)g_nds->ARM9Timestamp;
            rt_yield(&C);
            syncToMelon();
            g_nds->ARM9Timestamp = (u64)C.cycles;
        }
    }
    syncFromMelon();
    C.cycles = (int64_t)g_nds->ARM9Timestamp;
}

void callAt(uint32_t target) {
    // computed jumps (bx/pop pc) pass the target with bit 0 cleared and the instruction set in TB:
    // keep it, or interpreted fallbacks would run Thumb code as ARM (undefined instruction -> hang)
    if (!(target & 1) && C.TB) target |= 1;
    uint32_t origTarget = target;
    target &= ~1u;
    g_stats.calls++;
    g_recentCalls[g_recentPos++ & 63] = target;
    GuestFn fn = lookup(target);
    if (fn) { fn(&C); return; }
    // a return site (e.g. a thread resumed from a save state, or setjmp's return after longjmp)
    if (resumeAt(target)) return;
    // jump into the middle of hand-written assembly: use the owning function's multi-entry variant
    for (unsigned i = 0; i < g_guest_range_count; i++) {
        const GuestRange& r = g_guest_ranges[i];
        if (target < r.start || target >= r.end) continue;
        if (r.body) {
            const uint8_t* mem = r.entry < C.itcm_size ? g_arm9->ITCM + (r.entry & (ITCMPhysicalSize - 1))
                                                       : C.main_ram + (r.entry & C.main_ram_mask);
            if (memcmp(mem, r.body, r.body_len) != 0) continue;  // a different image is resident
        }
        r.fn_multi(&C, target);
        return;
    }
    // Code with no recompiled version (e.g. generated or copied into the heap at runtime):
    // run it in melonDS's ARM9 interpreter until it returns to a recompiled frame.
    if ((target >> 24) == 0x02 || target < C.itcm_size) {
        static int logged = 0;
        if ((target < 0x0216fd00u || target >= 0x02172000u) && logged == 0) {
            if (FILE* f = fopen("ram_miss.bin", "wb")) { fwrite(g_nds->MainRAM, 1, 0x400000, f); fclose(f); }
        }
        if ((target < 0x0216fd00u || target >= 0x02172000u) && logged++ < 40) {
            int ov = residentOverlay(target);
            logf("[rt] no recompiled code at %08x (lr=%08x, table candidates: %zu, resident overlay %d): interpreting\n",
                 target, C.r[14], g_fnmap.count(target) ? g_fnmap[target].e.size() : (size_t)0, ov);
        }
        interpretAt(origTarget);
        return;
    }
    fatal("no recompiled function at %08x (lr=%08x). Add it as a seed and regenerate.", target, C.r[14]);
}

// Root trampoline for a guest thread: functions that return to an address no frame
// recognises continue executing there (e.g. thread entry returning into OS_ExitThread).
// Call `target` expecting it to return to `expected`. Returns to computed addresses are
// executed as continuations, like the resolver blocks in generated code.
void callExpect(uint32_t target, uint32_t expected) {
    C.ss[C.ssp++] = expected;
    g_depth++;
    callAt(target);
    while (C.ret != expected) {
        if (rt_in_stack(&C, C.ret)) fatal("unwinding through runtime frame (ret %08x, expected %08x)", C.ret, expected);
        callAt(C.ret);
    }
    g_depth--;
    C.ssp--;
}

void runAt(uint32_t pc) {
    // r14 keeps the value the thread was created with (Nitro: OS_ExitThread); returning there
    // simply continues as a call, and that function never returns.
    C.ss = g_cur->ss.data();
    C.ssp = 0;
    // Threads restored from a save state have no host frames: continue at their return address and
    // let the root loop below resume each caller in turn (return sites, see resumeAt).
    if (pc == kSaveCtxResume) {      // parked in OS_SaveContext: it "returns 1" to its caller
        C.r[0] = 1;
        pc = C.r[14];
    } else if (pc == kColdReturn) {  // halted in a leaf call: return from it
        pc = C.r[14];
    } else if (pc == kColdCall) {    // saved at a function's entry: call it again
        pc = g_coldCall;
    }
    callExpect(pc, kRootRet);
    fatal("guest thread root function at %08x returned", pc);
}

// Transfer control to guest PC `pc` after a context switch.
void transferTo(uint32_t pc) {
    if (pc >= kTokenBase && (pc & 0xF) == 0) {
        auto it = g_byToken.find(pc);
        if (it != g_byToken.end()) {
            g_tokenParked.erase(it->second);
            g_parkHow.erase(it->second);
            switchTo(it->second);
            return;
        }
        // switched out by an IRQ before a save state was loaded: restart it on a new fiber
        auto ct = g_coldTokens.find(pc);
        if (ct == g_coldTokens.end()) fatal("resuming unknown interrupted thread %08x", pc);
        uint32_t how = ct->second;
        g_coldTokens.erase(ct);
        switchTo(newFiber(how));
        return;
    }
    if (pc == kSaveCtxResume) {
        auto it = g_parkedBySp.find(C.r[13]);
        if (it != g_parkedBySp.end()) { switchTo(it->second); return; }
        // a thread parked before a save state was loaded: start a fiber that resumes it
    }
    switchTo(newFiber(pc));
}

// ------------------------------------------------------------------ IRQ (BIOS vector in C)
void doIrq() {
    uint32_t cpsr = rt_cpsr_read(&C);
    Fiber* me = g_cur;
    // how this thread can be restarted if the handler switches it out (save states)
    uint32_t how = g_yieldPark;
    g_yieldPark = 0;
    const uint32_t mode0 = C.cpsr & 0x1F;
    if (how && (g_depth != 1 || (mode0 != 0x1F && mode0 != 0x10) || !resumeOwner(C.r[14] & ~1u))) how = 0;
    uint32_t old = C.cpsr;
    switchMode(old & 0x1F, 0x12);
    C.cpsr = (cpsr & ~0xFFu) | 0x92;  // IRQ mode, IRQs disabled, ARM state
    C.TB = 0;
    C.spsr = cpsr;
    C.r[14] = me->token + 4;
    // BIOS: stmfd sp!, {r0-r3, r12, lr}
    uint32_t sp = C.r[13] - 24;
    mem_write32(&C, sp + 0, C.r[0]);
    mem_write32(&C, sp + 4, C.r[1]);
    mem_write32(&C, sp + 8, C.r[2]);
    mem_write32(&C, sp + 12, C.r[3]);
    mem_write32(&C, sp + 16, C.r[12]);
    mem_write32(&C, sp + 20, C.r[14]);
    C.r[13] = sp;
    uint32_t dtcmEnd = C.dtcm_base + 0x4000;
    uint32_t handler = mem_read32(&C, dtcmEnd - 4);
    g_stats.irqs++;
    g_lastIrqHandler = handler;
    C.r[0] = dtcmEnd;
    C.r[14] = kBiosIrqRet;
    callExpect(handler, kBiosIrqRet);
    // BIOS: ldmfd sp!, {r0-r3, r12, lr}; subs pc, lr, #4
    sp = C.r[13];
    C.r[0] = mem_read32(&C, sp + 0);
    C.r[1] = mem_read32(&C, sp + 4);
    C.r[2] = mem_read32(&C, sp + 8);
    C.r[3] = mem_read32(&C, sp + 12);
    C.r[12] = mem_read32(&C, sp + 16);
    C.r[14] = mem_read32(&C, sp + 20);
    C.r[13] = sp + 24;
    uint32_t pc = C.r[14] - 4;
    loadPsr(C.spsr);
    if (pc != me->token) {  // the OS switched threads inside the handler
        g_tokenParked.insert(me);
        if (how) g_parkHow[me] = how;
        transferTo(pc);
    }
}

void maybeIrq() {
    if (g_arm9->IRQ && !(C.cpsr & 0x80)) doIrq();
}

// ------------------------------------------------------------------ hook called by melonDS
void externalExecute(ARMv5* cpu) {
    if (cpu->Halted == 2) cpu->Halted = 0;
    if (g_halted) {
        if (!g_nds->HaltInterrupted(0)) {
            g_nds->ARM9Timestamp = g_nds->ARM9Target;
            return;
        }
        g_halted = false;
    }
    C.cycles = (int64_t)g_nds->ARM9Timestamp;
    C.target = (int64_t)g_nds->ARM9Target;
    SwitchToFiber(g_cur->handle);
    g_nds->ARM9Timestamp = (u64)C.cycles;
}

}  // namespace

namespace recomp { bool saveAtCallPending(); void takeSaveAtCall(uint32_t fn); }

// ================================================================== C ABI used by generated code
extern "C" {

void rt_yield(Cpu* c) {
    // A save state is pending: keep target 0 so that every function entry checks for a moment to
    // save (rt_yield_entry), and take IRQs only at function entries, where a thread switched out by
    // one can be restarted from a save state.
    const bool pending = recomp::saveAtCallPending();
    if (pending && !g_halted && c->cycles < (int64_t)g_nds->ARM9Target) {
        c->target = 0;
        if (g_yieldPark) maybeIrq();
        return;
    }
    g_stats.yields++;
    g_nds->ARM9Timestamp = (u64)c->cycles;
    SwitchToFiber(g_hostFiber);
    c->cycles = (int64_t)g_nds->ARM9Timestamp;
    c->target = (int64_t)g_nds->ARM9Target;
    if (recomp::saveAtCallPending()) {
        c->target = 0;
        if (!g_yieldPark) return;
    }
    maybeIrq();
}

static bool trySaveAtEntry(Cpu* c, uint32_t fn);

void rt_yield_entry(Cpu* c, uint32_t fn) {
    if (recomp::saveAtCallPending() && trySaveAtEntry(c, fn | c->TB)) return;
    uint32_t prev = g_yieldPark;
    g_yieldPark = fn | c->TB;
    rt_yield(c);
    g_yieldPark = prev;
}

static inline void afterIo(Cpu* c) {
    c->target = (int64_t)g_nds->ARM9Target;
    if (g_arm9->Halted == 2 || g_arm9->IRQ) c->target = 0;  // DMA stall or pending IRQ: yield at next check
}

uint8_t rt_read8(Cpu* c, uint32_t a) {
    if (a < c->itcm_size) return g_arm9->ITCM[a & (ITCMPhysicalSize - 1)];
    if ((a & c->dtcm_mask) == c->dtcm_base) return g_arm9->DTCM[a & (DTCMPhysicalSize - 1)];
    return g_nds->ARM9Read8(a);
}
uint16_t rt_read16(Cpu* c, uint32_t a) {
    a &= ~1u;
    if (a < c->itcm_size) return *(u16*)&g_arm9->ITCM[a & (ITCMPhysicalSize - 1)];
    if ((a & c->dtcm_mask) == c->dtcm_base) return *(u16*)&g_arm9->DTCM[a & (DTCMPhysicalSize - 1)];
    return g_nds->ARM9Read16(a);
}
uint32_t rt_read32(Cpu* c, uint32_t a) {
    a &= ~3u;
    if (a < c->itcm_size) return *(u32*)&g_arm9->ITCM[a & (ITCMPhysicalSize - 1)];
    if ((a & c->dtcm_mask) == c->dtcm_base) return *(u32*)&g_arm9->DTCM[a & (DTCMPhysicalSize - 1)];
    return g_nds->ARM9Read32(a);
}
void rt_write8(Cpu* c, uint32_t a, uint8_t v) {
    if (a < c->itcm_size) { g_arm9->ITCM[a & (ITCMPhysicalSize - 1)] = v; return; }
    if ((a & c->dtcm_mask) == c->dtcm_base) { g_arm9->DTCM[a & (DTCMPhysicalSize - 1)] = v; return; }
    g_nds->ARM9Write8(a, v);
    afterIo(c);
}
void rt_write16(Cpu* c, uint32_t a, uint16_t v) {
    a &= ~1u;
    if (a < c->itcm_size) { *(u16*)&g_arm9->ITCM[a & (ITCMPhysicalSize - 1)] = v; return; }
    if ((a & c->dtcm_mask) == c->dtcm_base) { *(u16*)&g_arm9->DTCM[a & (DTCMPhysicalSize - 1)] = v; return; }
    g_nds->ARM9Write16(a, v);
    afterIo(c);
}
void rt_write32(Cpu* c, uint32_t a, uint32_t v) {
    a &= ~3u;
    if (a < c->itcm_size) { *(u32*)&g_arm9->ITCM[a & (ITCMPhysicalSize - 1)] = v; return; }
    if ((a & c->dtcm_mask) == c->dtcm_base) { *(u32*)&g_arm9->DTCM[a & (DTCMPhysicalSize - 1)] = v; return; }
    g_nds->ARM9Write32(a, v);
    afterIo(c);
}

int rt_in_stack(Cpu* c, uint32_t addr) {
    for (uint32_t i = c->ssp; i-- > 0;)
        if (c->ss[i] == addr) return 1;
    return 0;
}

void rt_call(Cpu* c, uint32_t target) {
    // A jump to an address some outer frame is waiting for is really a return (e.g. `ldr pc,[sp],#4`).
    if (rt_in_stack(c, target & ~1u)) { c->ret = target & ~1u; return; }
    callAt(target);
}

// User-bank r13/r14 access for LDM/STM with the S bit (`^`)
uint32_t rt_get_user(Cpu* c, uint32_t n) {
    if (n < 13 || bankOf(c->cpsr) == 0) return c->r[n];
    return n == 13 ? g_bankR13[0] : g_bankR14[0];
}

void rt_set_user(Cpu* c, uint32_t n, uint32_t v) {
    if (n < 13 || bankOf(c->cpsr) == 0) { c->r[n] = v; return; }
    if (n == 13) g_bankR13[0] = v; else g_bankR14[0] = v;
}

void rt_bad_return(Cpu*, uint32_t expected, uint32_t got, uint32_t at) {
    fatal("unexpected return to %08x (expected %08x) after call at %08x", got, expected, at);
}

void rt_missing(Cpu*, uint32_t at, const char* why) { fatal("%s at %08x", why, at); }

void rt_userop(Cpu*, uint32_t op, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t at) {
    static int count = 0;
    if (count++ < 32) logf("[rt] ignored user op %u at %08x\n", op, at);
}

uint32_t rt_cpsr_read(Cpu* c) {
    return (c->cpsr & 0x07FFFFDFu) | ((uint32_t)c->NG << 31) | ((uint32_t)c->ZR << 30) | ((uint32_t)c->CY << 29) |
           ((uint32_t)c->OV << 28) | ((uint32_t)c->Q << 27) | ((uint32_t)c->TB << 5);
}

void rt_cpsr_written(Cpu* c, uint32_t old) {
    switchMode(old & 0x1F, c->cpsr & 0x1F);
    if ((old & 0x80) && !(c->cpsr & 0x80) && g_arm9->IRQ) c->target = 0;
}

void rt_spsr_restore(Cpu*) { loadPsr(C.spsr); }

void rt_msr_cpsr(Cpu* c, uint32_t val, uint32_t mask) {
    uint32_t old = rt_cpsr_read(c);
    if ((old & 0x1F) == 0x10) mask &= 0xFF000000u;  // user mode may only change flags
    uint32_t v = (old & ~mask) | (val & mask);
    switchMode(old & 0x1F, v & 0x1F);
    c->cpsr = v;
    setFlagsFrom(v);
    c->TB = (old >> 5) & 1;  // MSR cannot change the T bit
    if ((old & 0x80) && !(v & 0x80) && g_arm9->IRQ) c->target = 0;
}

uint32_t rt_cp15_read(Cpu*, uint32_t id) { return g_arm9->CP15Read(id); }

// Called at the entry of OS_WaitVBlankIntr (see testhooks.cpp): take a pending save state here
// if every other thread is parked and this one can be resumed by calling the function again.
void rt_safe_call_point(Cpu* c, uint32_t fn) {
    if (recomp::saveAtCallPending()) trySaveAtEntry(c, fn | 1);
}

// Every other thread can be restarted from guest memory after a load.
static bool othersRestartable() {
    if (g_parkHow.size() != g_tokenParked.size()) return false;
    for (auto& [sp, f] : g_parkedBySp)
        if (f != g_cur && !f->savedAtRoot) return false;
    return true;
}

// At the entry of `fn` (| Thumb bit), before it has run anything: save here if calling it again
// after a load continues exactly like this thread does now.
static bool trySaveAtEntry(Cpu* c, uint32_t fn) {
    const uint32_t mode = c->cpsr & 0x1F;
    const bool ok = g_depth == 1 && !g_halted && (mode == 0x1F || mode == 0x10) && othersRestartable() &&
                    lookup(fn & ~1u) && resumeOwner(c->r[14] & ~1u);
    if (!ok) {
        static int n = 0;
        if (getenv("MSDS_STATE_LOG") && n++ % 5000 == 0)
            logf("[state] not at %08x: depth %u, mode %02x, IRQ-parked unrestartable %zu, lr %08x resumable %d\n", fn,
                 g_depth, mode, g_tokenParked.size() - g_parkHow.size(), c->r[14], resumeOwner(c->r[14] & ~1u) != nullptr);
        return false;
    }
    g_nds->ARM9Timestamp = (u64)c->cycles;
    recomp::takeSaveAtCall(fn);
    c->target = (int64_t)g_nds->ARM9Target;
    return true;
}

void rt_cp15_write(Cpu* c, uint32_t id, uint32_t val, uint32_t) {
    if (id == 0x704 || id == 0x782) {  // wait for interrupt
        g_halted = true;
        g_stats.halts++;
        g_haltWfi = true;
        while (g_halted) { g_yieldPark = kColdReturn; rt_yield(c); }
        g_yieldPark = 0;
        g_haltWfi = false;
        return;
    }
    g_arm9->CP15Write(id, val);
    refreshTcm();
}

void rt_swi(Cpu* c, uint32_t num, uint32_t at) {
    if (num > 0xFF) num = (num >> 16) & 0xFF;
    g_stats.swis++;
    switch (num) {
    case 0x03:  // WaitByLoop (FreeBIOS: subs r0, r0, #1; bgt)
        c->cycles += (int64_t)(int32_t)c->r[0] > 0 ? (int64_t)(int32_t)c->r[0] * 4 : 4;
        c->r[0] = (int32_t)c->r[0] > 0 ? 0 : c->r[0] - 1;
        break;
    case 0x06:  // Halt
        g_halted = true;
        while (g_halted) rt_yield(c);
        break;
    case 0x09: {  // Div (FreeBIOS register results: r0 quotient, r1 |remainder|, r2 = r3 = |quotient|)
        int32_t n = (int32_t)c->r[0], d = (int32_t)c->r[1];
        if (d == 0) { c->r[0] = n < 0 ? 1 : (uint32_t)-1; c->r[1] = (uint32_t)n; c->r[3] = 1; break; }
        uint32_t un = n < 0 ? 0u - (uint32_t)n : (uint32_t)n, ud = d < 0 ? 0u - (uint32_t)d : (uint32_t)d;
        uint32_t q = un / ud, r = un % ud;
        c->r[0] = ((n ^ d) < 0) ? 0u - q : q;
        c->r[1] = r; c->r[2] = q; c->r[3] = q;
        break;
    }
    case 0x0B: case 0x0C: {  // CpuSet / CpuFastSet (FreeBIOS: pointers advance, r3 = last value)
        uint32_t ctl = c->r[2], n = ctl & 0x1FFFFF;
        bool fill = ctl & (1 << 24), word = num == 0x0C || (ctl & (1 << 26));
        uint32_t sz = word ? 4 : 2;
        uint32_t src = c->r[0] & ~(sz - 1), dst = c->r[1] & ~(sz - 1), v = 0;
        if (fill) v = word ? mem_read32(c, src) : mem_read16(c, src);
        for (uint32_t i = 0; i < n; i++) {
            if (!fill) { v = word ? mem_read32(c, src) : mem_read16(c, src); src += sz; }
            if (word) mem_write32(c, dst, v); else mem_write16(c, dst, (uint16_t)v);
            dst += sz;
        }
        c->r[0] = src; c->r[1] = dst; c->r[3] = v; c->r[12] = 0;
        c->cycles += n * 2;
        break;
    }
    case 0x0D: {  // Sqrt
        uint32_t v = c->r[0], r = 0, bit = 1u << 30;
        while (bit > v) bit >>= 2;
        while (bit) { if (v >= r + bit) { v -= r + bit; r = (r >> 1) + bit; } else r >>= 1; bit >>= 2; }
        c->r[0] = r;
        break;
    }
    case 0x0F: c->r[0] = 0; break;  // IsDebugger
    default:
        fatal("unimplemented BIOS call SWI %02x at %08x", num, at);
    }
}

// ---------------------------------------------------------------- Nitro OS thread context overrides
void f_ram_020c3af8(Cpu*);  // original OS_SaveContext (recompiled)

void ovr_OS_SaveContext(Cpu* c) {
    uint32_t ctx = c->r[0];
    f_ram_020c3af8(c);
    uint32_t savedSp = mem_read32(c, ctx + 4 + 13 * 4);
    g_parkedBySp[savedSp] = g_cur;
    g_cur->savedAtRoot = g_depth == 1;
}

void ovr_OS_LoadContext(Cpu* c) {
    TRACE_ENTRY(0x020c3b44u);
    uint32_t ctx = c->r[0];
    // CP_RestoreContext(ctx + 0x48): divider/sqrt unit state (called like the original: blx r1)
    uint32_t cpRestore = mem_read32(c, 0x020c3b84);
    c->r[0] = ctx + 0x48;
    c->r[14] = 0x020c3b54u;
    callExpect(cpRestore, 0x020c3b54u);
    // mode switch to SVC, svc sp from the context, then restore user-bank registers and CPSR
    uint32_t psr = mem_read32(c, ctx);
    uint32_t old = C.cpsr;
    switchMode(old & 0x1F, 0x13);
    C.cpsr = (C.cpsr & ~0x1Fu) | 0x13;
    C.r[13] = mem_read32(c, ctx + 0x44);
    for (int i = 0; i < 13; i++) C.r[i] = mem_read32(c, ctx + 4 + i * 4);
    g_bankR13[0] = mem_read32(c, ctx + 4 + 13 * 4);
    g_bankR14[0] = mem_read32(c, ctx + 4 + 14 * 4);
    uint32_t pc = mem_read32(c, ctx + 0x40) - 4;
    if (bankOf(psr) == 0) {  // returning to a usr/sys thread: user bank becomes live
        switchMode(0x13, psr & 0x1F);
        C.cpsr = psr;
        setFlagsFrom(psr);
    } else {
        loadPsr(psr);
    }
    Fiber* me = g_cur;
    transferTo(pc);
    // We are running again: someone restored our context (saved by OS_SaveContext).
    // Behave like OS_SaveContext returning 1: unwind to its call site.
    (void)me;
    c->ret = c->r[14] & ~1u;
}

}  // extern "C"

// ================================================================== differential tracing
// Record format shared by the recompiled code and the interpreter (see tools/tracediff.py).
struct TraceRec { uint32_t addr, r0, r1, r2, r3, sp, lr; uint32_t mode; };
static FILE* g_traceFile = nullptr;
static uint64_t g_traceCount = 0, g_traceLimit = 20000000;
static std::vector<uint8_t> g_entryBitmap;  // 2-byte granularity over 0x01ff8000..0x02200000

static inline bool isEntry(uint32_t a) {
    uint32_t i = (a - 0x01FF8000u) >> 1;
    return i < g_entryBitmap.size() * 8 && (g_entryBitmap[i >> 3] >> (i & 7)) & 1;
}

static void traceWrite(uint32_t addr, const uint32_t* r, uint32_t mode) {
    if (!g_traceFile || g_traceCount >= g_traceLimit) return;
    TraceRec t{addr, r[0], r[1], r[2], r[3], r[13], r[14], mode};
    fwrite(&t, sizeof t, 1, g_traceFile);
    if (++g_traceCount == g_traceLimit) fflush(g_traceFile);
}

static uint32_t g_lastFn = 0;
extern "C" {
int g_rt_trace = 0;
uint32_t g_watch_lo = 0, g_watch_len = 0;
// debug: MSDS_DUMP_AT=<fn addr>:<lr>:<n> dumps main RAM when that call happens for the n-th time
static void maybeDump(uint32_t addr, uint32_t lr, const char* tag) {
    static uint32_t dAddr = 0, dLr = 0, dN = 0;
    static bool parsed = false;
    if (!parsed) {
        parsed = true;
        if (const char* e = getenv("MSDS_DUMP_AT")) sscanf(e, "%x:%x:%u", &dAddr, &dLr, &dN);
    }
    if (!dAddr || addr != dAddr || (lr & ~1u) != (dLr & ~1u)) return;
    if (dN-- > 1) return;
    char fn[64];
    snprintf(fn, sizeof fn, "ram_%s.bin", tag);
    if (FILE* f = fopen(fn, "wb")) { fwrite(g_nds->MainRAM, 1, 0x400000, f); fclose(f); }
    logf("[trace] main RAM dumped to %s at %08x\n", fn, addr);
    dAddr = 0;
}

// debug: MSDS_INTERP_FN=lo-hi[,lo-hi...] runs recompiled functions in those ranges in the
// interpreter instead (bisecting recompiler bugs)
static std::vector<std::pair<uint32_t, uint32_t>> g_interpRanges;
static bool g_interpRangesParsed = false;

static bool forceInterp(uint32_t addr) {
    if (!g_interpRangesParsed) {
        g_interpRangesParsed = true;
        if (const char* e = getenv("MSDS_INTERP_FN")) {
            std::string sv = e;
            size_t pos = 0;
            while (pos < sv.size()) {
                size_t comma = sv.find(',', pos);
                std::string part = sv.substr(pos, comma == std::string::npos ? std::string::npos : comma - pos);
                uint32_t lo = 0, hi = 0;
                if (sscanf(part.c_str(), "%x-%x", &lo, &hi) == 2) g_interpRanges.push_back({lo, hi});
                if (comma == std::string::npos) break;
                pos = comma + 1;
            }
        }
    }
    for (auto& r : g_interpRanges)
        if (addr >= r.first && addr <= r.second) return true;
    return false;
}

static bool g_inForcedInterp = false;
// overlay id of the function image resident at addr (-1 static, -3 unknown)
static int residentOverlay(uint32_t addr) {
    auto it = g_fnmap.find(addr);
    if (it == g_fnmap.end()) return -3;
    const uint8_t* mem = addr < C.itcm_size ? g_arm9->ITCM + (addr & (ITCMPhysicalSize - 1))
                                            : C.main_ram + (addr & C.main_ram_mask);
    for (const GuestFnEntry* e : it->second.e) {
        if (e->overlay < 0) return -1;
        if (e->body && memcmp(mem, e->body, e->body_len) == 0) return e->overlay;
    }
    return -3;
}

int rt_trace(Cpu* c, uint32_t addr) {
    g_lastFn = addr;
    maybeDump(addr, c->r[14], "recomp");
    traceWrite(addr, c->r, c->cpsr & 0x1F);
    if (!g_interpRanges.empty() || !g_interpRangesParsed) {
        if (!g_inForcedInterp && forceInterp(addr) && residentOverlay(addr) == g_interpOverlay) {
            g_inForcedInterp = true;
            interpretAt(addr | (c->TB ? 1 : 0));
            g_inForcedInterp = false;
            return 1;
        }
    }
    return 0;
}
void rt_watch(Cpu* c, uint32_t addr, uint32_t size, uint32_t val) {
    static int n = 0;
    if (n++ > 200) return;
    logf("[watch] write%u %08x <- %08x in fn %08x lr=%08x sp=%08x r4-r12=%08x %08x %08x %08x %08x %08x %08x %08x %08x  stack:",
         size * 8, addr, val, g_lastFn, c->r[14], c->r[13], c->r[4], c->r[5], c->r[6], c->r[7], c->r[8], c->r[9],
         c->r[10], c->r[11], c->r[12]);
    for (uint32_t i = c->ssp > 6 ? c->ssp - 6 : 0; i < c->ssp; i++) logf(" %08x", c->ss[i]);
    logf("\n");
}
}

// debug: MSDS_ITRACE=file[:count] logs every instruction executed in the movie decoder image with
// r0-r14 and NZCV, from the interpreter (--interp) and from native code built with -DMSDS_IMG_STEP=ON.
// tools/itracediff.py finds the first instruction whose results differ.
struct ImgRec { uint32_t pc, r[15], nzcv; };
static FILE* g_itrace = nullptr;
static uint64_t g_itraceLeft = 0;
static const GuestRange* g_decoderRange = nullptr;

static void itraceOpen() {
    const char* e = getenv("MSDS_ITRACE");
    if (!e || g_itrace) return;
    std::string path = e;
    g_itraceLeft = 4000000;
    size_t colon = path.rfind(':');
    if (colon != std::string::npos && colon > 1) {
        g_itraceLeft = strtoull(path.c_str() + colon + 1, nullptr, 10);
        path.resize(colon);
    }
    g_itrace = fopen(path.c_str(), "wb");
    for (unsigned i = 0; i < g_guest_range_count; i++)
        if (g_guest_ranges[i].overlay == 200) g_decoderRange = &g_guest_ranges[i];
}

static void itraceWrite(uint32_t pc, const uint32_t* r, uint32_t nzcv) {
    if (!g_itrace || !g_itraceLeft) return;
    ImgRec rec{pc, {}, nzcv};
    memcpy(rec.r, r, sizeof rec.r);
    fwrite(&rec, sizeof rec, 1, g_itrace);
    if (--g_itraceLeft == 0) { fclose(g_itrace); g_itrace = nullptr; logf("[trace] instruction trace complete\n"); }
}

extern "C" void rt_img_step(Cpu* c, uint32_t addr) {
    itraceWrite(addr, c->r, (uint32_t)c->NG << 3 | (uint32_t)c->ZR << 2 | (uint32_t)c->CY << 1 | c->OV);
}

static void interpHook(ARMv5* cpu, u32 addr) {
    if (!g_nds) g_nds = &cpu->NDS;
    if (g_itrace && g_decoderRange && addr >= g_decoderRange->start && addr < g_decoderRange->end &&
        memcmp(cpu->ITCM + (g_decoderRange->entry & (ITCMPhysicalSize - 1)), g_decoderRange->body, g_decoderRange->body_len) == 0)
        itraceWrite(addr, cpu->R, cpu->CPSR >> 28);
    maybeDump(addr, cpu->R[14], "interp");
    // debug: MSDS_ITCM_AT=<addr> dumps ITCM the first time the interpreter reaches that address
    static uint32_t dumpAt = getenv("MSDS_ITCM_AT") ? (uint32_t)strtoul(getenv("MSDS_ITCM_AT"), nullptr, 16) : 0;
    if (dumpAt && addr == dumpAt) {
        if (FILE* f = fopen("itcm_at.bin", "wb")) { fwrite(cpu->ITCM, 1, ITCMPhysicalSize, f); fclose(f); }
        logf("[trace] ITCM dumped at %08x (lr=%08x)\n", addr, cpu->R[14]);
        dumpAt = 0;
    }
    if (!isEntry(addr)) return;
    // overlays share addresses: only count it if this address is an entry of the resident overlay
    auto it = g_fnmap.find(addr);
    if (it == g_fnmap.end()) return;
    bool ok = false;
    u32 w0 = 0, w1 = 0;
    bool haveWords = false;
    for (const GuestFnEntry* e : it->second.e) {
        if (e - g_guest_fns >= (ptrdiff_t)g_guest_primary_count) continue;
        if (e->overlay < 0) { ok = true; break; }
        if (e->body) {
            const uint8_t* ram = addr < cpu->ITCMSize ? cpu->ITCM + (addr & (ITCMPhysicalSize - 1))
                                                      : cpu->NDS.MainRAM + (addr & cpu->NDS.MainRAMMask);
            if (memcmp(ram, e->body, e->body_len) == 0) { ok = true; break; }
            continue;
        }
        if (!haveWords) { w0 = cpu->NDS.ARM9Read32(addr); w1 = cpu->NDS.ARM9Read32(addr + 4); haveWords = true; }
        if (e->sig[0] == w0 && e->sig[1] == w1) { ok = true; break; }
    }
    if (ok) traceWrite(addr, cpu->R, cpu->CPSR & 0x1F);
}

// ================================================================== public API
namespace recomp {

void traceStart(const char* path, bool interpreter) {
    itraceOpen();
    g_traceFile = path ? fopen(path, "wb") : nullptr;
    if (!g_traceFile && !g_itrace) return;
    g_entryBitmap.assign((0x02200000u - 0x01FF8000u) / 2 / 8 + 1, 0);
    for (unsigned i = 0; i < g_guest_primary_count; i++) {
        uint32_t a = g_guest_fns[i].addr;
        if (a >= 0x01FF8000u && a < 0x02200000u) {
            uint32_t k = (a - 0x01FF8000u) >> 1;
            g_entryBitmap[k >> 3] |= 1 << (k & 7);
        }
    }
    if (g_fnmap.empty())
        for (unsigned i = 0; i < g_guest_fn_count; i++) g_fnmap[g_guest_fns[i].addr].e.push_back(&g_guest_fns[i]);
    if (interpreter) ARMv5::InstrHook = interpHook;
    else if (g_traceFile) g_rt_trace = 1;
}

void traceStop() {
    if (g_traceFile) { fclose(g_traceFile); g_traceFile = nullptr; }
    ARMv5::InstrHook = nullptr;
    g_rt_trace = 0;
}

bool available() { return g_guest_fn_count > 0; }

void attach(NDS* nds, uint32_t entry) {
    g_nds = nds;
    if (const char* w = getenv("MSDS_WATCH")) {
        g_watch_lo = (uint32_t)strtoul(w, nullptr, 16);
        const char* colon = strchr(w, ':');
        g_watch_len = colon ? (uint32_t)strtoul(colon + 1, nullptr, 16) : 4;
        if (!g_rt_trace) g_rt_trace = 1;  // keep track of the current function (no file needed)
    }
    if (getenv("MSDS_INTERP_FN")) g_rt_trace = 1;
    g_arm9 = &nds->ARM9;
    if (!g_log) g_log = fopen("recomp.log", "w");
    g_fnmap.clear();
    for (unsigned i = 0; i < g_guest_fn_count; i++) g_fnmap[g_guest_fns[i].addr].e.push_back(&g_guest_fns[i]);
    g_resumeMap.clear();
    for (unsigned i = 0; i < g_resume_count; i++) g_resumeMap[g_resume_points[i].addr].push_back(&g_guest_fns[g_resume_points[i].fn]);
    memcpy(C.r, g_arm9->R, sizeof C.r);
    C.cpsr = g_arm9->CPSR;
    setFlagsFrom(C.cpsr);
    // melonDS banks: R_SVC/R_IRQ/... hold {r13, r14, spsr}
    g_bankR13[3] = g_arm9->R_SVC[0]; g_bankR14[3] = g_arm9->R_SVC[1]; g_bankSpsr[3] = g_arm9->R_SVC[2];
    g_bankR13[2] = g_arm9->R_IRQ[0]; g_bankR14[2] = g_arm9->R_IRQ[1]; g_bankSpsr[2] = g_arm9->R_IRQ[2];
    g_bankR13[4] = g_arm9->R_ABT[0]; g_bankR14[4] = g_arm9->R_ABT[1]; g_bankSpsr[4] = g_arm9->R_ABT[2];
    g_bankR13[5] = g_arm9->R_UND[0]; g_bankR14[5] = g_arm9->R_UND[1]; g_bankSpsr[5] = g_arm9->R_UND[2];
    C.main_ram = nds->MainRAM;
    C.main_ram_mask = nds->MainRAMMask;
    refreshTcm();
    if (!g_hostFiber) g_hostFiber = ConvertThreadToFiber(nullptr);
    for (Fiber* f : g_fibers) { DeleteFiber(f->handle); delete f; }
    g_fibers.clear();
    g_parkedBySp.clear();
    g_tokenParked.clear();
    g_byToken.clear();
    g_parkHow.clear();
    g_coldTokens.clear();
    g_nextFiberId = 0;
    g_yieldPark = 0;
    g_depth = 0;
    g_halted = false;
    g_haltWfi = false;
    g_cur = newFiber(entry);
    C.ss = g_cur->ss.data();
    C.ssp = 0;
    ARMv5::ExternalExecute = externalExecute;
    g_active = true;
    logf("[rt] attached: %u recompiled functions, entry %08x\n", g_guest_fn_count, entry);
}

void detach() {
    ARMv5::ExternalExecute = nullptr;
    g_active = false;
}

bool active() { return g_active; }

namespace {
std::function<bool(const std::vector<uint8_t>&)> g_saveWriter;
int g_saveResult = -2;
}
void requestSaveAtCall(std::function<bool(const std::vector<uint8_t>&)> write) { g_saveWriter = std::move(write); g_saveResult = 0; }
int saveAtCallResult() { return g_saveResult; }
bool saveAtCallPending() { return g_saveWriter && g_saveResult == 0; }
void takeSaveAtCall(uint32_t fn) {
    std::vector<uint8_t> rt = saveState();
    uint32_t kind = 1, target = fn;      // entry | Thumb bit
    memcpy(rt.data() + 8, &kind, 4);     // StateBlock.kind / .target follow magic and version
    memcpy(rt.data() + 12, &target, 4);
    g_saveResult = g_saveWriter(rt) ? 1 : -1;
    g_saveWriter = nullptr;
}
void cancelSaveAtCall() { g_saveWriter = nullptr; g_saveResult = -2; }
std::vector<uint8_t> saveState();

// ---------------------------------------------------------------- save states
namespace {
struct StateBlock {
    char magic[4];
    uint32_t version;
    uint32_t kind;    // 0: halted in a leaf call (continue at lr); 1: at the entry of `target`
    uint32_t target;
    uint32_t r[16];
    uint8_t NG, ZR, CY, OV, Q, TB, halted, pad;
    uint32_t cpsr, spsr;
    uint32_t bankR13[6], bankR14[6], bankSpsr[6];
};
}

bool canSaveState(std::string* why) {
    auto no = [&](const char* w) { if (why) *why = w; return false; };
    if (!g_active || !g_cur) return no("native code not running");
    if (!g_halted || !g_haltWfi) return no("the game is busy (not waiting for the next frame)");
    if (g_depth != 1 || !othersRestartable()) return no("a thread was interrupted mid-work");
    const uint32_t mode = C.cpsr & 0x1F;
    if (mode != 0x1F && mode != 0x10) return no("an interrupt is being handled");
    if (!resumeOwner(C.r[14] & ~1u)) return no("the waiting thread cannot be resumed");
    return true;
}

std::vector<uint8_t> saveState() {
    StateBlock b{};
    memcpy(b.magic, "MSRT", 4);
    b.version = 3;
    memcpy(b.r, C.r, sizeof b.r);
    b.NG = C.NG; b.ZR = C.ZR; b.CY = C.CY; b.OV = C.OV; b.Q = C.Q; b.TB = C.TB;
    b.halted = g_halted;
    b.cpsr = C.cpsr; b.spsr = C.spsr;
    memcpy(b.bankR13, g_bankR13, sizeof b.bankR13);
    memcpy(b.bankR14, g_bankR14, sizeof b.bankR14);
    memcpy(b.bankSpsr, g_bankSpsr, sizeof b.bankSpsr);
    // then: count, {token, how} of each thread switched out by an IRQ (see g_parkHow)
    std::vector<uint32_t> parked;
    for (auto& [f, how] : g_parkHow) { parked.push_back(f->token); parked.push_back(how); }
    for (auto& [tok, how] : g_coldTokens) { parked.push_back(tok); parked.push_back(how); }
    uint32_t n = (uint32_t)parked.size() / 2;
    logf("[rt] state saved: %s, lr %08x, %u interrupted thread(s), cycles %lld\n", g_halted ? "halted" : "at a call",
         C.r[14], n, (long long)C.cycles);
    std::vector<uint8_t> out(sizeof b + 4 + parked.size() * 4);
    memcpy(out.data(), &b, sizeof b);
    memcpy(out.data() + sizeof b, &n, 4);
    if (n) memcpy(out.data() + sizeof b + 4, parked.data(), parked.size() * 4);
    return out;
}

bool loadState(const uint8_t* data, size_t len) {
    StateBlock b;
    if (len < sizeof b + 4) return false;
    memcpy(&b, data, sizeof b);
    if (memcmp(b.magic, "MSRT", 4) != 0 || b.version != 3) return false;
    uint32_t n;
    memcpy(&n, data + sizeof b, 4);
    if (len != sizeof b + 4 + (size_t)n * 8) return false;
    // Drop every fiber: the threads are rebuilt from guest memory as the game switches to them
    // (OS_LoadContext of a parked thread starts a fiber that resumes it, see transferTo/runAt).
    for (Fiber* f : g_fibers) { DeleteFiber(f->handle); delete f; }
    g_fibers.clear();
    g_parkedBySp.clear();
    g_tokenParked.clear();
    g_byToken.clear();
    g_parkHow.clear();
    g_coldTokens.clear();
    g_yieldPark = 0;
    g_depth = 0;
    // threads switched out by an IRQ restart from their entry; new fibers get fresh tokens
    uint32_t maxId = 0;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t tok, how;
        memcpy(&tok, data + sizeof b + 4 + i * 8, 4);
        memcpy(&how, data + sizeof b + 8 + i * 8, 4);
        g_coldTokens[tok] = how;
        maxId = std::max(maxId, (tok - kTokenBase) / 0x10 + 1);
    }
    g_nextFiberId = maxId;
    memcpy(C.r, b.r, sizeof C.r);
    C.NG = b.NG; C.ZR = b.ZR; C.CY = b.CY; C.OV = b.OV; C.Q = b.Q; C.TB = b.TB;
    C.cpsr = b.cpsr; C.spsr = b.spsr;
    memcpy(g_bankR13, b.bankR13, sizeof g_bankR13);
    memcpy(g_bankR14, b.bankR14, sizeof g_bankR14);
    memcpy(g_bankSpsr, b.bankSpsr, sizeof g_bankSpsr);
    refreshTcm();
    C.cycles = (int64_t)g_nds->ARM9Timestamp;
    C.target = (int64_t)g_nds->ARM9Target;
    C.resume = 0;
    // the saved thread either waited for an interrupt in a leaf call (it continues by returning
    // from it) or was about to call `target` (it calls it again)
    g_halted = b.halted;
    g_haltWfi = false;
    g_coldCall = b.target;
    g_cur = newFiber(b.kind == 1 ? kColdCall : kColdReturn);
    C.ss = g_cur->ss.data();
    C.ssp = 0;
    logf("[rt] state loaded: resuming at %08x (sp %08x)\n", C.r[14], C.r[13]);
    return true;
}

void dumpStats() {
    logf("[rt] interpreted instructions: %llu\n", (unsigned long long)g_interpSteps);
    logf("[rt] stats: yields=%llu irqs=%llu halts=%llu indirect_calls=%llu swis=%llu thread_switches=%llu fibers=%zu\n",
         (unsigned long long)g_stats.yields, (unsigned long long)g_stats.irqs, (unsigned long long)g_stats.halts,
         (unsigned long long)g_stats.calls, (unsigned long long)g_stats.swis, (unsigned long long)g_stats.threadSwitches, g_fibers.size());
    logf("[rt] cycles=%lld target=%lld halted=%d irqline=%d IME=%x IE=%08x IF=%08x cpsr=%08x irq_handler=%08x\n",
         (long long)C.cycles, (long long)C.target, g_halted, g_arm9->IRQ, g_nds->IME[0], g_nds->IE[0], g_nds->IF[0], rt_cpsr_read(&C), g_lastIrqHandler);
    logf("[rt] regs:");
    for (int i = 0; i < 16; i++) logf(" r%d=%08x", i, C.r[i]);
    logf("\n[rt] recent indirect calls:");
    for (unsigned i = 0; i < 64; i++) logf(" %08x", g_recentCalls[(g_recentPos + i) & 63]);
    logf("\n");
}

}  // namespace recomp
