"""Static recompiler back-end: Ghidra P-code export -> C.

usage: python pcode2c.py <pcode_export.txt> <outdir> [--per-file N]

Every guest function becomes `void f_<space>_<addr>(Cpu* c)`. Intra-function control flow
becomes goto; direct calls become C calls; returns become C returns. Indirect transfers go
through the runtime dispatcher. See port/DESIGN.md.
"""
import os
import sys
import collections

STATE_REGS = {f'r{i}': f'c->r[{i}]' for i in range(13)}
STATE_REGS.update({'sp': 'c->r[13]', 'lr': 'c->r[14]', 'pc': 'c->r[15]',
                   'NG': 'c->NG', 'ZR': 'c->ZR', 'CY': 'c->CY', 'OV': 'c->OV',
                   'Q': 'c->Q', 'TB': 'c->TB', 'cpsr': 'c->cpsr', 'spsr': 'c->spsr'})
CTYPE = {1: 'uint8_t', 2: 'uint16_t', 4: 'uint32_t', 8: 'uint64_t'}
STYPE = {1: 'int8_t', 2: 'int16_t', 4: 'int32_t', 8: 'int64_t'}


class Vn:
    __slots__ = ('space', 'off', 'size')

    def __init__(self, s):
        sp, off, size = s.split(':')
        self.space, self.off, self.size = sp, int(off, 16), int(size)


class Insn:
    __slots__ = ('addr', 'length', 'thumb', 'text', 'ops', 'jumps', 'raw')

    def __init__(self, addr, length, thumb, text, raw=b''):
        self.addr, self.length, self.thumb, self.text, self.raw = addr, length, thumb, text, raw
        self.ops = []
        self.jumps = []


class Func:
    __slots__ = ('entry', 'thumb', 'space', 'name', 'ranges', 'insns')

    def __init__(self, entry, thumb, space, name):
        self.entry, self.thumb, self.space, self.name = entry, thumb, space, name
        self.ranges = []
        self.insns = []

    @property
    def cname(self):
        return 'f_%s_%08x' % (self.space, self.entry)

    def contains(self, a):
        return any(s <= a < e for s, e in self.ranges)


def parse(path):
    regs, userops, funcs = {}, {}, []
    f = cur = ins = None
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            t = line[0]
            if t == 'P':
                parts = line.split()
                ins.ops.append((parts[1], None if parts[2] == '-' else Vn(parts[2]), [Vn(x) for x in parts[3:]]))
            elif t == 'I':
                head, _, text = line.rstrip('\n').partition(' ; ')
                _, a, ln, th, _hex = head.split()
                ins = Insn(int(a, 16), int(ln), th == '1', text, bytes.fromhex(_hex))
                cur.insns.append(ins)
            elif t == 'F':
                parts = line.split()
                cur = Func(int(parts[1], 16), parts[2] == '1', parts[3], parts[4] if len(parts) > 4 else '')
                funcs.append(cur)
            elif t == 'B':
                _, s, e = line.split()
                cur.ranges.append((int(s, 16), int(e, 16)))
            elif t == 'J':
                _, a, b = line.split()
                ins.jumps.append(int(b, 16))
            elif t == 'R':
                _, off, size, name = line.split()
                regs.setdefault((int(off, 16), int(size)), name)
            elif t == 'U':
                _, idx, name = line.split()
                userops[int(idx)] = name
    return regs, userops, funcs


# Guest functions replaced by runtime implementations (see port/runtime/overrides.cpp).
OVERRIDES = {
    0x020c3af8: 'ovr_OS_SaveContext',
    0x020c3b44: 'ovr_OS_LoadContext',
}

COND_C = {0x0: 'c->ZR', 0x1: '!c->ZR', 0x2: 'c->CY', 0x3: '!c->CY', 0x4: 'c->NG', 0x5: '!c->NG',
          0x6: 'c->OV', 0x7: '!c->OV', 0x8: '(c->CY && !c->ZR)', 0x9: '(!c->CY || c->ZR)',
          0xa: '(c->NG == c->OV)', 0xb: '(c->NG != c->OV)', 0xc: '(!c->ZR && c->NG == c->OV)',
          0xd: '(c->ZR || c->NG != c->OV)'}


ITCM_OV0 = (0x01ff8500, 0x01ffa2e0)     # overlay 0, resident in ITCM most of the time
ITCM_SWAP = (0x01ff8500, 0x01ffeae0)    # range the movie decoder (pseudo-overlay 200) replaces


def in_itcm_overlay(a):
    return ITCM_SWAP[0] <= a < ITCM_SWAP[1]


def image_of(fn):
    if fn.space != 'ram':
        return fn.space
    if ITCM_OV0[0] <= fn.entry < ITCM_OV0[1]:
        return 'itcm0'
    return 'ram'


def overlay_id(fn, addr):
    """Overlay id stored in the dispatch table (-1 = always resident)."""
    if fn.space == 'ram':
        return 0 if ITCM_OV0[0] <= addr < ITCM_OV0[1] else -1
    return int(fn.space[2:]) if fn.space.startswith('ov') else -2


class Emitter:
    def __init__(self, regs, userops, funcs):
        self.regs, self.userops = regs, userops
        self.funcs = funcs
        self.by_space = collections.defaultdict(dict)
        for fn in funcs:
            self.by_space[fn.space][fn.entry] = fn
        self.static_spaces = {'ram'}
        self.unknown_regs = collections.Counter()
        self.unknown_ops = collections.Counter()

    # ------------------------------------------------------------- varnodes
    def regname(self, v):
        n = self.regs.get((v.off, v.size))
        if n is None:
            # sub-register access: find containing register
            for (off, size), name in self.regs.items():
                if off == v.off and size >= v.size:
                    n = name
                    break
        return n or 'reg_%x_%d' % (v.off, v.size)

    def rd(self, v, locals_):
        """C expression reading varnode v."""
        if v.space == 'c':
            if v.size == 8:
                return '0x%xull' % (v.off & 0xffffffffffffffff)
            return '((%s)0x%xu)' % (CTYPE.get(v.size, 'uint32_t'), v.off & ((1 << (8 * v.size)) - 1))
        if v.space == 'r':
            n = self.regname(v)
            if n in STATE_REGS:
                expr = STATE_REGS[n]
                return '(%s)%s' % (CTYPE[v.size], expr) if v.size != 4 and n.startswith('r') else expr
            locals_[('reg', n, v.size)] = 1
            return 'R_%s_%d' % (n, v.size)
        if v.space == 'u':
            locals_[('u', v.off, v.size)] = 1
            return 'u_%x_%d' % (v.off, v.size)
        if v.space in ('m', 'o'):
            if v.size == 8:
                return '((uint64_t)mem_read32(c, 0x%xu) | ((uint64_t)mem_read32(c, 0x%xu) << 32))' % (v.off, v.off + 4)
            return 'mem_read%d(c, 0x%xu)' % (8 * v.size, v.off)
        raise ValueError('cannot read varnode space %s' % v.space)

    def wr(self, v, locals_):
        if v.space == 'r':
            n = self.regname(v)
            if n in STATE_REGS:
                return STATE_REGS[n]
            locals_[('reg', n, v.size)] = 1
            return 'R_%s_%d' % (n, v.size)
        if v.space == 'u':
            locals_[('u', v.off, v.size)] = 1
            return 'u_%x_%d' % (v.off, v.size)
        raise ValueError('cannot write varnode space %s' % v.space)

    # ------------------------------------------------------------- functions
    def target_fn(self, fn, addr, space):
        """Resolve a direct branch/call target to a known function (or None)."""
        if space == 'o':
            return self.by_space[fn.space].get(addr)
        return self.by_space['ram'].get(addr)

    def emit_function(self, fn, alt_entry=None, multi=False):
        """Emit C for fn. alt_entry: emit a secondary entry point (copy of fn starting at that address).
        multi: emit `<name>_m(Cpu*, uint32_t at)` that can start at any instruction (computed jumps
        into hand-written assembly; the runtime falls back to it for mid-function targets)."""
        L = []  # body lines
        locals_ = collections.OrderedDict()
        insn_addrs = {i.addr for i in fn.insns}
        labels = set()
        if alt_entry is not None:
            labels.add(alt_entry)
        if multi:
            labels.update(insn_addrs)
        # Ghidra bodies can contain blocks located before the entry point (shared tails):
        # instructions are emitted in address order, so jump to the entry first.
        entry_goto = alt_entry is None and not multi and fn.insns and fn.insns[0].addr != fn.entry \
            and any(i.addr == fn.entry for i in fn.insns)
        if entry_goto:
            labels.add(fn.entry)
        # functions with an unresolved computed jump that is not a tail call through a register
        # loaded from a literal (veneer) get every instruction as a possible target
        self.cur_dense = False
        for idx2, ins2 in enumerate(fn.insns):
            if not any(o[0] == 'BRANCHIND' for o in ins2.ops):
                continue
            computed = any(t in ins2.text for t in ('add pc', 'addls pc', 'addcc pc', 'ldr pc,[pc', 'ldrls pc', 'mov pc,r', 'sub pc'))
            linked = self.links_to(fn.insns[idx2 - 1] if idx2 else None, ins2.addr + ins2.length)
            if computed and not linked and (not ins2.jumps or 'add pc' in ins2.text):
                self.cur_dense = True
        if self.cur_dense:
            labels.update(insn_addrs)
        # pre-scan branch targets
        for ins in fn.insns:
            for opc, out, ins_ in ins.ops:
                if opc in ('BRANCH', 'CBRANCH') and ins_[0].space in ('m', 'o') and ins_[0].off in insn_addrs:
                    labels.add(ins_[0].off)
            for j in ins.jumps:
                if j in insn_addrs:
                    labels.add(j)
        pending = 0

        def flush():
            nonlocal pending
            if pending:
                L.append('    CYC(%d);' % pending)
                pending = 0

        # return sites (instruction after each call) are resume points for context switches
        self.cur_uses_resolver = False
        ret_sites = []
        prev = None
        for ins in fn.insns:
            nxt = ins.addr + ins.length
            linked = any(opc == 'BRANCHIND' for opc, _, _ in ins.ops) and self.links_to(prev, nxt)
            if (linked or any(opc in ('CALL', 'CALLIND') for opc, _, _ in ins.ops)) and nxt in insn_addrs:
                ret_sites.append(nxt)
                labels.add(nxt)
            prev = ins
        self.cur_ret_sites = ret_sites

        for idx, ins in enumerate(fn.insns):
            self.prev_ins = fn.insns[idx - 1] if idx > 0 else None
            if ins.addr in labels:
                flush()
                L.append('L_%08x:' % ins.addr)
            L.append('    /* %08x: %s */' % (ins.addr, ins.text.replace('*/', '* /')))
            pending += 1
            nxt = fn.insns[idx + 1].addr if idx + 1 < len(fn.insns) else None
            fallthrough_addr = ins.addr + ins.length
            # p-code relative branch targets inside this instruction
            rel = set()
            for k, (opc, out, ins_) in enumerate(ins.ops):
                if opc in ('BRANCH', 'CBRANCH') and ins_[0].space == 'c':
                    rel.add(k + ins_[0].off if ins_[0].off < 0x80000000 else k + ins_[0].off - (1 << 64))
            ends_with_transfer = False
            cp = self.cp15(ins)
            if cp is not None:
                L.extend(cp)
                continue
            for k, (opc, out, ins_) in enumerate(ins.ops):
                if k in rel:
                    L.append('  P_%08x_%d:;' % (ins.addr, k))
                line, transfer = self.emit_op(fn, ins, k, opc, out, ins_, locals_, flush, fallthrough_addr)
                if line:
                    L.extend(line if isinstance(line, list) else [line])
                ends_with_transfer = transfer
            if len(ins.ops) in rel:
                L.append('  P_%08x_%d:;' % (ins.addr, len(ins.ops)))
            # fall through into a non-contiguous next instruction
            if nxt is not None and nxt != fallthrough_addr and not ends_with_transfer:
                flush()
                L.append('    goto L_%08x;' % fallthrough_addr if fallthrough_addr in insn_addrs else
                         '    { rt_call(c, 0x%08xu); return; }' % fallthrough_addr)
                if fallthrough_addr in insn_addrs:
                    labels.add(fallthrough_addr)
        flush()
        last = fn.insns[-1] if fn.insns else None
        # Ghidra ended the body without a return (e.g. a no-return call): continue at the next address
        L.append('    { rt_call(c, 0x%08xu); return; }' % ((last.addr + last.length) if last else fn.entry))
        if self.cur_uses_resolver:
            L.extend(self.resolver_block())

        cname = fn.cname if alt_entry is None else 'f_%s_%08x' % (fn.space, alt_entry)
        if multi:
            out = ['void %s_m(Cpu* c, uint32_t at) {' % fn.cname]
        else:
            out = ['void %s(Cpu* c) {' % cname]
        if self.cur_uses_resolver:
            out.append('    uint32_t exp_ret = 0;')
        for key in locals_:
            if key[0] == 'u':
                out.append('    %s u_%x_%d;' % (CTYPE.get(key[2], 'uint64_t'), key[1], key[2]))
            else:
                out.append('    %s R_%s_%d = 0;' % (CTYPE.get(key[2], 'uint64_t'), key[1], key[2]))
        out.append('    CHECK();')
        if alt_entry is None and not multi:
            out.append('    TRACE_ENTRY(0x%08xu);' % fn.entry)
        if alt_entry is not None:
            out.append('    goto L_%08x;' % alt_entry)
        if entry_goto:
            out.append('    goto L_%08x;' % fn.entry)
        if multi:
            cases = ' '.join('case 0x%08xu: goto L_%08x;' % (i.addr, i.addr) for i in fn.insns)
            out.append('    switch (at) { %s default: rt_missing(c, at, "bad multi-entry target"); return; }' % cases)
        # labels referenced by late-added gotos must exist: re-insert if missing
        body = '\n'.join(L)
        for a in labels:
            if ('L_%08x:' % a) not in body:
                body = body.replace('    /* %08x:' % a, 'L_%08x:\n    /* %08x:' % (a, a), 1)
        out.append(body)
        out.append('}')
        return '\n'.join(out)

    def psr(self, ins):
        """MRS/MSR decoded from the instruction word. Ghidra's ARM spec builds MRS results from the
        flags only (mode/I/F bits read as 0), which breaks OS_DisableInterrupts-style code."""
        if ins.thumb or len(ins.raw) != 4:
            return None
        w = int.from_bytes(ins.raw, 'little')
        cond = w >> 28
        spsr = (w >> 22) & 1
        if (w & 0x0FBF0FFF) == 0x010F0000:      # MRS Rd, PSR
            rd = (w >> 12) & 0xF
            body = 'c->r[%d] = %s;' % (rd, 'c->spsr' if spsr else 'rt_cpsr_read(c)')
        elif (w & 0x0FB0FFF0) == 0x0120F000 or (w & 0x0FB0F000) == 0x0320F000:   # MSR PSR_fields, Rm/#imm
            fields = (w >> 16) & 0xF
            mask = sum(0xFF << (8 * i) for i in range(4) if fields & (1 << i))
            if w & (1 << 25):
                rot = ((w >> 8) & 0xF) * 2
                imm = w & 0xFF
                val = '0x%08xu' % (((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF if rot else imm)
            else:
                val = 'c->r[%d]' % (w & 0xF)
            if spsr:
                body = 'c->spsr = (c->spsr & ~0x%08xu) | (%s & 0x%08xu);' % (mask, val, mask)
            else:
                body = 'rt_msr_cpsr(c, %s, 0x%08xu);' % (val, mask)
        else:
            return None
        if cond == 0xE:
            return ['    ' + body]
        if cond in COND_C:
            return ['    if (%s) { %s }' % (COND_C[cond], body)]
        return None

    @staticmethod
    def links_to(prev, addr):
        """True if instruction `prev` sets lr to the constant `addr` (e.g. `mov lr, pc` before `bx r3`)."""
        if prev is None:
            return False
        for opc, out, inp in prev.ops:
            if opc == 'COPY' and out is not None and out.space == 'r' and out.off == 0x58 and inp[0].space == 'c'                     and (inp[0].off & ~1) == addr:
                return True
        return False

    def ldm_user(self, ins):
        """LDM/STM with the S bit: Ghidra ignores `^` (user-bank r13/r14, or CPSR<-SPSR when
        loading pc). Decoded here so OS thread switching in IRQ mode saves the right registers."""
        if ins.thumb or len(ins.raw) != 4:
            return None
        w = int.from_bytes(ins.raw, 'little')
        if (w & 0x0E400000) != 0x08400000:
            return None
        cond, p, u, wb, load = w >> 28, (w >> 24) & 1, (w >> 23) & 1, (w >> 21) & 1, (w >> 20) & 1
        rn, regs = (w >> 16) & 0xF, [i for i in range(16) if w & (1 << i)]
        n = len(regs)
        if u:
            start = 'b + 4' if p else 'b'
            final = 'b + %d' % (4 * n)
        else:
            start = 'b - %d' % (4 * n) if p else 'b - %d' % (4 * n - 4)
            final = 'b - %d' % (4 * n)
        lines = ['{ uint32_t b = c->r[%d]; uint32_t a = %s;' % (rn, start)]
        exc_return = load and 15 in regs
        for r in regs:
            if load:
                if r == 15:
                    lines.append(' uint32_t newpc = mem_read32(c, a); a += 4;')
                elif exc_return:
                    lines.append(' c->r[%d] = mem_read32(c, a); a += 4;' % r)
                else:
                    lines.append(' rt_set_user(c, %d, mem_read32(c, a)); a += 4;' % r)
            else:
                lines.append(' mem_write32(c, a, rt_get_user(c, %d)); a += 4;' % r)
        if wb and not (load and rn in regs):
            lines.append(' c->r[%d] = %s;' % (rn, final))
        if exc_return:
            lines.append(' rt_spsr_restore(c); rt_call(c, newpc); return; }')
        else:
            lines.append(' }')
        body = ''.join(lines)
        if cond == 0xE:
            return ['    ' + body]
        if cond in COND_C:
            return ['    if (%s) %s' % (COND_C[cond], body)]
        return None

    def cp15(self, ins):
        """MCR/MRC p15 decoded from the instruction word (Ghidra's named ops drop CRm/opc2)."""
        psr = self.psr(ins)
        if psr is not None:
            return psr
        um = self.ldm_user(ins)
        if um is not None:
            return um
        if ins.thumb or len(ins.raw) != 4:
            return None
        w = int.from_bytes(ins.raw, 'little')
        if (w & 0x0F000010) != 0x0E000010 or ((w >> 8) & 0xF) != 15:
            return None
        cond = w >> 28
        load = (w >> 20) & 1
        rd = (w >> 12) & 0xF
        cid = (((w >> 16) & 0xF) << 8) | ((w & 0xF) << 4) | ((w >> 5) & 7)
        if load:
            body = 'c->r[%d] = rt_cp15_read(c, 0x%03x);' % (rd, cid) if rd != 15 else '(void)rt_cp15_read(c, 0x%03x);' % cid
        else:
            body = 'rt_cp15_write(c, 0x%03x, c->r[%d], 0x%08xu);' % (cid, rd, ins.addr)
        if cond == 0xE:
            return ['    ' + body]
        if cond in COND_C:
            return ['    if (%s) { %s }' % (COND_C[cond], body)]
        return None

    def ret_check(self, fall, at):
        # Unexpected return address: handled by the function's shared resolver block (see emit_function)
        self.cur_uses_resolver = True
        return '    if (__builtin_expect(c->ret != 0x%08xu, 0)) { exp_ret = 0x%08xu; goto resolve; }' % (fall, fall)

    def resolver_block(self):
        cases = ' '.join('case 0x%08xu: goto L_%08x;' % (a, a) for a in self.cur_ret_sites)
        return ['resolve:',
                '    for (;;) {',
                '        switch (c->ret) { %s }' % cases,
                '        if (rt_in_stack(c, c->ret)) return;       /* unwinding to an outer frame */',
                '        SS_PUSH(exp_ret); rt_call(c, c->ret); SS_POP();  /* continue at a computed address */',
                '    }']

    @staticmethod
    def wrap_call(call):
        return 'SS_PUSH(exp_now); %s SS_POP();' % call

    def call_expr(self, fn, addr, space):
        if addr in OVERRIDES and (space == 'm' or fn.space == 'ram'):
            return '%s(c);' % OVERRIDES[addr]
        t = self.target_fn(fn, addr, space)
        if t is not None and t.space == 'ram' and in_itcm_overlay(addr) and image_of(fn) != 'itcm0':
            # ITCM above 0x01ff8500 is swapped at runtime (overlay 0 / movie decoder): dispatch
            return 'rt_call(c, 0x%08xu);' % addr
        if t is not None and (t.space == 'ram' or t.space == fn.space):
            return '%s(c);' % t.cname
        return 'rt_call(c, 0x%08xu);' % addr

    def emit_op(self, fn, ins, k, opc, out, inp, locals_, flush, fall):
        R = lambda v: self.rd(v, locals_)
        W = lambda v: self.wr(v, locals_)
        T = lambda v: CTYPE.get(v.size, 'uint64_t')
        S = lambda v: STYPE.get(v.size, 'int64_t')
        bits = lambda v: 8 * v.size

        def assign(expr):
            if out.space in ('m', 'o'):
                if out.size == 8:
                    return '    { uint64_t _v = (uint64_t)(%s); mem_write32(c, 0x%xu, (uint32_t)_v); mem_write32(c, 0x%xu, (uint32_t)(_v >> 32)); }' % (expr, out.off, out.off + 4)
                return '    mem_write%d(c, 0x%xu, (%s)(%s));' % (8 * out.size, out.off, T(out), expr)
            return '    %s = (%s)(%s);' % (W(out), T(out), expr)

        a = inp[0] if inp else None
        b = inp[1] if len(inp) > 1 else None
        reads_cpsr = any(v.space == 'r' and self.regname(v) == 'cpsr' for v in inp)
        writes_cpsr = out is not None and out.space == 'r' and self.regname(out) == 'cpsr'
        if not (reads_cpsr or writes_cpsr):
            return self.emit_op2(fn, ins, k, opc, out, inp, locals_, flush, fall)
        line, tr = self.emit_op2(fn, ins, k, opc, out, inp, locals_, flush, fall)
        lines = [] if line is None else (line if isinstance(line, list) else [line])
        if writes_cpsr and not (opc == 'COPY' and any('rt_cpsr_written' in x for x in lines)):
            lines = ['    { uint32_t old_cpsr = c->cpsr;'] + ['  ' + x for x in lines] + ['    rt_cpsr_written(c, old_cpsr); }']
        if reads_cpsr:
            lines = ['    c->cpsr = rt_cpsr_read(c);'] + lines
        return lines, tr

    def emit_op2(self, fn, ins, k, opc, out, inp, locals_, flush, fall):
        R = lambda v: self.rd(v, locals_)
        W = lambda v: self.wr(v, locals_)
        T = lambda v: CTYPE.get(v.size, 'uint64_t')
        S = lambda v: STYPE.get(v.size, 'int64_t')
        bits = lambda v: 8 * v.size

        def assign(expr):
            if out.space in ('m', 'o'):
                if out.size == 8:
                    return '    { uint64_t _v = (uint64_t)(%s); mem_write32(c, 0x%xu, (uint32_t)_v); mem_write32(c, 0x%xu, (uint32_t)(_v >> 32)); }' % (expr, out.off, out.off + 4)
                return '    mem_write%d(c, 0x%xu, (%s)(%s));' % (8 * out.size, out.off, T(out), expr)
            return '    %s = (%s)(%s);' % (W(out), T(out), expr)

        a = inp[0] if inp else None
        b = inp[1] if len(inp) > 1 else None
        if opc == 'COPY':
            line = assign(R(a))
            if out.space == 'r' and self.regname(out) == 'cpsr':
                return ['    { uint32_t old_cpsr = c->cpsr;', '  ' + line, '    rt_cpsr_written(c, old_cpsr); }'], False
            return line, False
        if opc == 'LOAD':
            addr = R(b)
            if out.size == 4:
                return assign('mem_read32_rot(c, %s)' % addr), False
            if out.size in (1, 2):
                return assign('mem_read%d(c, %s)' % (bits(out), addr)), False
            if out.size == 8:
                return assign('(uint64_t)mem_read32(c, %s) | ((uint64_t)mem_read32(c, (%s) + 4) << 32)' % (addr, addr)), False
        if opc == 'STORE':
            addr, val = R(inp[1]), inp[2]
            if val.size == 8:
                return '    { uint32_t _a = %s; uint64_t _v = %s; mem_write32(c, _a, (uint32_t)_v); mem_write32(c, _a + 4, (uint32_t)(_v >> 32)); }' % (addr, R(val)), False
            return '    mem_write%d(c, %s, %s);' % (bits(val), addr, R(val)), False
        if opc in ('BRANCH', 'CBRANCH'):
            cond = None if opc == 'BRANCH' else R(b)
            if a.space == 'c':
                rel = a.off if a.off < 0x80000000 else a.off - (1 << 64)
                tgt = 'goto P_%08x_%d;' % (ins.addr, k + rel)
                return ('    if (%s) %s' % (cond, tgt) if cond else '    ' + tgt), cond is None
            dest = a.off
            if fn.contains(dest) and any(i.addr == dest for i in fn.insns):
                back = dest <= ins.addr
                pre = []
                body = 'goto L_%08x;' % dest
                if back:
                    body = '{ CYC(%d); CHECK(); goto L_%08x; }' % (0, dest)
                flush_lines = []
                if cond:
                    # account cycles on both paths: flush before the test
                    flush()
                    return '    if (%s) %s' % (cond, body), False
                flush()
                return '    ' + body, True
            # branch out of the function: tail call
            flush()
            call = self.call_expr(fn, dest, a.space)
            if cond:
                return '    if (%s) { %s return; }' % (cond, call), False
            return '    { %s return; }' % call, True
        if opc == 'CALL':
            flush()
            call = self.call_expr(fn, a.off, a.space)
            return ['    SS_PUSH(0x%08xu); %s SS_POP();' % (fall, call), self.ret_check(fall, ins.addr)], False
        if opc == 'CALLIND':
            flush()
            return ['    SS_PUSH(0x%08xu); rt_call(c, %s); SS_POP();' % (fall, R(a)), self.ret_check(fall, ins.addr)], False
        if opc == 'RETURN':
            flush()
            return '    { c->ret = (%s) & ~1u; return; }' % R(a), True
        if opc == 'BRANCHIND' and self.links_to(getattr(self, 'prev_ins', None), fall) and fall in self.cur_ret_sites:
            flush()  # `mov lr, pc; bx rX` is a call
            return ['    SS_PUSH(0x%08xu); rt_call(c, %s); SS_POP();' % (fall, R(a)), self.ret_check(fall, ins.addr)], False
        if opc == 'BRANCHIND':
            flush()
            tgt = R(a)
            if ins.jumps and not (self.cur_dense and 'add pc' in ins.text):
                cases = ' '.join('case 0x%08xu: goto L_%08x;' % (j & ~1, j & ~1) for j in sorted(set(ins.jumps)) if any(i.addr == (j & ~1) for i in fn.insns))
                return '    switch ((%s) & ~1u) { %s default: rt_call(c, %s); return; }' % (tgt, cases, tgt), True
            if self.cur_dense:
                # unresolved computed jump: it may land on any instruction of this function
                cases = ' '.join('case 0x%08xu: goto L_%08x;' % (i.addr, i.addr) for i in fn.insns)
                return '    { uint32_t _t = (%s) & ~1u; switch (_t) { %s default: rt_call(c, _t); return; } }' % (tgt, cases), True
            return '    { rt_call(c, %s); return; }' % tgt, True
        if opc == 'CALLOTHER':
            name = self.userops.get(a.off, 'op%d' % a.off)
            args = [R(x) for x in inp[1:]]
            return self.emit_userop(name, a.off, out, args, locals_, ins, flush)
        # ---- arithmetic
        if opc == 'INT_ADD': return assign('%s + %s' % (R(a), R(b))), False
        if opc == 'INT_SUB': return assign('%s - %s' % (R(a), R(b))), False
        if opc == 'INT_MULT': return assign('(%s)%s * (%s)%s' % (T(out), R(a), T(out), R(b))), False
        if opc == 'INT_DIV': return assign('%s ? %s / %s : 0' % (R(b), R(a), R(b))), False
        if opc == 'INT_SDIV': return assign('%s ? (%s)%s / (%s)%s : 0' % (R(b), S(a), R(a), S(b), R(b))), False
        if opc == 'INT_REM': return assign('%s ? %s %% %s : 0' % (R(b), R(a), R(b))), False
        if opc == 'INT_SREM': return assign('%s ? (%s)%s %% (%s)%s : 0' % (R(b), S(a), R(a), S(b), R(b))), False
        if opc == 'INT_AND': return assign('%s & %s' % (R(a), R(b))), False
        if opc == 'INT_OR': return assign('%s | %s' % (R(a), R(b))), False
        if opc == 'INT_XOR': return assign('%s ^ %s' % (R(a), R(b))), False
        if opc == 'INT_NEGATE': return assign('~%s' % R(a)), False
        if opc == 'INT_2COMP': return assign('-(%s)%s' % (T(a), R(a))), False
        if opc == 'INT_ZEXT': return assign('(%s)%s' % (T(a), R(a))), False
        if opc == 'INT_SEXT': return assign('(%s)(%s)%s' % (S(out), S(a), R(a))), False
        if opc == 'INT_LEFT': return assign('shl64((uint64_t)%s, (uint64_t)%s)' % (R(a), R(b))) if a.size < 8 or True else None, False
        if opc == 'INT_RIGHT': return assign('shr64((uint64_t)(%s)%s, (uint64_t)%s)' % (T(a), R(a), R(b))), False
        if opc == 'INT_SRIGHT': return assign('sar64((int64_t)(%s)%s, (uint64_t)%s)' % (S(a), R(a), R(b))), False
        if opc == 'INT_EQUAL': return assign('%s == %s' % (R(a), R(b))), False
        if opc == 'INT_NOTEQUAL': return assign('%s != %s' % (R(a), R(b))), False
        if opc == 'INT_LESS': return assign('(%s)%s < (%s)%s' % (T(a), R(a), T(b), R(b))), False
        if opc == 'INT_LESSEQUAL': return assign('(%s)%s <= (%s)%s' % (T(a), R(a), T(b), R(b))), False
        if opc == 'INT_SLESS': return assign('(%s)%s < (%s)%s' % (S(a), R(a), S(b), R(b))), False
        if opc == 'INT_SLESSEQUAL': return assign('(%s)%s <= (%s)%s' % (S(a), R(a), S(b), R(b))), False
        if opc == 'INT_CARRY':
            return assign('(%s)((%s)%s + (%s)%s) < (%s)%s' % (T(a), T(a), R(a), T(a), R(b), T(a), R(a))), False
        if opc == 'INT_SCARRY':
            return assign('({ %s _x = %s, _y = %s, _r = (%s)(_x + _y); (((_x ^ _r) & (_y ^ _r)) >> %d) & 1; })'
                          % (T(a), R(a), R(b), T(a), bits(a) - 1)), False
        if opc == 'INT_SBORROW':
            return assign('({ %s _x = %s, _y = %s, _r = (%s)(_x - _y); (((_x ^ _y) & (_x ^ _r)) >> %d) & 1; })'
                          % (T(a), R(a), R(b), T(a), bits(a) - 1)), False
        if opc == 'BOOL_NEGATE': return assign('!%s' % R(a)), False
        if opc == 'BOOL_AND': return assign('%s && %s' % (R(a), R(b))), False
        if opc == 'BOOL_OR': return assign('%s || %s' % (R(a), R(b))), False
        if opc == 'BOOL_XOR': return assign('(!!%s) ^ (!!%s)' % (R(a), R(b))), False
        if opc == 'SUBPIECE':
            return assign('(uint64_t)%s >> %d' % (R(a), 8 * b.off)), False
        if opc == 'PIECE':
            return assign('((uint64_t)%s << %d) | (uint64_t)%s' % (R(a), bits(b), R(b))), False
        if opc == 'POPCOUNT': return assign('__builtin_popcountll((uint64_t)%s)' % R(a)), False
        if opc == 'LZCOUNT':
            return assign('%s ? __builtin_clzll((uint64_t)%s) - %d : %d' % (R(a), R(a), 64 - bits(a), bits(a))), False
        self.unknown_ops[opc] += 1
        return '    rt_missing(c, 0x%08xu, "pcode %s");' % (ins.addr, opc), False

    def emit_userop(self, name, idx, out, args, locals_, ins, flush):
        pad = args + ['0'] * (4 - len(args))
        if name == 'software_interrupt':
            flush()
            return '    rt_swi(c, %s, 0x%08xu);' % (args[0], ins.addr), False
        if name == 'count_leading_zeroes':
            return '    %s = clz32(%s);' % (self.wr(out, locals_), args[0]), False
        if name in ('setISAMode', 'ISB', 'DSB', 'DMB', 'HintPreloadData', 'HintPreloadDataForWrite', 'HintPreloadInstruction'):
            return None, False
        call = 'rt_userop(c, %d, %s, %s, %s, %s, 0x%08xu)' % (idx, pad[0], pad[1], pad[2], pad[3], ins.addr)
        if out is not None:
            locals_[('u' if out.space == 'u' else 'reg', out.off if out.space == 'u' else self.regname(out), out.size)] = 1
            flush()
            return '    %s = (%s)rt_userop_ret(c);' % (self.wr(out, locals_), CTYPE.get(out.size, 'uint32_t')) if False else \
                   ['    %s;' % call, '    %s = (%s)c->ret;' % (self.wr(out, locals_), CTYPE.get(out.size, 'uint32_t'))], False
        flush()
        return '    %s;' % call, False


def main():
    src, outdir = sys.argv[1], sys.argv[2]
    per_file = 150
    if '--per-file' in sys.argv:
        per_file = int(sys.argv[sys.argv.index('--per-file') + 1])
    regs, userops, funcs = parse(src)
    funcs = [f for f in funcs if f.insns]
    # A function that ends in `add pc, pc, rX ...` jumps into code right after it (unrolled loops,
    # jump tables) which Ghidra split into separate functions: emit that code as part of it too.
    by_space_sorted = collections.defaultdict(list)
    for f in funcs:
        by_space_sorted[f.space].append(f)
    merged = 0
    merged_entries = []
    for sp, lst in by_space_sorted.items():
        lst.sort(key=lambda f: f.entry)
        for i, f in enumerate(lst):
            last = max(f.insns, key=lambda x: x.addr)
            if 'add pc,pc' in last.text and any(o[0] == 'BRANCHIND' for o in last.ops):
                end = last.addr + last.length
                for g in lst[i + 1:i + 4]:
                    if g.entry > end + 8:
                        break
                    merged_entries.append(g.entry)
                    f.insns = f.insns + [x for x in g.insns if not f.contains(x.addr)]
                    f.ranges = f.ranges + g.ranges
                    end = max(x.addr + x.length for x in g.insns)
                    merged += 1
    if merged:
        print('merged %d jump-table continuations' % merged)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, 'merged_entries.txt'), 'w').write(''.join('%08x\n' % e for e in merged_entries))
    em = Emitter(regs, userops, funcs)
    extra = []  # (containing function, address)
    if '--extra-entries' in sys.argv:
        path = sys.argv[sys.argv.index('--extra-entries') + 1]
        static_fns = [f for f in funcs if f.space == 'ram']
        entries = {f.entry for f in static_fns}
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            a = int(line, 16)
            if a in entries:
                continue
            for f in static_fns:
                if f.contains(a) and any(i.addr == a for i in f.insns):
                    extra.append((f, a))
                    break
        print('extra entry points:', len(extra))
    # Direct branches/calls that land in the middle of another function (shared tails, multiple
    # entry points) also need secondary entry points.
    import bisect
    have = {(f.space, f.entry) for f in funcs} | {(f.space, a) for f, a in extra}
    spans = collections.defaultdict(list)
    for f in funcs:
        for s0, e0 in f.ranges:
            spans[f.space].append((s0, e0, f))
    for sp in spans:
        spans[sp].sort(key=lambda t: t[0])
    starts = {sp: [t[0] for t in v] for sp, v in spans.items()}
    auto = 0
    for f in funcs:
        for ins in f.insns:
            for opc, out, inp in ins.ops:
                if opc not in ('BRANCH', 'CBRANCH', 'CALL') or not inp or inp[0].space not in ('m', 'o'):
                    continue
                t = inp[0].off
                if opc != 'CALL' and f.contains(t):
                    continue
                sp = f.space if inp[0].space == 'o' else 'ram'
                if (sp, t) in have or sp not in spans:
                    continue
                i = bisect.bisect_right(starts[sp], t) - 1
                while i >= 0:
                    s0, e0, g = spans[sp][i]
                    if s0 <= t < e0:
                        if any(x.addr == t for x in g.insns):
                            extra.append((g, t))
                            have.add((sp, t))
                            auto += 1
                        break
                    if t - s0 > 0x10000:
                        break
                    i -= 1
    print('automatic mid-function entry points:', auto)
    os.makedirs(outdir, exist_ok=True)
    hdr = ['/* generated by pcode2c.py - do not edit */', '#pragma once', '#include "recomp.h"']
    for fn in funcs:
        hdr.append('void %s(Cpu* c);' % fn.cname)
    for fn, a in extra:
        hdr.append('void f_%s_%08x(Cpu* c);' % (fn.space, a))
    # hand-written assembly regions (movie decoder, ITCM overlay 0): multi-entry variants
    multi_fns = [f for f in funcs if image_of(f) in ('ov200', 'itcm0')]
    for fn in multi_fns:
        hdr.append('void %s_m(Cpu* c, uint32_t at);' % fn.cname)
    for name in sorted(set(OVERRIDES.values())):
        hdr.append('void %s(Cpu* c);' % name)
    hdr.append('uint32_t rt_cp15_read(Cpu* c, uint32_t id);')
    hdr.append('void rt_msr_cpsr(Cpu* c, uint32_t val, uint32_t mask);')
    hdr.append('void rt_cp15_write(Cpu* c, uint32_t id, uint32_t val, uint32_t at);')
    open(os.path.join(outdir, 'funcs.h'), 'w').write('\n'.join(hdr) + '\n')
    nfiles = 0
    for i in range(0, len(funcs), per_file):
        chunk = funcs[i:i + per_file]
        body = ['/* generated by pcode2c.py - do not edit */', '#include "funcs.h"',
                '#pragma GCC diagnostic ignored "-Wunused-label"', '#pragma GCC diagnostic ignored "-Wunused-variable"',
                '#pragma GCC diagnostic ignored "-Wunused-but-set-variable"', '']
        for fn in chunk:
            body.append(em.emit_function(fn))
            body.append('')
        open(os.path.join(outdir, 'funcs_%03d.c' % nfiles), 'w').write('\n'.join(body))
        nfiles += 1
    if extra:
        body = ['/* generated by pcode2c.py - do not edit */', '#include "funcs.h"',
                '#pragma GCC diagnostic ignored "-Wunused-label"', '']
        for fn, a in extra:
            body.append(em.emit_function(fn, alt_entry=a))
            body.append('')
        open(os.path.join(outdir, 'funcs_%03d.c' % nfiles), 'w').write('\n'.join(body))
        nfiles += 1
    if multi_fns:
        body = ['/* generated by pcode2c.py - do not edit */', '#include "funcs.h"',
                '#pragma GCC diagnostic ignored "-Wunused-label"', '']
        for fn in multi_fns:
            body.append(em.emit_function(fn, multi=True))
            body.append('')
        open(os.path.join(outdir, 'funcs_%03d.c' % nfiles), 'w').write('\n'.join(body))
        nfiles += 1
    # dispatch table: (space, address, thumb, fn)
    # Overlays share load addresses and often start with identical prologues, so overlay entries
    # carry up to 256 bytes of the function's original code; the dispatcher compares them with RAM.
    ov_images = {}
    ovdir = sys.argv[sys.argv.index('--overlay-dir') + 1] if '--overlay-dir' in sys.argv else None
    if ovdir:
        for fname in os.listdir(ovdir):
            if fname.startswith('ov') and fname.endswith('.bin'):
                ov_images[int(fname[2:5])] = (int(fname[6:14], 16), open(os.path.join(ovdir, fname), 'rb').read())
    bodies = []
    body_names = {}

    def body_ref(fn, start, sp):
        if (fn.space, start) in body_names:
            return body_names[(fn.space, start)]
        if sp < 0 or sp not in ov_images:
            return 'NULL, 0'
        base, img = ov_images[sp]
        end = start
        for s0, e0 in fn.ranges:
            if s0 <= start < e0:
                end = e0
        end = min(end, start + 256)
        data = img[start - base:end - base]
        if not data:
            return 'NULL, 0'
        name = 'B_%s_%08x' % (fn.space, start)
        bodies.append('static const uint8_t %s[%d] = {%s};' % (name, len(data), ','.join(str(x) for x in data)))
        body_names[(fn.space, start)] = '%s, %d' % (name, len(data))
        return body_names[(fn.space, start)]

    spaces = sorted({f.space for f in funcs})
    tab = ['/* generated by pcode2c.py - do not edit */', '#include "funcs.h"', '#include "../runtime/table.h"', '']
    rows = []
    for fn in sorted(funcs, key=lambda f: (f.space, f.entry)):
        sp = overlay_id(fn, fn.entry)
        raw = b''.join(i.raw for i in sorted(fn.insns, key=lambda i: i.addr) if i.addr >= fn.entry)[:8].ljust(8, bytes(1))
        sig0, sig1 = int.from_bytes(raw[:4], 'little'), int.from_bytes(raw[4:8], 'little')
        name = OVERRIDES.get(fn.entry, fn.cname) if fn.space == 'ram' else fn.cname
        rows.append('    {0x%08xu, %d, %d, %s, {0x%08xu, 0x%08xu}, %s},' % (fn.entry, sp, int(fn.thumb), name, sig0, sig1, body_ref(fn, fn.entry, sp)))
    for fn, a in extra:
        sp = overlay_id(fn, a)
        raw = b''.join(i.raw for i in sorted(fn.insns, key=lambda i: i.addr) if i.addr >= a)[:8].ljust(8, bytes(1))
        sig0, sig1 = int.from_bytes(raw[:4], 'little'), int.from_bytes(raw[4:8], 'little')
        rows.append('    {0x%08xu, %d, %d, f_%s_%08x, {0x%08xu, 0x%08xu}, %s},' % (a, sp, int(fn.thumb), fn.space, a, sig0, sig1, body_ref(fn, a, sp)))
    tab += bodies + ['', 'const GuestFnEntry g_guest_fns[] = {'] + rows
    tab.append('};')
    tab.append('const unsigned g_guest_fn_count = %d;' % (len(funcs) + len(extra)))
    tab.append('const unsigned g_guest_primary_count = %d;  /* entries before this index are Ghidra function starts */' % len(funcs))
    # code ranges with multi-entry variants: the runtime uses them for jumps into the middle of a function
    rr = []
    for fn in multi_fns:
        sp = overlay_id(fn, fn.entry)
        ref = body_ref(fn, fn.entry, sp)
        for s0, e0 in fn.ranges:
            rr.append('    {0x%08xu, 0x%08xu, 0x%08xu, %d, %s_m, %s},' % (s0, e0, fn.entry, sp, fn.cname, ref))
    tab.append('const GuestRange g_guest_ranges[] = {')
    tab += rr or ['    {0, 0, 0, 0, 0, NULL, 0},']
    tab.append('};')
    tab.append('const unsigned g_guest_range_count = %d;' % len(rr))
    open(os.path.join(outdir, 'table.c'), 'w').write('\n'.join(tab) + '\n')
    print('functions', len(funcs), 'files', nfiles, 'spaces', spaces[:5], '...')
    if em.unknown_ops:
        print('unhandled p-code ops:', dict(em.unknown_ops))
    used = collections.Counter()
    for fn in funcs:
        for ins in fn.insns:
            for opc, out, inp in ins.ops:
                if opc == 'CALLOTHER':
                    used[userops.get(inp[0].off, inp[0].off)] += 1
    print('userops used:', dict(used))


if __name__ == '__main__':
    main()
