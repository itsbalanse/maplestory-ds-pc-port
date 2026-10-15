"""Compare per-instruction traces of the movie decoder (MSDS_ITRACE) from the interpreter and from
native code built with -DMSDS_IMG_STEP=ON, and print the first instruction whose results differ.

usage: python tools/itracediff.py interp.itrace native.itrace [--context N]

Each record is the state *before* an instruction: pc, r0-r14, NZCV. When record i matches but
record i+1 does not, the instruction at record i computed something different.
"""
import sys
import numpy as np

DT = np.dtype([('pc', '<u4'), ('r', '<u4', 15), ('nzcv', '<u4')])


def show(tag, rec):
    regs = ' '.join('r%d=%08x' % (k, v) for k, v in enumerate(rec['r']))
    print('  %s pc=%08x %s nzcv=%x' % (tag, rec['pc'], regs, rec['nzcv']))


def main():
    a, b = np.fromfile(sys.argv[1], dtype=DT), np.fromfile(sys.argv[2], dtype=DT)
    ctx = int(sys.argv[sys.argv.index('--context') + 1]) if '--context' in sys.argv else 3
    n = min(len(a), len(b))
    print('records: %d vs %d' % (len(a), len(b)))
    diff = (a['pc'][:n] != b['pc'][:n]) | (a['r'][:n] != b['r'][:n]).any(axis=1)
    idx = np.flatnonzero(diff)
    if not len(idx):
        print('no difference in the first %d instructions' % n)
        return
    i = int(idx[0])
    print('first difference at record %d' % i)
    for j in range(max(0, i - ctx), min(n, i + 2)):
        print('#%d' % j)
        show('A', a[j])
        if (a[j]['pc'] != b[j]['pc']) or (a[j]['r'] != b[j]['r']).any() or a[j]['nzcv'] != b[j]['nzcv']:
            show('B', b[j])
            regs = [k for k in range(15) if a[j]['r'][k] != b[j]['r'][k]]
            print('    differs: %s%s' % ('pc ' if a[j]['pc'] != b[j]['pc'] else '', ' '.join('r%d' % k for k in regs)))
    if i:
        print('suspect instruction: %08x (state before it matched, state after it differs)' % a[i - 1]['pc'])


if __name__ == '__main__':
    main()
