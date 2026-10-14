"""Export every unique Japanese string to translation/strings/*.json.

Each unique Japanese string appears once, in the file of its first occurrence.
Existing English translations are preserved when re-exporting.
Entry fields:
  jp    - original text (do not edit)
  en    - English translation (fill this in)
  ctx   - first location "<table>:<key>"
  rule  - layout rule name (see textdb.RULES) -> width in px / max lines
  n     - number of places this string is used
"""
import os, sys, json, collections
sys.path.insert(0, os.path.dirname(__file__))
from textdb import iter_tables, parse_gmm, category, has_jp, RULES, TRANS, load_translations

def group_name(container, inner):
    base = (inner or container.split('/')[-1]).upper()
    if base.startswith('MP') and len(base) >= 8:
        return 'stage_' + base[2:8]
    if base.startswith('MO'):
        return 'mapnames'
    for suf in ('.GMM.JAPANESE', 'GMMJAPANESE'):
        if base.endswith(suf):
            base = base[:-len(suf)]
    return 'global_' + base.lower().replace('.', '_')

def main():
    old, _ = load_translations()
    seen = {}
    groups = collections.OrderedDict()
    counts = collections.Counter()
    for container, inner, blob in iter_tables():
        cat = category(container, inner)
        g = group_name(container, inner)
        for key, text in parse_gmm(blob):
            if not text.strip() or not has_jp(text):
                continue
            counts[text] += 1
            if text in seen:
                continue
            e = {'jp': text, 'en': old.get(text, ''), 'ctx': '%s:%s' % ((inner or container.split('/')[-1]), key), 'rule': cat}
            if text.startswith('★') or 'memo' in text.lower():
                e['dev'] = True
            seen[text] = e
            groups.setdefault(g, []).append(e)
    os.makedirs(os.path.join(TRANS, 'strings'), exist_ok=True)
    total = 0
    for g, ents in groups.items():
        for e in ents:
            e['n'] = counts[e['jp']]
        json.dump(ents, open(os.path.join(TRANS, 'strings', g + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        total += len(ents)
    print('groups', len(groups), 'unique strings', total, 'already translated', sum(1 for e in seen.values() if e['en']))

if __name__ == '__main__':
    main()
