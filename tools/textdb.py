"""Shared logic for the translation database: collecting Japanese message tables,
layout rules per table, and word-wrapping English to the game's pixel widths."""
import os, sys, json, re, collections
sys.path.insert(0, os.path.dirname(__file__))
from gmm import parse_gmm, looks_like_gmm
from narc import parse_narc

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
NX = os.path.join(ROOT, 'extracted', 'nx')
TRANS = os.path.join(ROOT, 'translation')
BS = chr(92)
NL = '[' + BS + 'n]'          # hard line break tag as stored in message files

# Layout rules: (max_width_px, max_lines). Dialogue boxes measured from the Japanese script.
# max_lines=None means "no limit / scrolling or auto-sized window".
RULES = {
    'DIALOG': (216, 4),
    'MAPNAME': (104, 1),
    'ITEMNAME': (107, 1),
    'ITEMDESC': (216, 3),
    'HINT': (224, 7),
    'GLOBAL': (216, 6),
    'MONSTERNAME': (101, 1),
    'MONSTERGEN': (145, 1),
    'SKILL': (216, 4),
    'SYNOPSIS': (216, None),
    'MAPDESCRIPTIONS': (216, None),
    'CHAPTER': (125, 1),
    'MOVIE': (110, 1),
    'DNA': (180, 2),
    'GALLERY': (110, 1),
    'TAXI': (216, 4),
    'QUIZ': (216, 6),
    'SHOP': (165, 2),
    'MAINMENU': (216, 1),
    'MONSTERBOOK': (156, 1),
    'CLASS': (216, 1),
    'EQUIPHELPMESSAGE': (61, 2),
    'SONGPUZZLE': (207, 1),
    'CREDIT': (216, None),
    'PROLOGUE': (216, None),
    'TUTORIAL': (216, 4),
    'CHARSEL': (216, 2),
}

def category(container, inner):
    """Map a message table location to a layout rule key."""
    name = (inner or container).split('/')[-1].upper().replace('.', '')
    if '#' in container or inner:
        n = (inner or '').upper()
        if n.startswith('MP') or n.startswith('GLOBALSCENE') or n.startswith('000000000'):
            return 'DIALOG'
        if n.startswith('MO'):
            return 'MAPNAME'
    for k in sorted(RULES, key=len, reverse=True):
        if name.startswith(k):
            return k
    return 'DIALOG'

def is_japanese_table(name):
    return name.upper().replace('.', '').endswith('GMMJAPANESE')

def iter_tables():
    """Yield (container_relpath, inner_name or None, gmm_bytes) for every Japanese message table."""
    for dp, dn, fn in os.walk(NX):
        for f in sorted(fn):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, NX).replace(os.sep, '/')
            if f.split('.')[-1] in ('NCLR', 'NCER', 'NCBR', 'NANR', 'NCGR', 'NSCR', 'NXATARI'):
                continue
            d = open(p, 'rb').read()
            if d[:4] == b'NARC':
                names, files, _ = parse_narc(d)
                for i, blob in enumerate(files):
                    nm = names[i] or str(i)
                    if is_japanese_table(nm) and looks_like_gmm(blob):
                        yield rel, nm, blob
            elif is_japanese_table(f) and looks_like_gmm(d):
                yield rel, None, d

def has_jp(t):
    return any('぀' <= c <= 'ヿ' or '一' <= c <= '鿿' or '＀' <= c <= '￯' or '　' <= c <= '〿' for c in t)

# ---------------------------------------------------------------- wrapping
# button tags first: escaped \[A\] etc. render as one prompt (keycap/button) in the PC port
_BUTTON = re.escape(BS) + r'\[(?:[ABXYLR<>v^]|START|SELECT)' + re.escape(BS) + r'\]'
_COMBO = re.escape(BS) + r'\[\^' + re.escape(BS) + r'\]\+' + _BUTTON  # Up + L/Y/X: skills 4-6
_TOKEN = re.compile(r'(' + _COMBO + r'|' + _BUTTON + r'|\[' + re.escape(BS) + r'n\]|' + re.escape(BS) + r'\[name[:：][A-Z]_PC' + re.escape(BS) + r'\]|\[[A-Za-z<>^]\]|\[color:[a-z]\]|\[\]|' + re.escape(BS) + r'\[|' + re.escape(BS) + r'\])')

class Wrapper:
    NAME_PX = 60  # worst-case width reserved for the player's name
    COMBO_PX = 40   # Up + skill button: one keycap, or d-pad icon + shoulder button
    BUTTON_PX = 27  # a button prompt: DS icon (11px) or a PC keycap such as SHIFT (25px)

    def __init__(self, measurer):
        self.m = measurer

    def char_px(self, ch):
        if ch == '\x00':
            ch = ' '
        if ch in '<>{}「」『』':
            return 0  # markup -> colour change, no glyph
        return self.m.adv(ch)[2] + 1

    def token_px(self, tok):
        if tok == NL:
            return None
        if tok.startswith(BS + '[name'):
            return self.NAME_PX
        if tok.startswith('[color') or tok == '':
            return 0
        if tok in ('[]',):
            return self.char_px(' ')
        if re.fullmatch(_COMBO, tok):
            return self.COMBO_PX
        if re.fullmatch(_BUTTON, tok) or (len(tok) == 3 and tok[0] == '[' and tok[2] == ']'):
            return self.BUTTON_PX
        if tok in (BS + '[', BS + ']'):
            return self.char_px(tok[1])
        return sum(self.char_px(c) for c in tok)

    def words(self, segment):
        """Split a segment (no hard breaks) into words keeping markup tokens attached."""
        parts = _TOKEN.split(segment)
        out = []
        cur = ''
        for p in parts:
            if not p:
                continue
            if _TOKEN.fullmatch(p):
                cur += p
                continue
            pieces = p.split(' ')
            for j, piece in enumerate(pieces):
                if j > 0:
                    out.append(cur); cur = ''
                cur += piece
        out.append(cur)
        return [w for w in out if w != '']

    def word_px(self, w):
        parts = _TOKEN.split(w)
        return sum(self.token_px(p) if _TOKEN.fullmatch(p) else sum(self.char_px(c) for c in p) for p in parts if p)

    def wrap(self, text, width):
        """Word-wrap English text to `width` pixels. Existing [\\n] are kept as hard breaks.
        Returns (wrapped_text, line_count, overflow_px)."""
        space = self.char_px(' ')
        lines = []
        overflow = 0
        for seg in text.split(NL):
            seg_px = self.word_px(seg.replace(' ', '\x00')) if seg else 0
            if seg_px - 1 <= width:
                lines.append(seg)  # fits as written: keep author spacing verbatim
                continue
            words = self.words(seg)
            if not words:
                lines.append(''); continue
            cur, cw = '', 0
            for w in words:
                wp = self.word_px(w)
                if cur and cw + space + wp - 1 > width:
                    lines.append(cur); cur, cw = w, wp
                else:
                    cw = cw + space + wp if cur else wp
                    cur = cur + ' ' + w if cur else w
                overflow = max(overflow, cw - 1 - width)
            lines.append(cur)
        return NL.join(lines), len(lines), overflow

def load_translations():
    """Merge all translation/strings/*.json into {jp: en} plus per-id overrides."""
    tr = {}
    over = {}
    sdir = os.path.join(TRANS, 'strings')
    if os.path.isdir(sdir):
        for f in sorted(os.listdir(sdir)):
            if not f.endswith('.json'):
                continue
            for e in json.load(open(os.path.join(sdir, f), encoding='utf-8')):
                if e.get('en'):
                    tr.setdefault(e['jp'], e['en'])
    op = os.path.join(TRANS, 'overrides.json')
    if os.path.exists(op):
        over = json.load(open(op, encoding='utf-8'))
    return tr, over
