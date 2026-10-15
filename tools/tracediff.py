"""Compare function-entry traces from the interpreter and the recompiled build.

usage: python tools/tracediff.py interp.trace recomp.trace [--limit N] [--hunks K] [--keys addr,lr]

Records: addr, r0..r3, sp, lr, cpu mode (8 x u32). IRQ-mode records are ignored because
interrupts land at different points in the two runs, and short polling loops are collapsed.
After a mismatch the tool resynchronises on the next run of matching records, so differences
that only come from timing (a flag read before/after an interrupt) don't hide later problems.
A hunk is reported as a control-flow divergence when the two sides ran different functions.
"""
import sys
import numpy as np

DT = np.dtype([('addr', '<u4'), ('r0', '<u4'), ('r1', '<u4'), ('r2', '<u4'), ('r3', '<u4'),
               ('sp', '<u4'), ('lr', '<u4'), ('mode', '<u4')])
FIELDS = ('addr', 'r0', 'r1', 'r2', 'r3', 'sp', 'lr')
KEYS = list(range(len(FIELDS)))  # fields compared (--keys addr,lr: control flow only)


def key(r):
    return tuple(r[k] for k in KEYS)


def collapse_loops(keys, maxlen=6):
    """Remove repeats of short call cycles (polling loops whose iteration count depends on timing)."""
    keep = []
    i, n = 0, len(keys)
    while i < n:
        for L in range(1, maxlen + 1):
            if len(keep) >= L and i + L <= n and keys[i:i + L] == [keys[j] for j in keep[-L:]]:
                i += L
                break
        else:
            keep.append(i)
            i += 1
    return keep


def load(path, limit):
    t = np.fromfile(path, dtype=DT, count=limit)
    t = t[(t['mode'] == 0x1F) | (t['mode'] == 0x10)]
    # calls made from inside runtime-overridden functions (OS_LoadContext) are not comparable
    t = t[~((t['lr'] >= 0x020c3b44) & (t['lr'] < 0x020c3b88))]
    import os
    mp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'gen', 'merged_entries.txt')
    if os.path.exists(mp):
        merged = np.array([int(x, 16) for x in open(mp).read().split()], dtype=np.uint32)
        t = t[~np.isin(t['addr'], merged)]
    if START:
        idx = np.flatnonzero((t['addr'] == START[0]) & (t['lr'] == START[1]))
        if len(idx):
            t = t[int(idx[0]):]
    # a loop whose back-edge targets the function entry looks like repeated entries: keep the first
    if len(t) > 1:
        same = (t['addr'][1:] == t['addr'][:-1]) & (t['lr'][1:] == t['lr'][:-1]) & (t['sp'][1:] == t['sp'][:-1])
        t = t[np.concatenate([[True], ~same])]
    rows = [tuple(int(r[k]) for k in FIELDS) for r in t]
    # magic runtime addresses (>= 0xF0000000) stand in for BIOS/thread addresses: normalise
    rows = [tuple(0xF0000000 if v >= 0xF0000000 else v for v in r) for r in rows]
    keep = collapse_loops([key(r) for r in rows])
    return [rows[i] for i in keep]


def fmt(r):
    return 'fn %08x r0=%08x r1=%08x r2=%08x r3=%08x sp=%08x lr=%08x' % r


def resync(a, b, i, j, window=400, need=4):
    best = None
    for d in range(1, window):
        for di in range(0, d + 1):
            dj = d - di
            ii, jj = i + di, j + dj
            if ii + need > len(a) or jj + need > len(b):
                continue
            if all(key(a[ii + k]) == key(b[jj + k]) for k in range(need)):
                return ii, jj
    return best


START = None
STRICT = False


def main():
    global START, STRICT, KEYS
    if '--keys' in sys.argv:  # e.g. --keys addr,lr when arguments legitimately differ (test hooks)
        KEYS = [FIELDS.index(k) for k in sys.argv[sys.argv.index('--keys') + 1].split(',')]
    STRICT = '--strict' in sys.argv  # also report the first hunk that differs only in arguments
    if '--from' in sys.argv:  # --from ADDR:LR  start both traces at the first call of ADDR from LR
        f, l = sys.argv[sys.argv.index('--from') + 1].split(':')
        START = (int(f, 16), int(l, 16))
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 2000000
    max_hunks = int(sys.argv[sys.argv.index('--hunks') + 1]) if '--hunks' in sys.argv else 3
    a, b = load(sys.argv[1], limit), load(sys.argv[2], limit)
    print('records after filtering: interp=%d recomp=%d' % (len(a), len(b)))
    i = j = 0
    timing_hunks = 0
    shown = 0
    while i < len(a) and j < len(b):
        if key(a[i]) == key(b[j]):
            i += 1; j += 1
            continue
        r = resync(a, b, i, j)
        if r is None:
            print('\nno resync after interp record %d / recomp record %d:' % (i, j))
            for k in range(max(0, i - 6), min(len(a), i + 6)):
                print('   I', '>>' if k == i else '  ', fmt(a[k]))
            for k in range(max(0, j - 6), min(len(b), j + 6)):
                print('   R', '>>' if k == j else '  ', fmt(b[k]))
            return
        ii, jj = r
        fa = {x[0] for x in a[i:ii]}
        fb = {x[0] for x in b[j:jj]}
        if fa != fb or (STRICT and shown == 0):
            shown += 1
            print('\ncontrol-flow divergence #%d at interp %d / recomp %d' % (shown, i, j))
            print('   only in interp:', ' '.join('%08x' % x for x in sorted(fa - fb)))
            print('   only in recomp:', ' '.join('%08x' % x for x in sorted(fb - fa)))
            for k in range(max(0, i - 4), min(ii + 1, i + 12)):
                print('   I', '>>' if k == i else '  ', fmt(a[k]))
            for k in range(max(0, j - 4), min(jj + 1, j + 12)):
                print('   R', '>>' if k == j else '  ', fmt(b[k]))
            if shown >= max_hunks:
                return
        else:
            timing_hunks += 1
        i, j = ii, jj
    print('\ncompared to interp %d / recomp %d; timing-only differences: %d' % (i, j, timing_hunks))


if __name__ == '__main__':
    main()
