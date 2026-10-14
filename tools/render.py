"""Render text with the game's NFTR font exactly like FUN_02012000 (advance = charWidth + 1)."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from nftr import NFTR
from PIL import Image

BS = chr(92)  # backslash (kept out of literals to avoid escaping mistakes)
TAGS = [(BS + '[', '['), (BS + ']', ']'), ('[' + BS + 'n]', '\n'), ('[]', ' '),
        ('[A]', '\ue000'), ('[B]', '\ue001'), ('[X]', '\ue002'), ('[Y]', '\ue003'), ('[L]', '\ue004'), ('[R]', '\ue005'),
        ('[>]', '\ue019'), ('[<]', '\ue01a'), ('[^]', '\ue01b'), ('[v]', '\ue01c'),
        ('[color:w]', '\uf801'), ('[color:r]', '\uf803'), ('[color:g]', '\uf804'), ('[color:b]', '\uf805'), ('[color:y]', '\uf808'),
        ('『', '\uf803'), ('「', '\uf808'), ('<', '\uf804'), ('{', '\uf805'), ('』', '\uf801'), ('」', '\uf801'), ('>', '\uf801'), ('}', '\uf801')]
NAME_SAMPLE = 'Maplerrrrrr'  # widest plausible player name placeholder (set later)

def expand(s, name='Maple'):
    for t in ('S_PC', 'R_PC', 'A_PC', 'M_PC'):
        s = s.replace(BS + '[name:%s' % t + BS + ']', name).replace('[name:%s]' % t, name).replace('[name：%s]' % t, name)
    for a, b in TAGS:
        s = s.replace(a, b)
    return s

class Measurer:
    def __init__(self, font_path):
        self.f = NFTR(open(font_path, 'rb').read())
    def adv(self, ch):
        gi = self.f.cmap.get(ord(ch), self.f.cmap.get(self.f.alt_char, 0))
        w = self.f.widths.get(gi, (0, self.f.def_glyph_w, self.f.def_char_w))
        return w
    def line_widths(self, text):
        """Return pixel widths per line of already-expanded text (no auto wrap)."""
        out = []; x = 0
        for ch in text:
            if ch == '\n':
                out.append(x); x = 0; continue
            if 0xf800 <= ord(ch) <= 0xf8ff: continue
            w = self.adv(ch)
            x += w[2] + 1
        out.append(x)
        return [max(0, v - 1) for v in out]

    def render(self, text, boxw=None, scale=3):
        lines = text.split('\n')
        h = (len(lines)) * 14 + 4
        W = boxw or (max(self.line_widths(text)) + 4)
        img = Image.new('RGB', (W + 4, h), (32, 40, 64))
        px = img.load()
        colors = {1: (255, 255, 255), 3: (255, 80, 80), 4: (100, 255, 100), 5: (120, 160, 255), 8: (255, 230, 80)}
        col = colors[1]
        y = 2
        for ln in lines:
            x = 2
            for ch in ln:
                if 0xf800 <= ord(ch) <= 0xf8ff:
                    col = colors.get(ord(ch) & 0xff, col); continue
                gi = self.f.cmap.get(ord(ch), 0)
                l, gw, cw = self.f.widths.get(gi, (0, 11, 11))
                g = self.f.glyph_bits(gi)
                for yy, row in enumerate(g):
                    for xx, v in enumerate(row):
                        if v and 0 <= x + l + xx < img.width and y + yy < img.height:
                            px[x + l + xx, y + yy] = col
                x += cw + 1
            y += 14
        if boxw:
            for yy in range(img.height): px[boxw + 1, yy] = (255, 0, 0)
        return img.resize((img.width * scale, img.height * scale), Image.NEAREST)

if __name__ == '__main__':
    m = Measurer(sys.argv[1])
    t = expand(sys.argv[2])
    print(m.line_widths(t))
    m.render(t).save(sys.argv[3])
