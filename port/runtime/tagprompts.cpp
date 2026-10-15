// Override of the game's text tag expansion (FUN_02017a70, see tagprompts.h).
//
// The game keeps text in a libc++-style u16string (12-byte object). Edits go through the game's
// own string functions so its allocator stays in charge; the pattern and replacement are placed
// as C strings in scratch space below the guest stack pointer.
#include "tagprompts.h"
#include "recomp.h"

// weak: the build without generated code (interpreter only) has none of these
#define WEAK __attribute__((weak))
extern "C" {
WEAK void f_ram_02017a70(Cpu*);  // original: expand \[A\] -> U+E000 etc., colours, player names
WEAK void f_ram_02012e8c(Cpu*);  // string(obj, const char16_t*)
WEAK void f_ram_02017cb0(Cpu*);  // int find(str, const string& pat, uint pos) (-1 if absent)
WEAK void f_ram_02017c84(Cpu*);  // replace(str, pos, len, const char16_t*)
WEAK void f_ram_0200b830(Cpu*);  // ~string(obj)
void ovr_ExpandTags(Cpu* c);
}

namespace {
recomp::TagReplacements g_repl;

constexpr uint32_t kRet = 0x02017a70u;  // return address for our calls (nothing returns there)

uint32_t call(Cpu* c, void (*fn)(Cpu*), uint32_t a0, uint32_t a1 = 0, uint32_t a2 = 0, uint32_t a3 = 0) {
    c->r[0] = a0; c->r[1] = a1; c->r[2] = a2; c->r[3] = a3;
    c->r[14] = kRet;
    SS_PUSH(kRet);
    fn(c);
    SS_POP();
    return c->r[0];
}

void putWide(Cpu* c, uint32_t at, const std::u16string& s) {
    for (size_t i = 0; i < s.size(); i++) mem_write16(c, at + (uint32_t)i * 2, (uint16_t)s[i]);
    mem_write16(c, at + (uint32_t)s.size() * 2, 0);
}
}  // namespace

namespace recomp {
void setTagReplacements(TagReplacements r) { g_repl = std::move(r); }
}

extern "C" void ovr_ExpandTags(Cpu* c) {
    const uint32_t str = c->r[0], flag = c->r[1], lr = c->r[14], sp = c->r[13];
    if (!g_repl.empty()) {
        // scratch: [obj 16][pattern 0x60][replacement 0x100], kept below the live stack
        const uint32_t base = (sp - 0x180) & ~7u, obj = base, pat = base + 0x10, rep = base + 0x70;
        c->r[13] = base - 0x10;
        for (const auto& [from, to] : g_repl) {
            if (from.empty() || from.size() > 0x2f || to.size() > 0x7f) continue;
            putWide(c, pat, from);
            putWide(c, rep, to);
            call(c, f_ram_02012e8c, obj, pat);
            uint32_t pos = 0;
            for (int guard = 0; guard < 64; guard++) {
                int32_t at = (int32_t)call(c, f_ram_02017cb0, str, obj, pos);
                if (at < 0) break;
                call(c, f_ram_02017c84, str, (uint32_t)at, (uint32_t)from.size(), rep);
                pos = (uint32_t)at + (uint32_t)to.size();
            }
            call(c, f_ram_0200b830, obj);
        }
        c->r[13] = sp;
    }
    c->r[0] = str; c->r[1] = flag; c->r[14] = lr;
    f_ram_02017a70(c);
}
