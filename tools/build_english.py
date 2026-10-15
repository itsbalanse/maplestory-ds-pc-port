"""Build the English ROM: inject translations, re-wrap to pixel widths, patch the font.

usage: python tools/build_english.py [--report]
output: build/MapleStory DS (English).nds  and build/layout_report.txt
"""
import os, sys, json, struct
sys.path.insert(0, os.path.dirname(__file__))
from textdb import (ROOT, NX, TRANS, RULES, NL, category, is_japanese_table, load_translations,
                    Wrapper, has_jp)
from gmm import parse_gmm, build_gmm, looks_like_gmm
from narc import parse_narc, build_narc
from nxarc import NxArc, rebuild_nxarc
from ndsfs import NDS
from ndsbuild import rebuild_rom
from render import Measurer

ROM_IN = os.path.join(ROOT, 'MapleStory DS (Japan).nds')
OUT_DIR = os.path.join(ROOT, 'build')
FONT_ENTRY = 'IN/RES/FONT/JAPANESENFTR'

# English-friendly spacing tweaks: char -> (left, glyph_width, char_width)
FONT_TWEAKS = {
    ' ': (0, 0, 3),
    '!': (0, 1, 1),
}

def patch_font(raw):
    sys.path.insert(0, os.path.dirname(__file__))
    from nftr import NFTR
    f = NFTR(raw)
    out = bytearray(raw)
    wp = f.cwdh_ptr - 8
    fi, li, _ = struct.unpack_from('<HHI', raw, wp + 8)
    for ch, (l, gw, cw) in FONT_TWEAKS.items():
        gi = f.cmap[ord(ch)]
        if fi <= gi <= li:
            o = wp + 16 + (gi - fi) * 3
            if ch == '!':
                l, gw, cw = (0, f.widths[gi][1], f.widths[gi][1])
            out[o:o + 3] = struct.pack('<bBB', l, gw, cw)
    # keycap / controller glyphs for the PC port's button prompts (unused on a DS)
    from promptfont import add_to_nftr
    return add_to_nftr(bytes(out))

class Builder:
    def __init__(self):
        self.tr, self.over = load_translations()
        self.font = patch_font(open(os.path.join(NX, FONT_ENTRY), 'rb').read())
        fp = os.path.join(OUT_DIR, '_font.tmp')
        os.makedirs(OUT_DIR, exist_ok=True)
        open(fp, 'wb').write(self.font)
        self.wrapper = Wrapper(Measurer(fp))
        self.report = []
        self.stats = {'replaced': 0, 'untranslated': 0}

    def english_for(self, table, key, jp, cat):
        en = self.over.get('%s:%s' % (table, key)) or self.tr.get(jp)
        if not en:
            if has_jp(jp):
                self.stats['untranslated'] += 1
            return None
        width, maxl = RULES.get(cat, RULES['DIALOG'])
        wrapped, nlines, overflow = self.wrapper.wrap(en, width)
        if (maxl and nlines > maxl) or overflow > 0:
            self.report.append('%s:%s [%s] lines=%d/%s overflow=%dpx :: %s' % (table, key, cat, nlines, maxl, overflow, en))
        self.stats['replaced'] += 1
        return wrapped

    def process_gmm(self, container, inner, blob):
        cat = category(container, inner)
        table = inner or container.split('/')[-1]
        ents = parse_gmm(blob)
        new = []
        changed = False
        for k, t in ents:
            en = self.english_for(table, k, t, cat) if t else None
            if en is not None and en != t:
                changed = True
                new.append((k, en))
            else:
                new.append((k, t))
        return build_gmm(new) if changed else None

    def run(self):
        arc = NxArc(os.path.join(ROOT, 'extracted', 'data', 'RESOURCE.NXARC'), os.path.join(ROOT, 'extracted', 'arm9_dec.bin'))
        repl = {FONT_ENTRY: self.font}
        for name, off, size in arc.entries:
            base = name.split('/')[-1]
            if base.split('.')[-1] in ('NCLR', 'NCER', 'NCBR', 'NANR', 'NCGR', 'NSCR', 'NXATARI'):
                continue
            d = arc.d[off:off + size]
            if d[:4] == b'NARC':
                names, files, fnt = parse_narc(d)
                changed = False
                for i, blob in enumerate(files):
                    nm = names[i] or str(i)
                    if is_japanese_table(nm) and looks_like_gmm(blob):
                        nb = self.process_gmm(name, nm, blob)
                        if nb is not None:
                            files[i] = nb; changed = True
                if changed:
                    repl[name] = build_narc(files, fnt)
            elif is_japanese_table(base) and looks_like_gmm(d):
                nb = self.process_gmm(name, None, d)
                if nb is not None:
                    repl[name] = nb
        from gfx_patch import gfx_replacements  # English graphics (translation/gfx)
        repl.update(gfx_replacements())
        new_arc = rebuild_nxarc(arc, repl)
        rom = NDS(ROM_IN)
        out = rebuild_rom(rom, {rom.files['RESOURCE.NXARC']: new_arc})
        op = os.path.join(OUT_DIR, 'MapleStory DS (English).nds')
        open(op, 'wb').write(out)
        open(os.path.join(OUT_DIR, 'layout_report.txt'), 'w', encoding='utf-8').write('\n'.join(self.report))
        os.remove(os.path.join(OUT_DIR, '_font.tmp'))
        print('wrote', op, 'files replaced:', len(repl), self.stats, 'layout warnings:', len(self.report))

if __name__ == '__main__':
    Builder().run()
