"""Compare interpreter/recompiled traces from the first movie-decoder call (debug helper)."""
import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
import tracediff as T, numpy as np
a = np.fromfile(sys.argv[1], dtype=T.DT); b = np.fromfile(sys.argv[2], dtype=T.DT)
def start(t):
    idx = np.flatnonzero((t['addr'] == 0x1ff8500) & (t['lr'] == 0x020b34ec))
    return int(idx[0]) if len(idx) else None
ia, ib = start(a), start(b)
n = int(sys.argv[3]) if len(sys.argv) > 3 else 200000
def ok(r):
    return r['mode'] in (0x1f, 0x10) and not (0x020c3b44 <= r['lr'] < 0x020c3b88)
ra = [tuple(int(r[x]) for x in T.FIELDS) for r in a[ia:ia + n] if ok(r)]
rb = [tuple(int(r[x]) for x in T.FIELDS) for r in b[ib:ib + n] if ok(r)]
for k, (x, y) in enumerate(zip(ra, rb)):
    if x != y:
        print('first difference after %d matching decoder records' % k)
        for j in range(max(0, k - 4), min(k + 4, len(ra), len(rb))):
            print('  I', T.fmt(ra[j])); print('  R', T.fmt(rb[j]))
        break
else:
    print('no difference in', min(len(ra), len(rb)), 'records')
