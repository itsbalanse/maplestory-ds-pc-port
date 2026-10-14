"""Scan extracted NXARC tree for message tables, recursing into NARCs."""
import os, sys, json, struct, collections
sys.path.insert(0, os.path.dirname(__file__))
from gmm import parse_gmm, looks_like_gmm
from narc import parse_narc

ROOT = sys.argv[1]
stats = collections.Counter()
other_jp = []
records = []  # (container path, inner name, key, text)

def has_jp(t):
    return any('\u3000' <= c <= '\u9fff' or '\uff00' <= c <= '\uffef' for c in t)

def scan_utf16(d):
    # count UTF-16LE hiragana/katakana code units
    n = 0
    for i in range(0, len(d)-1, 2):
        if d[i+1] == 0x30 or (0x4e <= d[i+1] <= 0x9f): n += 1
    return n

def visit(path, d, depth=0):
    if d[:4] == b'NARC':
        names, files, _ = parse_narc(d)
        for i, f in enumerate(files):
            visit(path + '#' + (names[i] or str(i)), f, depth+1)
        return
    if looks_like_gmm(d):
        ents = parse_gmm(d)
        stats['gmm'] += 1
        for k, t in ents:
            records.append((path, k, t))
        return
    # check sjis/utf16 presence
    try:
        s = d.decode('shift_jis')
        jp = sum(1 for c in s if '\u3040' <= c <= '\u30ff')
        if jp > 4: other_jp.append((path, 'sjis', jp))
    except Exception:
        pass
    u = scan_utf16(d)
    if u > 20: other_jp.append((path, 'utf16?', u))

for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        if f.split('.')[-1] in ('NCLR','NCER','NCBR','NANR','NCGR','NSCR','NXATARI'): continue
        p = os.path.join(dp, f)
        visit(os.path.relpath(p, ROOT).replace(os.sep, '/'), open(p,'rb').read())

jp = [r for r in records if has_jp(r[2])]
print('gmm tables', stats['gmm'], 'entries', len(records), 'with JP', len(jp), 'chars', sum(len(r[2]) for r in jp))
uniq = set(r[2] for r in jp); print('unique JP strings', len(uniq), 'chars', sum(len(s) for s in uniq))
by = collections.Counter(r[0].split('#')[0] for r in jp)
for k, v in by.most_common(40): print(v, k)
print('--- other files with JP-looking text')
for o in other_jp[:60]: print(o)
json.dump(records, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
