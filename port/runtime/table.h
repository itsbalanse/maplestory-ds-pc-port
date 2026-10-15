#pragma once
#include "recomp.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct GuestFnEntry {
    uint32_t addr;
    int overlay;     // -1: always resident (static ARM9 / ITCM), otherwise overlay id
    int thumb;
    GuestFn fn;
    uint32_t sig[2]; // first 8 code bytes, to check which overlay is resident
    const uint8_t* body;  // overlay functions: original code bytes (up to 256) for an exact check
    uint32_t body_len;
} GuestFnEntry;

// Code range of a function that also has a multi-entry variant (hand-written assembly): jumps into
// the middle of it run fn_multi(c, target) when the owning image is resident.
typedef struct GuestRange {
    uint32_t start, end, entry;
    int overlay;
    void (*fn_multi)(Cpu*, uint32_t);
    const uint8_t* body;   // entry code bytes, to check which image is resident
    uint32_t body_len;
} GuestRange;

extern const GuestRange g_guest_ranges[];
extern const unsigned g_guest_range_count;

extern const GuestFnEntry g_guest_fns[];
extern const unsigned g_guest_fn_count;
extern const unsigned g_guest_primary_count;

#ifdef __cplusplus
}
#endif
