"""Drawing helpers for English replacement graphics: erase Japanese text, draw styled text.

All coordinates are image pixels of the cell/screen render (see gfx.py)."""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONTS = r'C:\Windows\Fonts'
FONT_FILES = {
    'bold': 'verdanab.ttf', 'sans': 'tahoma.ttf', 'sansbold': 'tahomabd.ttf',
    'arialbold': 'arialbd.ttf', 'arialbi': 'arialbi.ttf', 'narrowbold': 'ARIALNB.TTF',
    'narrowbi': 'ARIALNBI.TTF', 'trebbold': 'trebucbd.ttf', 'trebbi': 'trebucbi.ttf',
    'impact': 'impact.ttf', 'segoebold': 'segoeuib.ttf', 'calibribold': 'calibrib.ttf',
}

def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, FONT_FILES.get(name, name)), size)


def erase_rows(img, box, refs):
    """Fill box (x0,y0,x1,y1) row by row with the average colour of reference columns `refs`."""
    a = np.array(img)
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        cols = [a[y, r] for r in refs if 0 <= r < a.shape[1]]
        c = np.mean(cols, axis=0).astype(np.uint8) if cols else a[y, x0]
        a[y, x0:x1] = c
    return Image.fromarray(a)

def erase_cols(img, box, refs):
    """Fill box column by column with the average colour of reference rows `refs`."""
    a = np.array(img)
    x0, y0, x1, y1 = box
    for x in range(x0, x1):
        rows = [a[r, x] for r in refs if 0 <= r < a.shape[0]]
        a[y0:y1, x] = np.mean(rows, axis=0).astype(np.uint8)
    return Image.fromarray(a)

def erase_clear(img, box):
    a = np.array(img); x0, y0, x1, y1 = box
    a[y0:y1, x0:x1] = 0
    return Image.fromarray(a)

def erase_patch(img, box, src):
    """Copy the region starting at src=(x,y) over box."""
    x0, y0, x1, y1 = box
    p = img.crop((src[0], src[1], src[0] + x1 - x0, src[1] + y1 - y0))
    img = img.copy(); img.paste(p, (x0, y0))
    return img


def text_mask(text, fnt, aa=False, tracking=0, scale_x=1.0):
    """Return an L-mode mask of the text (tight bbox) and the baseline offset."""
    asc, desc = fnt.getmetrics()
    w = int(sum(fnt.getlength(c) + tracking for c in text) + 8)
    h = asc + desc + 4
    m = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(m)
    if not aa:
        d.fontmode = '1'
    if tracking == 0:
        d.text((2, 2), text, font=fnt, fill=255)      # whole string: keeps the font's kerning
    else:
        x = 2
        for c in text:
            d.text((x, 2), c, font=fnt, fill=255)
            x += fnt.getlength(c) + tracking
    if scale_x != 1.0:
        m = m.resize((max(1, int(m.width * scale_x)), m.height), Image.LANCZOS if aa else Image.NEAREST)
    bb = m.getbbox() or (0, 0, 1, 1)
    return m.crop(bb)


def cap_band(text, fnt, aa=False, tracking=0):
    """(cap_top, baseline) of the text relative to the top of text_mask(text): the band that
    should be centred, so descenders (g, y, p) don't push the word upwards."""
    def top_of(s):
        m = Image.new('L', (int(fnt.getlength(s)) + 8, sum(fnt.getmetrics()) + 4), 0)
        d = ImageDraw.Draw(m)
        if not aa: d.fontmode = '1'
        d.text((2, 2), s, font=fnt, fill=255)
        bb = m.getbbox()
        return bb[1], bb[3]
    t_top, _ = top_of(text)
    h_top, h_bot = top_of('H')
    return h_top - t_top, h_bot - t_top


def dilate(mask, r):
    if r <= 0: return mask
    return mask.filter(ImageFilter.MaxFilter(2 * r + 1))

def dilate_square(mask, r):
    a = np.array(mask) > 0
    out = a.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(a, dy, 0), dx, 1)
    return Image.fromarray((out * 255).astype(np.uint8))


def draw_text(img, text, fnt, center=None, pos=None, fill=(255, 255, 255), outline=None, ow=1,
              shadow=None, soff=(1, 1), aa=False, tracking=0, scale_x=1.0, gradient=None,
              round_outline=True, max_w=None):
    """Draw text centred at `center` (cx, cy) or with top-left at `pos`.
    gradient: (top_rgb, bottom_rgb) vertical gradient fill instead of `fill`.
    Returns (img, bbox)."""
    m = text_mask(text, fnt, aa, tracking, scale_x)
    if max_w and m.width > max_w:
        m = m.resize((max_w, m.height), Image.LANCZOS if aa else Image.NEAREST)
    pad = ow + max(abs(soff[0]), abs(soff[1])) + 1
    W, H = m.width + 2 * pad, m.height + 2 * pad
    base = Image.new('L', (W, H), 0); base.paste(m, (pad, pad))
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    if outline is not None:
        om = dilate(base, ow) if round_outline else dilate_square(base, ow)
        if shadow is not None:
            sm = Image.new('L', (W, H), 0); sm.paste(om, soff)
            layer.paste(Image.new('RGBA', (W, H), shadow + (255,)), (0, 0), sm)
        layer.paste(Image.new('RGBA', (W, H), outline + (255,)), (0, 0), om)
    elif shadow is not None:
        sm = Image.new('L', (W, H), 0); sm.paste(base, soff)
        layer.paste(Image.new('RGBA', (W, H), shadow + (255,)), (0, 0), sm)
    if gradient:
        g = np.zeros((H, W, 4), np.uint8)
        t, b = np.array(gradient[0]), np.array(gradient[1])
        y0, y1 = pad, pad + m.height
        for y in range(H):
            f = min(1, max(0, (y - y0) / max(1, y1 - y0 - 1)))
            g[y, :, :3] = (t * (1 - f) + b * f).astype(np.uint8); g[y, :, 3] = 255
        layer.paste(Image.fromarray(g), (0, 0), base)
    else:
        layer.paste(Image.new('RGBA', (W, H), fill + (255,)), (0, 0), base)
    if center is not None:
        x = int(round(center[0] - W / 2)); y = int(round(center[1] - H / 2))
    else:
        x, y = pos[0] - pad, pos[1] - pad
    out = img.copy()
    out.alpha_composite(layer, (x, y)) if x >= 0 and y >= 0 and x + W <= img.width and y + H <= img.height else _composite_clip(out, layer, x, y)
    return out, (x + pad, y + pad, x + pad + m.width, y + pad + m.height)

def _composite_clip(out, layer, x, y):
    big = Image.new('RGBA', out.size, (0, 0, 0, 0))
    big.paste(layer, (x, y), layer)
    out.alpha_composite(big)
