"""Find Thumb switch tables whose targets Ghidra never disassembled.

The game's compiler emits switches as
    add r0,r0,r0 ; add r0,pc ; ldrh r0,[r0,#k] ; lsl r0,r0,#16 ; asr r0,r0,#16 ; add pc,r0
followed by a table of signed halfword offsets from the `add pc` (pc = its address + 4).
Ghidra does not always recover these, so the case blocks are missing from the generated C and
the game falls into the interpreter (and can crash) when it takes one of those cases.

usage: python tools/find_switch_tables.py [--out work/switch_seeds.txt]
Writes "space address" lines for every missing target (space: ram or ovNNN), for
tools/ghidra_scripts/SeedSwitchTargets.java.
"""
import collections, glob, os, re, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_pcode(path):
    """space -> {addr: (length, thumb)} for every decoded instruction."""
    insns = collections.defaultdict(dict)
    space = 'ram'
    with open(path, errors='replace') as f:
        for line in f:
            if line.startswith('F '):
                space = line.split()[3]
            elif line.startswith('I '):
                p = line.split(None, 4)
                insns[space][int(p[1], 16)] = (int(p[2]), p[3] == '1')
    return insns


def images():
    out = {'ram': (0x02000000, open(os.path.join(ROOT, 'extracted', 'arm9_dec.bin'), 'rb').read())}
    for p in glob.glob(os.path.join(ROOT, 'extracted', 'overlay_dec', 'ov*.bin')):
        n = os.path.basename(p)
        out['ov%03d' % int(n[2:5])] = (int(n[6:14], 16), open(p, 'rb').read())
    return out


def main():
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else os.path.join(ROOT, 'work', 'switch_seeds.txt')
    insns = load_pcode(os.path.join(ROOT, 'work', 'pcode_full.txt'))
    imgs = images()
    missing, tables, missing_tables = [], 0, 0
    for space, (base, img) in sorted(imgs.items()):
        dec = insns.get(space, {})
        if space == 'ov000':
            dec = {**dec, **insns.get('ram', {})}  # ITCM overlay 0 is exported in the ram space
        for a, (ln, thumb) in sorted(dec.items()):
            if not thumb or ln != 2 or not (base <= a < base + len(img) - 2):
                continue
            x = struct.unpack_from('<H', img, a - base)[0]
            if (x & 0xFF87) != 0x4487:  # add pc, Rm
                continue
            # an ldrh/ldrsh of the table a few instructions before
            window = [struct.unpack_from('<H', img, b - base)[0] for b in range(max(base, a - 10), a, 2)]
            if not any((w >> 11) == 0x11 or (w & 0xFE00) == 0x5E00 or (w & 0xFE00) == 0x5A00 for w in window):
                continue
            tables += 1
            # entry count from a `cmp rN,#imm` bound check just before, when there is one
            limit = 512
            for b in range(a - 2, max(base, a - 16) - 2, -2):
                w = struct.unpack_from('<H', img, b - base)[0]
                if (w >> 11) == 0x05:  # cmp rN,#imm
                    limit = (w & 0xFF) + 1
                    break
            pc = a + 4
            entries, k, end = [], 0, None
            while True:
                t_addr = a + 2 + 2 * k
                if end is not None and t_addr >= end or t_addr + 2 > base + len(img) or k >= limit:
                    break
                off = struct.unpack_from('<h', img, t_addr - base)[0]
                tgt = pc + off
                if tgt & 1 or not (base <= tgt < base + len(img)) or tgt <= t_addr:
                    break
                entries.append(tgt)
                end = tgt if end is None else min(end, tgt)
                k += 1
            # without a bound, a table can seem to run on into the code after it: such "entries" point far away
            miss = sorted({t for t in entries if t not in dec and (limit < 512 or abs(t - a) < 0x1000)})
            if miss:
                missing_tables += 1
                missing += [(space, t, a) for t in miss]
    with open(out, 'w') as f:
        for space, t, site in missing:
            f.write('%s %08x %08x\n' % (space, t, site))
    print('thumb switch tables: %d, with undecoded targets: %d, missing targets: %d -> %s' % (
        tables, missing_tables, len(missing), out))


if __name__ == '__main__':
    main()
