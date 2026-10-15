// ABI between generated (recompiled) game code and the runtime.
#pragma once
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct Cpu {
    uint32_t r[16];          // r0-r15 (r13 sp, r14 lr, r15 pc)
    uint8_t NG, ZR, CY, OV;  // condition flags
    uint8_t Q, TB;           // sticky overflow, thumb bit
    uint8_t pad[2];
    uint32_t cpsr;           // mode/I/F bits (flags live in NG..OV; composed on read)
    uint32_t spsr;
    int64_t cycles;          // ARM9 cycles executed (in ARM9 clock units)
    int64_t target;          // run until cycles >= target, then yield
    uint32_t ret;            // address a function returned to
    uint32_t irq_pending;    // set by the hardware model
    uint8_t* main_ram;       // 4 MB main RAM
    uint32_t main_ram_mask;
    uint8_t* itcm;           // 32 KB
    uint32_t itcm_size;      // mapped size (0 if disabled)
    uint8_t* dtcm;           // 16 KB
    uint32_t dtcm_base, dtcm_mask;
    void* rt;                // runtime private
    uint32_t* ss;            // shadow stack of expected return addresses (per guest thread)
    uint32_t ssp;
} Cpu;

// debug write watchpoint (MSDS_WATCH=addr[:len]); g_watch_len is 0 when disabled
extern uint32_t g_watch_lo, g_watch_len;
void rt_watch(Cpu*, uint32_t addr, uint32_t size, uint32_t val);

extern int g_rt_trace;
int rt_trace(Cpu*, uint32_t addr);   // nonzero: the runtime already executed the function (debug)
void rt_img_step(Cpu*, uint32_t addr);  // per-instruction trace of code images (debug, MSDS_IMG_STEP build)
#define TRACE_ENTRY(a) do { if (__builtin_expect(g_rt_trace, 0) && rt_trace(c, (a))) return; } while (0)

#define SS_PUSH(a) (c->ss[c->ssp++] = (a))
#define SS_POP() (c->ssp--)

typedef void (*GuestFn)(Cpu*);

// slow paths (I/O, VRAM, …) implemented by the runtime
uint8_t rt_read8(Cpu*, uint32_t);
uint16_t rt_read16(Cpu*, uint32_t);
uint32_t rt_read32(Cpu*, uint32_t);
void rt_write8(Cpu*, uint32_t, uint8_t);
void rt_write16(Cpu*, uint32_t, uint16_t);
void rt_write32(Cpu*, uint32_t, uint32_t);

void rt_yield(Cpu*);                                  // cycles >= target: let hardware catch up, take IRQs
void rt_call(Cpu*, uint32_t target);                  // indirect call through the dispatcher
int rt_in_stack(Cpu*, uint32_t addr);                 // is addr an expected return of an outer frame?
uint32_t rt_get_user(Cpu*, uint32_t n);               // user-bank register (LDM/STM ^)
void rt_set_user(Cpu*, uint32_t n, uint32_t v);
void rt_bad_return(Cpu*, uint32_t expected, uint32_t got, uint32_t at);
void rt_userop(Cpu*, uint32_t op, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t at);
void rt_swi(Cpu*, uint32_t num, uint32_t at);
void rt_cpsr_written(Cpu*, uint32_t old_cpsr);
uint32_t rt_cpsr_read(Cpu*);
void rt_spsr_restore(Cpu*);                           // exception return (CPSR = SPSR)
void rt_missing(Cpu*, uint32_t at, const char* why);

// ---------------------------------------------------------------- memory fast paths
static inline int in_itcm(Cpu* c, uint32_t a) { return a < c->itcm_size; }
static inline int in_dtcm(Cpu* c, uint32_t a) { return (a & c->dtcm_mask) == c->dtcm_base; }

#define MEM_FAST(N, T)                                                                    \
static inline T mem_read##N(Cpu* c, uint32_t a) {                                         \
    T v;                                                                                  \
    if ((a >> 24) == 0x02 && !in_dtcm(c, a)) { memcpy(&v, c->main_ram + (a & c->main_ram_mask & ~(uint32_t)(sizeof(T) - 1)), sizeof(T)); return v; } \
    return (T)rt_read##N(c, a);                                                           \
}                                                                                         \
static inline void mem_write##N(Cpu* c, uint32_t a, T v) {                                \
    if (__builtin_expect(a - g_watch_lo < g_watch_len, 0)) rt_watch(c, a, sizeof(T), (uint32_t)v); \
    if ((a >> 24) == 0x02 && !in_dtcm(c, a)) { memcpy(c->main_ram + (a & c->main_ram_mask & ~(uint32_t)(sizeof(T) - 1)), &v, sizeof(T)); return; } \
    rt_write##N(c, a, v);                                                                 \
}
MEM_FAST(8, uint8_t)
MEM_FAST(16, uint16_t)
MEM_FAST(32, uint32_t)

// ARM9 LDR from an unaligned address reads the aligned word and rotates it
static inline uint32_t mem_read32_rot(Cpu* c, uint32_t a) {
    uint32_t v = mem_read32(c, a);
    uint32_t s = (a & 3) * 8;
    return s ? (v >> s) | (v << (32 - s)) : v;
}

// ---------------------------------------------------------------- p-code helpers
static inline uint64_t shl64(uint64_t a, uint64_t s) { return s >= 64 ? 0 : a << s; }
static inline uint64_t shr64(uint64_t a, uint64_t s) { return s >= 64 ? 0 : a >> s; }
static inline int64_t sar64(int64_t a, uint64_t s) { return s >= 64 ? (a < 0 ? -1 : 0) : a >> s; }
static inline uint32_t clz32(uint32_t v) { return v ? (uint32_t)__builtin_clz(v) : 32; }

#define CYC(n) (c->cycles += (n))  /* ~1 ARM9 cycle per instruction */
#define CHECK() do { if (__builtin_expect(c->cycles >= c->target, 0)) rt_yield(c); } while (0)

#ifdef __cplusplus
}
#endif
