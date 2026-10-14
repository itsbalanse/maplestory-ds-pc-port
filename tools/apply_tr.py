"""Merge translation batch files ({"<japanese>": "<english>", ...}) into translation/strings/*.json.

usage: python tools/apply_tr.py translation/batches/*.json
"""
import os, sys, json, glob
sys.path.insert(0, os.path.dirname(__file__))
from textdb import TRANS

def main(paths):
    m = {}
    for p in paths:
        for f in glob.glob(p):
            m.update(json.load(open(f, encoding='utf-8')))
    sdir = os.path.join(TRANS, 'strings')
    hit = set()
    for f in sorted(os.listdir(sdir)):
        fp = os.path.join(sdir, f)
        ents = json.load(open(fp, encoding='utf-8'))
        changed = False
        for e in ents:
            if e['jp'] in m and e.get('en') != m[e['jp']]:
                e['en'] = m[e['jp']]; changed = True
            if e['jp'] in m:
                hit.add(e['jp'])
        if changed:
            json.dump(ents, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    missing = [k for k in m if k not in hit]
    print('applied', len(hit), 'of', len(m), 'entries')
    for k in missing[:20]:
        print('  no match:', repr(k[:60]))

if __name__ == '__main__':
    main(sys.argv[1:])
