"""Build hook: turn the English graphics in translation/gfx/ into archive replacements.

translation/gfx/<entry>_cNN.png  -> cell NN of cell set <entry> (e.g. OUT/UI_CSS4_c00.png)
translation/gfx/<entry>.png      -> whole BG screen <entry>.NSCR (e.g. IN/RES/BG/BG8109.png)

gfx_replacements() returns {archive entry name: bytes} for build_english.py.
python tools/gfx_patch.py  imports everything and prints what changed (dry run).
"""
import os, re, sys, glob
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from gfx import NX, ROOT, find_palette, ncer_charfile, load, entry_name
from gfx_import import import_cells, import_bg

GFX_DIR = os.path.join(ROOT, 'translation', 'gfx')


def collect():
    cells, bgs = {}, {}
    for p in glob.glob(os.path.join(GFX_DIR, '**', '*.png'), recursive=True):
        rel = os.path.relpath(p, GFX_DIR).replace(os.sep, '/')[:-4]
        m = re.match(r'(.*)_c(\d+)$', rel)
        if m and os.path.exists(os.path.join(NX, m.group(1) + '.NCER')):
            cells.setdefault(m.group(1), {})[int(m.group(2))] = p
        elif os.path.exists(os.path.join(NX, rel + '.NSCR')):
            bgs[rel] = p
    return cells, bgs


def gfx_replacements(verbose=False):
    repl = {}
    cells, bgs = collect()
    for entry, files in sorted(cells.items()):
        ncer = os.path.join(NX, entry + '.NCER')
        chf, pal = ncer_charfile(ncer), find_palette(ncer)
        edits = {}
        for i, p in files.items():
            im = Image.open(p)
            im.load()
            info = dict(im.info)
            im = im.convert('RGBA'); im.info.update(info)
            edits[i] = im
        ne, nc, log = import_cells(load(ncer), load(chf), load(pal), edits)
        repl[entry + '.NCER'] = ne
        repl[entry_name(chf)] = nc
        if verbose:
            print('%-28s %2d cells %s' % (entry, len(files), '; '.join(log)))
    for entry, p in sorted(bgs.items()):
        base = os.path.join(NX, entry)
        ns, ng, log = import_bg(load(base + '.NSCR'), load(base + '.NCGR'), load(find_palette(base + '.NSCR')),
                                Image.open(p).convert('RGBA'))
        repl[entry + '.NSCR'] = ns
        repl[entry + '.NCGR'] = ng
        if verbose:
            print('%-28s BG %s' % (entry, '; '.join(log)))
    return repl


if __name__ == '__main__':
    r = gfx_replacements(verbose=True)
    print(len(r), 'archive entries replaced')
