"""Generate the English replacement PNGs in translation/gfx/ from the original graphics.

Each job renders original cells/screens, removes the Japanese lettering and draws English in
the original's style. The PNGs it writes are the editable source the build imports
(tools/gfx_patch.py); touch them up by hand if needed and list the file in KEEP so the
generator leaves it alone.

usage: python tools/gfx_make.py [filter]     (filter = substring of the entry name)
"""
import os, sys
import numpy as np
from PIL import Image, PngImagePlugin
sys.path.insert(0, os.path.dirname(__file__))
from gfx import NX, ROOT, NCER, NCGR, NCLR, NSCR, load, find_palette, ncer_charfile
from gfx_text import font, draw_text, erase_rows

OUT = os.path.join(ROOT, 'translation', 'gfx')
DEBUG = False
KEEP = set()   # 'OUT/UI_CSS4_c00' ... hand-edited files the generator must not overwrite


# ------------------------------------------------------------------ loading / saving

_cache = {}
def cellset(entry):
    if entry not in _cache:
        p = os.path.join(NX, entry + '.NCER')
        _cache[entry] = (NCER(load(p)), NCGR(load(ncer_charfile(p))), NCLR(load(find_palette(p))))
    return _cache[entry]

def render_cell(entry, i, drop=None):
    """Render cell i at its full bounds; OAMs for which drop(oam) is true are left out."""
    nc, cg, pl = cellset(entry)
    b = nc.cell_bounds(i)
    if drop is None:
        return nc.render(i, cg, pl), b
    saved = nc.cells[i]['oams']
    nc.cells[i]['oams'] = [o for o in saved if not drop(o)]
    try:
        im = nc.render(i, cg, pl, bounds=b)
    finally:
        nc.cells[i]['oams'] = saved
    return im, b

def save_cell(entry, i, img, origin=None):
    name = '%s_c%02d' % (entry, i)
    if name in KEEP:
        return
    p = os.path.join(OUT, name + '.png')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    meta = PngImagePlugin.PngInfo()
    if origin:
        meta.add_text('origin', '%d,%d' % origin)
    img.save(p, pnginfo=meta)

def render_bg(entry):
    base = os.path.join(NX, entry)
    return NSCR(load(base + '.NSCR')).render(NCGR(load(base + '.NCGR')), NCLR(load(find_palette(base + '.NSCR'))))

def save_bg(entry, img):
    if entry in KEEP:
        return
    p = os.path.join(OUT, entry + '.png')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    img.save(p)


# ------------------------------------------------------------------ cleaning

def clean_rows(img, rows, margin=5, cols=None):
    """Rebuild each row between the opaque edges (+margin) by interpolating the edge colours.
    Works for the game's horizontally uniform gradient buttons and plates."""
    a = np.array(img).astype(float)
    out = a.copy()
    op = a[..., 3] > 0
    for y in range(*rows):
        xs = np.nonzero(op[y])[0]
        if len(xs) < 2 * margin + 2:
            continue
        L, R = (xs[0] + margin, xs[-1] - margin) if cols is None else cols
        cl, cr = a[y, L], a[y, R]
        for x in range(L + 1, R):
            f = (x - L) / (R - L)
            out[y, x] = cl * (1 - f) + cr * f
    return Image.fromarray(out.round().astype(np.uint8))

def darker(c, f):
    return tuple(int(v * f) for v in c[:3])

def mid_colour(img, y=None):
    a = np.array(img)
    y = a.shape[0] // 2 if y is None else y
    xs = np.nonzero(a[y, :, 3])[0]
    return tuple(int(v) for v in a[y, xs[len(xs) // 2 if len(xs) else 0], :3])



def opaque_bbox(img, box=None):
    a = np.array(img)[..., 3] > 0
    if box:
        m = np.zeros_like(a); x0, y0, x1, y1 = box; m[y0:y1, x0:x1] = True; a &= m
    ys, xs = np.nonzero(a)
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else None

def text_colours(img, box=None):
    """(fill, outline) sampled from lettering: most common bright / dark opaque colours."""
    a = np.array(img)
    if box:
        x0, y0, x1, y1 = box; a = a[y0:y1, x0:x1]
    px = a[a[..., 3] > 0][:, :3].astype(int)
    lum = px @ np.array([3, 6, 1])
    order = np.argsort(lum)
    n = len(px)
    def common(sel):
        vals, cnt = np.unique(sel, axis=0, return_counts=True)
        return tuple(int(v) for v in vals[cnt.argmax()])
    return common(px[order[int(n * 0.6):]]), common(px[order[:max(1, int(n * 0.3))]])

def clear_except(img, keep=None):
    a = np.array(img)
    out = np.zeros_like(a)
    if keep:
        x0, y0, x1, y1 = keep; out[y0:y1, x0:x1] = a[y0:y1, x0:x1]
    return Image.fromarray(out)

def place(base, text, fnt, anchor_box, align='center', valign='center', dx=0, dy=0, **kw):
    """Draw text aligned within anchor_box (x0,y0,x1,y1)."""
    from gfx_text import text_mask
    m = text_mask(text, fnt, kw.get('aa', False), kw.get('tracking', 0), kw.get('scale_x', 1.0))
    w, h = m.size
    if kw.get('max_w') and w > kw['max_w']:
        w = kw['max_w']
    x0, y0, x1, y1 = anchor_box
    x = {'center': (x0 + x1 - w) / 2, 'left': x0, 'right': x1 - w}[align] + dx
    if valign == 'center':
        from gfx_text import cap_band
        ct, cb = cap_band(text, fnt, kw.get('aa', False), kw.get('tracking', 0))
        y = (y0 + y1) / 2 - (ct + cb) / 2 + dy      # centre the cap-height band, not the descenders
    else:
        y = {'top': y0, 'bottom': y1 - h}[valign] + dy
    out, bb = draw_text(base, text, fnt, pos=(int(round(x)), int(round(y))), **kw)
    return out, bb

def text_only(entry, cells, texts, face='arialbold', size=12, keep=None, align='center', valign='center',
              ow=1, shadow=None, fill=None, outline=None, dx=0, dy=0, **kw):
    """Cells that are just lettering (optionally with an icon box to keep): redraw the lettering."""
    for i, t in zip(cells, texts):
        im, b = render_cell(entry, i)
        if keep and callable(keep):
            kb = keep(im)
        else:
            kb = keep
        region = (0, 0, im.width, im.height)
        tb = opaque_bbox(clear_except(im, region) if not kb else _minus(im, kb))
        f, o = text_colours(im if not kb else _minus(im, kb))
        base = clear_except(im, kb)
        redraw(entry, i, b, base, t, font(face, size), tb, align, valign, dx=dx, dy=dy, fill=fill or f,
               outline=outline or o, ow=ow, shadow=shadow, **kw)

def redraw(entry, i, b, base, text, fnt, tb, align='center', valign='center', **kw):
    """Draw `text` on `base` (a render of cell i at bounds b) anchored to box tb and save it.
    The canvas grows sideways in 8 px steps when the English is wider than the cell; the
    importer covers the new area with extra OAMs."""
    from gfx_text import text_mask
    ow = kw.get('ow', 1)
    need = text_mask(text, fnt, kw.get('aa', False), kw.get('tracking', 0)).width + 2 * ow + 4
    if align == 'center':
        cx = (tb[0] + tb[2]) / 2
        gl = max(0, int(need / 2 - cx + 1)); gr = max(0, int(cx + need / 2 - base.width + 1))
    elif align == 'right':
        gl, gr = max(0, need - tb[2]), 0
    else:
        gl, gr = 0, max(0, tb[0] + need - base.width)
    gl, gr = (gl + 7) // 8 * 8, (gr + 7) // 8 * 8      # keep the 8 px OAM grid
    if gl or gr:
        big = Image.new('RGBA', (base.width + gl + gr, base.height), (0, 0, 0, 0))
        big.paste(base, (gl, 0)); base = big
        tb = (tb[0] + gl, tb[1], tb[2] + gl, tb[3])   # same anchor, shifted into the new canvas
    out, _ = place(base, text, fnt, tb, align, valign, **kw)
    if gl or gr:
        if b[0] - gl < -128 or b[2] + gr > 128:
            print('warning: %s c%d wider than the screen' % (entry, i))
        save_cell(entry, i, out, origin=(b[0] - gl, b[1]))
    else:
        save_cell(entry, i, out)

def _minus(im, box):
    a = np.array(im).copy(); x0, y0, x1, y1 = box; a[y0:y1, x0:x1] = 0
    return Image.fromarray(a)

# ------------------------------------------------------------------ jobs

def button(entry, cells, text, size=13, face='bold', rows=None, dy=0, margin=5, outline=None,
           ofac=0.45, shadow=True, fill=(255, 255, 255), tracking=0, cols=None, scale_x=1.0, max_w=None):
    """Gradient button: wipe the Japanese label + small English subtitle, draw one English label."""
    for i in cells:
        im, b = render_cell(entry, i)
        a0 = np.array(im)[..., 3]
        ys = np.nonzero(a0[:, a0.shape[1] // 2])[0]
        top, bot = (ys[0], ys[-1] + 1) if len(ys) else (0, im.height)
        r = (top + rows[0], top + rows[1]) if rows else (top + 3, bot - 4)
        base = clean_rows(im, r, margin, cols)
        oc = outline or darker(mid_colour(base, (r[0] + r[1]) // 2), ofac)
        sc = darker(oc, 0.7) if shadow else None
        a = np.array(base)
        ys = [y for y in range(r[0], r[1]) if a[y, :, 3].any()]
        cy = (r[0] + r[1]) / 2 + dy
        xs = np.nonzero(a[(r[0] + r[1]) // 2, :, 3])[0]
        cx = (xs[0] + xs[-1] + 1) / 2
        out, _ = place(base, text, font(face, size), (cx - 128, cy - 32, cx + 128, cy + 32), fill=fill,
                       outline=oc, ow=1, shadow=sc, tracking=tracking, scale_x=scale_x, max_w=max_w)
        save_cell(entry, i, out)


JOBS = []
def job(f):
    JOBS.append(f); return f

MAPS_T1 = ['Southperry', 'Southperry West']
MAPS_T2 = ['Perion', 'Perion West', 'Perion East', 'Excavation Camp', 'Excavation Site',
           'Sharenian Palace', 'Sleepywood', 'Sleepy Dungeon', 'Sleepywood South', 'Forgotten Temple',
           'Ant Tunnel', "Golem's Temple", 'Ellinia', 'Ellinia West', 'Henesys', 'Henesys East',
           'Kerning City', 'Construction Site', 'Subway', 'North Forest', 'Secret Passage']
MAPS_T3 = ['Airship', 'Ludibrium', 'Eos Tower', 'Helios Tower', 'Toy Factory', 'Clocktower',
           'Omega Sector', 'Roswell Field', 'Downtown', 'Crow Mountain', 'Leafre', 'Minar Forest',
           'Dragon Forest', 'Dragon Canyon', 'Cave of Life', 'El Nath', 'Snowy Hills', 'Frozen Plains',
           'Dead Tree Forest', 'Dead Mine', 'Magatia Lab', 'Magatia Depths']
MAPS_T7 = ['Perion', 'Perilous Valley', 'Kerning City', 'Kerning City West', 'Henesys', 'Henesys West',
           'Ellinia', 'Towering Tree', 'Perion East']


@job
def title_buttons():
    button('OUT/UI_CSS4', [0, 1, 2], 'New Data', size=15, margin=14)
    button('OUT/UI_CSS6', [0, 1, 2], 'Continue', size=14, margin=10)
    button('OUT/UI_CSS6', [3, 4, 5], 'Select Chapter', size=14, margin=10)
    small = {3: 'Delete', 4: 'OK', 5: 'Delete', 6: 'OK', 7: 'Yes', 8: 'No', 9: 'Yes', 10: 'No',
             13: 'Delete', 14: 'OK', 15: 'Yes', 16: 'No'}
    for i, t in small.items():
        button('OUT/UI_CSS7', [i], t, size=11, rows=(3, 33))
    for cells, t in [((0, 1, 2), 'Delete Data'), ((3, 4, 5), 'Change Sign'), ((6, 7, 8), 'Credits'),
                     ((9, 10, 11), 'Coupon Book'), ((12, 13, 14), 'Movies'), ((15, 16, 17), 'Gallery')]:
        button('OUT/UI_CSS8', cells, t, size=12, rows=(4, 42), margin=8)

@job
def coupon_buttons():
    button('OUT/UI_CBS1', [0, 1, 2], 'View Coupons', size=13, rows=(4, 50), margin=10)
    button('OUT/UI_CBS1', [3, 4, 5], 'Enter Magic No.', size=13, rows=(4, 50), margin=10)
    text_only('OUT/UI_CBS1', [22], ['Clear used coupons'], face='sans', size=10, keep=(0, 0, 13, 16),
              align='left', ow=1)
    for cells, t in [((2, 3, 4), 'Yes'), ((5, 6, 7), 'No'), ((8, 9, 10), 'Delete'), ((11, 12, 13), 'Done')]:
        button('OUT/UI_CBS3', cells, t, face='sansbold', size=11, rows=(3, 20), margin=3, shadow=False, dy=1)

@job
def name_entry():
    button('OUT/UI_NQS2', [5, 6, 7], 'Back', face='sansbold', size=12, rows=(3, 21), margin=4)
    button('OUT/UI_NQS2', [8, 9, 10], 'Done', face='sansbold', size=12, rows=(3, 21), margin=4)
    im, b = render_cell('OUT/UI_NQS2', 17)
    base = clean_rows(im, (2, 21), 3)
    base.paste(im.crop((0, 0, 19, im.height)), (0, 0))       # keep the A-button icon
    out, _ = place(base, 'OK', font('sans', 12), (21, 1, im.width - 4, 20), 'left', fill=(255, 255, 255),
                   outline=darker(mid_colour(base), 0.5))
    save_cell('OUT/UI_NQS2', 17, out)

@job
def touch_to_start():
    # cell 1 is the blinking 'off' frame: the same plate without lettering -> use it as background
    base, b1 = render_cell('OUT/UI_OP', 1)
    im, b0 = render_cell('OUT/UI_OP', 0)
    assert b0 == b1
    out, _ = place(base, 'Touch the screen to start', font('sansbold', 12), (0, 4, im.width, im.height - 3),
                   fill=(255, 255, 255), outline=(24, 72, 80))
    save_cell('OUT/UI_OP', 0, out)

@job
def game_over():
    button('IN/UI_RBS', [0, 1, 2], 'Load', size=13, rows=(36, 60), margin=12)
    button('IN/UI_RBS', [3, 4, 5], 'Continue', size=13, rows=(36, 60), margin=12)

@job
def menu_tabs():
    tabs = ['Items', 'Equip', 'Skills', 'Story', 'Map', 'Hints', 'Monster Book', 'Quick Save']
    # all eight tabs share one plate; the 'Map' tab (short label) gives a clean copy of it
    plate = clean_rows(render_cell('IN/UI_US1', 19)[0], (3, 21), 2)
    for i, t in zip(range(15, 23), tabs):
        face, size, tr = ('sansbold', 11, 0)
        if len(t) > 8:
            from gfx_text import text_mask
            face, size, tr = next(('narrowbold', z, k) for z, k in ((12, 0), (11, -1), (10, -1))
                                  if text_mask(t, font('narrowbold', z), tracking=k).width <= 54)
        out, _ = place(plate, t, font(face, size), (4, 2, 60, 22), 'right', fill=(255, 239, 0), outline=(0, 24, 41),
                       tracking=tr)
        save_cell('IN/UI_US1', i, out)
    for i, t in zip(range(60, 68), tabs):
        text_only('IN/UI_US1', [i], [t], face='sansbold', size=10, align='right')
    for i, t in ((33, 'Buy'), (34, 'Sell')):
        text_only('IN/UI_US1', [i], [t], face='arialbold', size=15, align='left', ow=1,
                  fill=(255, 255, 255), outline=(24, 82, 123))

@job
def map_plates():
    for entry, names in [('IN/UI_T1', MAPS_T1), ('IN/UI_T2', MAPS_T2), ('IN/UI_T3', MAPS_T3)]:
        for i, t in enumerate(names):
            im, b = render_cell(entry, i)
            base = clean_rows(im, (2, im.height - 2), 3)
            out, _ = place(base, t, font('sansbold', 12), (2, 2, im.width - 3, im.height - 2), fill=(255, 255, 255),
                           outline=darker(mid_colour(base), 0.35), max_w=im.width - 8)
            save_cell(entry, i, out)

def diff_layer(im, base):
    a = np.array(im); a0 = np.array(base)
    return Image.fromarray(np.where((a != a0).any(-1, keepdims=True), a, 0).astype(np.uint8))

def map_title(entry, i, text, size=14, band=24):
    """Area-name title (bold italic lettering, optionally under a town icon)."""
    im, b = render_cell(entry, i)
    a = np.array(im)
    H = im.height
    # lettering height: rows (from the bottom up) containing the fill colour, gaps of < 3 rows
    rows = np.nonzero(a[..., 3].any(1))[0]
    last = rows[-1] + 1 if len(rows) else H
    fcol = np.array(text_colours(Image.fromarray(a[max(0, last - 10):last]))[0])
    hit = [(np.abs(a[y, :, :3].astype(int) - fcol).sum(-1) < 40).any() for y in range(H)]
    hits = [y for y in range(H) if hit[y]]
    start = hits[-1] if hits else H - 1          # lowest row of lettering
    top, gap = start, 0
    for y in range(start, -1, -1):
        if hit[y]:
            top, gap = y, 0
        else:
            gap += 1
            if gap >= 3: break
    band = max(band, H - top + 3)
    if DEBUG: print(entry, i, "H", H, "band", band, "fill", tuple(fcol))
    if not a[:max(0, H - band - 2), :, 3].any():
        base = Image.new('RGBA', im.size, (0, 0, 0, 0))        # lettering only
    else:
        # icon above the lettering: strip only lettering pixels inside the text band.
        # Lettering colours come from its lowest rows (below any icon); bright ones go everywhere
        # in the band, dark (outline/shadow) ones only next to removed lettering.
        y0 = max(0, H - band)
        low = a[max(0, start - 6):start + 1]
        cols = np.unique(low[low[..., 3] > 0][:, :3], axis=0).astype(int)
        lum = cols @ np.array([3, 6, 1]) / 10
        bright, dark = cols[lum > 80], cols[lum <= 80]
        rgb = a[..., :3].astype(int)
        def near(cs, thr):
            if not len(cs): return np.zeros(a.shape[:2], bool)
            return (np.abs(rgb[:, :, None, :] - cs[None, None]).sum(-1) < thr).any(-1)
        band_m = np.zeros(a.shape[:2], bool); band_m[y0:] = True
        opaque = a[..., 3] > 0
        fill_m = near(bright, 60) & band_m & opaque
        from PIL import ImageFilter
        grown = np.array(Image.fromarray((fill_m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
        dark_m = near(dark, 40) & band_m & opaque & grown
        ab = a.copy(); ab[fill_m | dark_m] = 0
        base = Image.fromarray(ab)
    textpx = diff_layer(im, base)
    tb = opaque_bbox(textpx)
    f, o = text_colours(textpx)
    redraw(entry, i, b, base, text, font('arialbi', size), tb, 'center', 'center', fill=f, outline=(0, 0, 0),
           ow=1, shadow=o if sum(o) > 0 else (16, 16, 48), soff=(1, 1))

@job
def map_titles():
    for entry, names in [('IN/UI_T4', MAPS_T1), ('IN/UI_T5', MAPS_T2), ('IN/UI_T6', MAPS_T3), ('IN/UI_T7', MAPS_T7)]:
        for i, t in enumerate(names):
            map_title(entry, i, t)

@job
def chapter_cards():
    for n in (1, 2, 3, 4):
        entry = 'IN/RES/ST/UI_ST%d' % n
        nc = cellset(entry)[0]
        base, b0 = render_cell(entry, 0)
        for i in range(1, nc.ncells):
            im, b = render_cell(entry, i)
            if b != b0:
                raise SystemExit('%s cell %d bounds differ' % (entry, i))
            textpx = diff_layer(im, base)
            tb = opaque_bbox(textpx)
            f, o = text_colours(textpx)
            out, _ = place(base, 'Chapter %d' % i, font('arialbi', 15), tb, 'center', 'bottom', fill=f,
                           outline=o, ow=1, shadow=(0, 0, 0), soff=(1, 1))
            save_cell(entry, i, out)

@job
def riddles():
    lines = ['Red light is order, red light is time.', 'Time is measure, measure is the world.',
             "The goddess's staff orders the world.", 'Time is a cat, always so fickle.', 'The world is gold.']
    for k, t in enumerate(lines):
        text_only('IN/UI_GS2', [3 * k, 3 * k + 1, 3 * k + 2], [t] * 3, face='narrowbi', size=14, ow=1)


def _fill_1d(a, mask, op):
    out = a.copy(); ok = np.zeros(mask.shape, bool)
    for y in range(a.shape[0]):
        good = np.nonzero(~mask[y] & op[y])[0]
        for x in np.nonzero(mask[y])[0]:
            l = good[good < x]; r = good[good > x]
            if len(l) and len(r):
                f = (x - l[-1]) / (r[0] - l[-1])
                out[y, x] = a[y, l[-1]] * (1 - f) + a[y, r[0]] * f; ok[y, x] = True
            elif len(l) or len(r):
                out[y, x] = a[y, (l[-1] if len(l) else r[0])]
    return out, ok

def inpaint_mask(img, mask):
    """Refill masked pixels by averaging row-wise and column-wise interpolation from the nearest
    unmasked opaque pixels (avoids the streaks a single direction leaves on shaded art)."""
    a = np.array(img).astype(float)
    op = a[..., 3] > 0
    h, hok = _fill_1d(a, mask, op)
    v, vok = _fill_1d(a.transpose(1, 0, 2), mask.T, op.T)
    v, vok = v.transpose(1, 0, 2), vok.T
    out = np.where((hok & vok)[..., None], (h + v) / 2, np.where(vok[..., None], v, h))
    return Image.fromarray(out.round().astype(np.uint8))

def lettering_mask(a, box, grow=1):
    """Yellow lettering + its dark outline inside box."""
    from PIL import ImageFilter
    r, g, b = (a[..., k].astype(int) for k in range(3))
    yellow = (r > 200) & (g > 180) & (b < 110) & (a[..., 3] > 0)
    dark = ((r * 3 + g * 6 + b) < 700) & (a[..., 3] > 0)
    m = np.zeros(a.shape[:2], bool); x0, y0, x1, y1 = box; m[y0:y1, x0:x1] = True
    yel = yellow & m
    near = np.array(Image.fromarray((yel * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    out = yel | (dark & near & m)
    if grow:
        out = np.array(Image.fromarray((out * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * grow + 1))) > 0
        out &= m
    return out

def lines(base, texts, fnt, box, gap=0, **kw):
    """Draw several centred lines inside box."""
    from gfx_text import cap_band
    hs = [cap_band(t, fnt)[1] - cap_band(t, fnt)[0] for t in texts]
    lh = max(hs) + 3 + gap
    total = lh * len(texts) - 3 - gap
    x0, y0, x1, y1 = box
    top = (y0 + y1 - total) / 2
    for k, t in enumerate(texts):
        base, _ = place(base, t, fnt, (x0, top + k * lh, x1, top + k * lh + max(hs)), **kw)
    return base

@job
def world_map():
    E = 'IN/UI_M5S1'
    fnt = font('arialbold', 12)
    for i, texts in ((4, ['Victoria', 'Island']), (5, ['Ossyria'])):
        im, b = render_cell(E, i)
        a = np.array(im)
        box = (0, 0, im.width, im.height)
        m = lettering_mask(a, box)
        tb = opaque_bbox(Image.fromarray(np.where(m[..., None], a, 0).astype(np.uint8)))
        base = inpaint_mask(im, m)
        out = lines(base, texts, fnt, tb, fill=(255, 231, 33), outline=(57, 41, 0), shadow=(24, 32, 0))
        save_cell(E, i, out)
    # Maple Island: yellow lettering on a magenta tag that hangs off the island
    im, b = render_cell(E, 3)
    a = np.array(im)
    r, g, bl = (a[..., k].astype(int) for k in range(3))
    tag = ((r > 120) & (bl > 120) & (g < 110)) & (a[..., 3] > 0)
    region = np.zeros(tag.shape, bool); region[:, 46:] = True
    m = (lettering_mask(a, (46, 0, im.width, im.height), 0) | tag) & region
    from PIL import ImageFilter
    m = np.array(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
    m &= region
    tb = opaque_bbox(Image.fromarray(np.where(m[..., None], a, 0).astype(np.uint8)))
    a2 = a.copy(); a2[m] = 0
    base = Image.fromarray(a2)
    # halo first (thick magenta outline), lettering on top
    halo = lines(Image.new('RGBA', im.size, (0, 0, 0, 0)), ['Maple', 'Island'], fnt, tb, fill=(206, 0, 214),
                 outline=(206, 0, 214), ow=3)
    base.alpha_composite(halo)
    out = lines(base, ['Maple', 'Island'], fnt, tb, fill=(255, 231, 33), outline=(57, 41, 0))
    save_cell(E, 3, out)

@job
def option_sign():
    """Small 'オプション' sign under the mushroom on the title screen sprite set."""
    im, b = render_cell('OUT/UI_CSS21', 14)
    a = np.array(im)
    # the lettering is the bottom strip (yellow with black outline) below the icon
    rows = np.nonzero(((a[..., 0] > 200) & (a[..., 1] > 180) & (a[..., 2] < 100)).any(1))[0]
    y0 = max(rows[-1] - 9, 0)
    base = a.copy(); base[y0:] = 0
    base = Image.fromarray(base)
    out, _ = place(base, 'OPTION', font('narrowbold', 9), (0, y0, im.width, im.height), fill=(255, 231, 0),
                   outline=(0, 0, 0))
    save_cell('OUT/UI_CSS21', 14, out)

def edit_shared_chars(entry, ref_cell, mask):
    """Clear the char pixels under `mask` (set of (x, y) cell coordinates of ref_cell) in every
    OAM of ref_cell, then save every cell whose render changed. For animations whose frames
    share tiles (the title logo), this keeps all frames consistent."""
    from gfx_import import CellImporter
    p = os.path.join(NX, entry + '.NCER')
    ci = CellImporter(load(p), load(ncer_charfile(p)), load(find_palette(p)))
    before = [ci.nc.render(i, ci.cg, ci.pl) for i in range(ci.nc.ncells)]
    bnds = [ci.nc.cell_bounds(i) for i in range(ci.nc.ncells)]
    ref = np.array(before[ref_cell]); rb = bnds[ref_cell]
    # every frame: clear the masked pixels where the frame shows exactly what the reference shows
    # there (frames draw the logo from their own tile copies; a leaf passing over is left alone)
    todo = []
    for i in range(ci.nc.ncells):
        cur = np.array(before[i]); b = bnds[i]
        for (X, Y) in mask:
            if not (b[0] <= X < b[2] and b[1] <= Y < b[3]):
                continue
            p = cur[Y - b[1], X - b[0]]; r = ref[Y - rb[1], X - rb[0]]
            if p[3] and (p == r).all():
                todo.append((i, X, Y))
    for i, X, Y in todo:
        for o in ci.nc.cells[i]['oams']:
            w, h = o.size
            if o.x <= X < o.x + w and o.y <= Y < o.y + h:
                ci.cg.px[ci.px_index(o, X - o.x, Y - o.y)] = 0
    n = 0
    for i in range(ci.nc.ncells):
        if not ci.nc.cells[i]['oams']:
            continue
        after = ci.nc.render(i, ci.cg, ci.pl)
        if np.array_equal(np.array(after), np.array(before[i])):
            continue
        save_cell(entry, i, after); n += 1
    return n

def tag_mask(img, b):
    """Pixels (cell coordinates) of the katakana tag under the logo in one frame: rows holding a
    long run (>= 40 px) of its dark body, widened to its border rows; only the tag's grey/white
    (low-saturation) pixels, so a red leaf passing over it is kept."""
    a = np.array(img).astype(int)
    rgb = a[..., :3]
    lowsat = (rgb.max(-1) - rgb.min(-1) < 48) & (a[..., 3] > 0)
    dark = lowsat & (rgb @ np.array([3, 6, 1]) < 1500)
    rows, x0, x1 = [], 10 ** 6, -1
    for y in range(a.shape[0]):
        run, best, start = 0, (0, 0, 0), 0
        for x in range(a.shape[1]):
            if dark[y, x]:
                if run == 0: start = x
                run += 1
                if run > best[0]: best = (run, start, x + 1)
            else:
                run = 0
        if best[0] >= 40:
            rows.append(y); x0 = min(x0, best[1]); x1 = max(x1, best[2])
    if not rows:
        return set()
    out = set()
    for y in range(max(0, rows[0] - 1), min(a.shape[0], rows[-1] + 5)):
        for x in range(max(0, x0 - 5), x1):
            if lowsat[y, x]:
                out.add((x + b[0], y + b[1]))
    return out

def edit_frames(entry, mask_fn):
    """Clear, in every frame, the char pixels under mask_fn(frame image, bounds) in all OAMs
    covering them, then save each frame whose render changed (frames share tiles, so this is
    done on the char data and every frame is re-rendered from it)."""
    from gfx_import import CellImporter
    p = os.path.join(NX, entry + '.NCER')
    ci = CellImporter(load(p), load(ncer_charfile(p)), load(find_palette(p)))
    before = [ci.nc.render(i, ci.cg, ci.pl) for i in range(ci.nc.ncells)]
    for i in range(ci.nc.ncells):
        if not ci.nc.cells[i]['oams']:
            continue
        for (X, Y) in mask_fn(before[i], ci.nc.cell_bounds(i)):
            for o in ci.nc.cells[i]['oams']:
                w, h = o.size
                if o.x <= X < o.x + w and o.y <= Y < o.y + h:
                    ci.cg.px[ci.px_index(o, X - o.x, Y - o.y)] = 0
    n = 0
    for i in range(ci.nc.ncells):
        if not ci.nc.cells[i]['oams']:
            continue
        after = ci.nc.render(i, ci.cg, ci.pl)
        if not np.array_equal(np.array(after), np.array(before[i])):
            save_cell(entry, i, after); n += 1
    return n

@job
def logo():
    """Remove the katakana reading (メイプルストーリー) tag under the MapleStory logo."""
    for e in ('OUT/UI_OP7', 'OUT/UI_OP8'):      # logo, and the logo layer used on later screens
        print(e, 'frames changed:', edit_frames(e, tag_mask))
    # small logo drawn into the notice screen: the tag sits on the panel's gridded border, so
    # copy the panel texture from two grid periods below over it
    im = render_bg(OB + 'UI_N3').convert('RGBA')
    a = np.array(im)
    a[38:47, 147:187] = a[54:63, 147:187]
    save_bg(OB + 'UI_N3', Image.fromarray(a))

# ------------------------------------------------------------------ BG screens

def bg_rows(img, box, cols=None):
    """Rebuild box row by row by interpolating between the columns just outside it."""
    x0, y0, x1, y1 = box
    L, R = cols or (x0 - 1, x1)
    a = np.array(img.convert('RGBA')).astype(float)
    for y in range(y0, y1):
        cl, cr = a[y, L], a[y, R]
        for x in range(x0, x1) if L == R else range(max(x0, L + 1), min(x1, R)):
            f = 0 if L == R else (x - L) / (R - L)      # L == R: copy that column across
            a[y, x] = cl * (1 - f) + cr * f
    return Image.fromarray(a.round().astype(np.uint8))

def bg_period(img, box, src_x, period=8):
    """Fill box with the periodic panel texture found at columns src_x..src_x+period."""
    x0, y0, x1, y1 = box
    a = np.array(img.convert('RGBA'))
    for x in range(x0, x1):
        a[y0:y1, x] = a[y0:y1, src_x + (x - src_x) % period]
    return Image.fromarray(a)

def bg_siblings(target, sibs, box):
    """Recover the background under lettering from sibling screens drawn over the same art:
    a pixel two siblings agree on (and the target doesn't) is background; pixels nobody can
    vouch for are interpolated along the row."""
    a = np.array(render_bg(target).convert('RGBA')).astype(int)
    ss = [np.array(render_bg(s).convert('RGBA')).astype(int) for s in sibs]
    x0, y0, x1, y1 = box
    known = np.zeros(a.shape[:2], bool)
    out = a.copy()
    for y in range(y0, y1):
        for x in range(x0, x1):
            t = a[y, x]
            vals = [s[y, x] for s in ss]
            if any((v == t).all() for v in vals):
                known[y, x] = True
                continue
            for i in range(len(vals)):
                for j in range(i + 1, len(vals)):
                    if (vals[i] == vals[j]).all():
                        out[y, x] = vals[i]; known[y, x] = True
                        break
                if known[y, x]: break
    for y in range(y0, y1):
        xs = [x for x in range(x0 - 1, x1 + 1) if x < 0 or x >= a.shape[1] or known[y, x] or not (x0 <= x < x1)]
        for x in range(x0, x1):
            if known[y, x]: continue
            l = max([k for k in xs if k < x], default=None); r = min([k for k in xs if k > x], default=None)
            if l is None or r is None or l < 0 or r >= a.shape[1]:
                continue
            f = (x - l) / (r - l)
            out[y, x] = out[y, l] * (1 - f) + out[y, r] * f
    return Image.fromarray(out.astype(np.uint8))

def bg_inpaint_dark(img, box, thr=110, grow=1, light=None):
    """Remove dark lettering drawn straight onto artwork: pixels darker than thr (luminance)
    inside box, plus `grow` px around them, are refilled from the nearest clean pixels in the row."""
    a = np.array(img.convert('RGBA')).astype(float)
    x0, y0, x1, y1 = box
    lum = a[..., :3] @ np.array([0.3, 0.6, 0.1])
    m = np.zeros(lum.shape, bool); m[y0:y1, x0:x1] = lum[y0:y1, x0:x1] < thr
    if light is not None:                      # embossed lettering also has a light edge
        m[y0:y1, x0:x1] |= lum[y0:y1, x0:x1] > light
    if grow:
        from PIL import ImageFilter
        m = np.array(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * grow + 1))) > 0
        box_m = np.zeros_like(m); box_m[y0:y1, x0:x1] = True; m &= box_m
    for y in range(y0, y1):
        xs = np.nonzero(~m[y, x0 - 1:x1 + 1])[0] + x0 - 1
        for x in np.nonzero(m[y, x0:x1])[0] + x0:
            l = xs[xs < x].max(); r = xs[xs > x].min()
            f = (x - l) / (r - l)
            a[y, x] = a[y, l] * (1 - f) + a[y, r] * f
    return Image.fromarray(a.round().astype(np.uint8))

def bg_text(img, text, box, size=11, face='sansbold', align='left', fill=(255, 255, 255), outline=None,
            **kw):
    out, _ = place(img, text, font(face, size), box, align, 'center', fill=fill, outline=outline, **kw)
    return out

MENU_BG = 'IN/RES/BG/'

def title_bar(entry, text):
    """Window title bar of the in-game menus: lettering at x 8..80, y 2..14."""
    im = render_bg(entry)
    f, o = text_colours(im, (8, 3, 76, 14))
    base = bg_rows(im, (6, 2, 80, 15))
    return bg_text(base, text, (9, 2, 120, 15), size=10, fill=(255, 255, 255), outline=o)

@job
def menu_screens():
    for n, t in [('BG8109', 'Items'), ('BG8111', 'Skills'), ('BG8210', 'Skills'), ('BG8311', 'Skills'),
                 ('BG8411', 'Skills'), ('BG8112', 'Equipment'), ('BG8113', 'Monster Book'), ('BG8117', 'Map')]:
        im = title_bar(MENU_BG + n, t)
        if n == 'BG8117':
            # island name on the map art + footer button hints
            im = bg_inpaint_dark(im, (7, 145, 106, 160))
            im = bg_text(im, 'Victoria Island', (9, 144, 120, 160), size=12, face='arialbi', fill=(57, 49, 41))
            im = bg_rows(im, (153, 174, 206, 189), (152, 207))
            im = bg_rows(im, (217, 174, 252, 189), (216, 253))
            im = bg_text(im, 'Area Info', (154, 173, 207, 189), size=11, fill=(255, 255, 255), outline=(16, 40, 64))
            im = bg_text(im, 'Map', (218, 173, 252, 189), size=11, fill=(255, 255, 255), outline=(16, 40, 64))
        save_bg(MENU_BG + n, im)
    sidebar(MENU_BG + 'BG8119')

# status screen side menu: eight flat navy buttons, labels right-aligned. The same label layout
# is used for the dimmed 'disabled' label sprites (UI_US1 c60-67) that the game draws exactly
# on top of these background labels, so the two must match pixel for pixel.
# 49 px buttons: 'Monster Book' does not fit legibly, the screen it opens carries the full name.
SIDEBAR = ['Items', 'Equip', 'Skills', 'Story', 'Map', 'Hints', 'Monsters', 'Quick Save']

def sidebar_label(k):
    """(text, font, tracking, screen box) of side-menu label k."""
    from gfx_text import text_mask
    t = SIDEBAR[k]
    y0 = 11 + 19 * k
    face, size, tr = ('sansbold', 11, 0)
    if len(t) > 8:
        face, size, tr = next(('narrowbold', z, d) for z, d in ((12, 0), (11, 0), (11, -1))
                              if text_mask(t, font('narrowbold', z), tracking=d).width <= 49)
    return t, font(face, size), tr, (194, y0, 243, y0 + 15)

def sidebar(entry):
    im = render_bg(entry)
    for k in range(len(SIDEBAR)):
        y0 = 11 + 19 * k
        im = mode_rows(im, (193, y0, 244, y0 + 15))
        t, f, tr, box = sidebar_label(k)
        im, _ = place(im, t, f, box, 'right', 'center', fill=(214, 222, 231), outline=(0, 16, 33), tracking=tr)
    save_bg(entry, im)

@job
def sidebar_sprites():
    """Dimmed labels (UI_US1 c60-67) drawn over the side menu; OBJ origin is the screen centre."""
    E = 'IN/UI_US1'
    for k in range(len(SIDEBAR)):
        i = 60 + k
        im, b = render_cell(E, i)
        f, o = text_colours(im)
        t, fnt, tr, (x0, y0, x1, y1) = sidebar_label(k)
        # canvas in cell coordinates covering the old cell and the button row
        cx0, cy0 = min(b[0], x0 - 128), min(b[1], y0 - 96 - 2)
        cx1, cy1 = max(b[2], x1 - 128 + 2), max(b[3], y1 - 96 + 2)
        canvas = Image.new('RGBA', (cx1 - cx0, cy1 - cy0), (0, 0, 0, 0))
        box = (x0 - 128 - cx0, y0 - 96 - cy0, x1 - 128 - cx0, y1 - 96 - cy0)
        out, _ = place(canvas, t, fnt, box, 'right', 'center', fill=f, outline=o, tracking=tr)
        save_cell(E, i, out, origin=(cx0, cy0))

LIVE = 'IN/RES/BG/'

@job
def live_menus():
    """The in-game menus (UI_M*, UI_MN, UI_TX...): same layouts as the BG81xx screens above."""
    for n, t in [('UI_M1', 'Equipment'), ('UI_M2', 'Items'), ('UI_M3', 'Skills'), ('UI_M41', 'Story'),
                 ('UI_M6', 'Hint List'), ('UI_M71', 'Monster Book'), ('UI_M72', 'Monster Book'),
                 ('UI_M8', 'Quick Save'), ('UI_M51', 'Map'), ('UI_M52', 'Map'), ('UI_M53', 'Map'),
                 ('UI_M54', 'Map'), ('UI_M55', 'Map')]:
        im = title_bar(LIVE + n, t)
        island = {'UI_M52': ('Maple Island', (7, 145, 100, 160)), 'UI_M53': ('Victoria Island', (7, 145, 106, 160)),
                  'UI_M54': ('Ossyria', (7, 145, 70, 160))}.get(n)
        if island:
            im = bg_inpaint_dark(im, island[1])
            im = bg_text(im, island[0], (9, 144, 140, 160), size=12, face='arialbi', fill=(57, 49, 41))
        if n in ('UI_M52', 'UI_M53', 'UI_M54'):
            im = bg_rows(im, (153, 174, 206, 189), (152, 207))
            im = bg_text(im, 'Area Info', (154, 173, 207, 189), size=11, fill=(255, 255, 255), outline=(16, 40, 64))
        if n in ('UI_M52', 'UI_M53', 'UI_M54', 'UI_M55'):
            im = bg_rows(im, (217, 174, 252, 189), (216, 253))
            im = bg_text(im, 'Map', (218, 173, 252, 189), size=11, fill=(255, 255, 255), outline=(16, 40, 64))
        if n == 'UI_M51':
            a = np.array(im.convert('RGBA'))
            for texts, box in ((['Victoria', 'Island'], (30, 46, 94, 82)), (['Maple', 'Island'], (172, 22, 234, 55)),
                               (['Ossyria'], (160, 128, 234, 148))):
                m = white_lettering_mask(a, box)
                a = np.array(inpaint_mask(Image.fromarray(a), m))
                im = lines(Image.fromarray(a), texts, font('arialbi', 13), box, fill=(255, 255, 255),
                           outline=(24, 40, 72))
                a = np.array(im)
        save_bg(LIVE + n, im)
    # Victoria map without title bar
    im = render_bg(LIVE + 'UI_TX')
    im = bg_inpaint_dark(im, (7, 145, 106, 162))
    save_bg(LIVE + 'UI_TX', bg_text(im, 'Victoria Island', (9, 145, 140, 161), size=12, face='arialbi',
                                     fill=(57, 49, 41)))
    sidebar(LIVE + 'UI_MN')
    # story log page footer: First / Prev / Next / Last
    im = render_bg(LIVE + 'UI_M42')
    for (x0, x1), t in (((40, 67), 'First'), ((97, 126), 'Prev'), ((155, 184), 'Next'), ((210, 239), 'Last')):
        im = fill_box_rows(im, (x0, 164, x1, 182))
        im = bg_text(im, t, (x0, 164, x1, 181), size=11, face='sans', align='center', fill=(255, 255, 255), outline=(16, 40, 72))
    save_bg(LIVE + 'UI_M42', im)
    # game over: Load / Continue (background copy of the sprite buttons)
    im = render_bg(LIVE + 'UI_RB')
    for (x0, x1), t in (((33, 113), 'Load'), ((143, 223), 'Continue')):
        im = clean_rows(im, (131, 148), 0, cols=(x0, x1))
        im = bg_text(im, t, (x0, 130, x1, 148), size=12, face='bold', align='center', fill=(176, 176, 176),
                     outline=(88, 88, 88))
    save_bg(LIVE + 'UI_RB', im)
    # riddle carved on the plank
    im = bg_inpaint_dark(render_bg(LIVE + 'UI_G2'), (64, 145, 196, 164), thr=80, light=135)
    save_bg(LIVE + 'UI_G2', bg_text(im, RIDDLE_G2, (20, 145, 236, 162), size=13,
                                    face='narrowbi', align='center', fill=(40, 64, 48)))
    # coupon confirm footer
    im = fill_box_rows(render_bg(LIVE + 'UI_C11'), (210, 169, 240, 183), thr=95)
    save_bg(LIVE + 'UI_C11', bg_text(im, 'OK', (210, 168, 245, 183), size=11, face='sans',
                                     fill=(255, 255, 255), outline=(16, 48, 96)))

def mode_rows(img, box):
    """Flat panels: refill each row of box with that row's most common colour (lettering is a
    minority of the pixels), so no gradient is invented that quantization would band."""
    a = np.array(img.convert('RGBA'))
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        row = a[y, x0:x1]
        lum = row[:, :3].astype(int) @ np.array([3, 6, 1]) // 10
        cand = row[lum < 70] if (lum < 70).any() else row       # dark panel, never the light lettering
        vals, cnt = np.unique(cand, axis=0, return_counts=True)
        a[y, x0:x1] = vals[cnt.argmax()]
    return Image.fromarray(a)

def fill_box_rows(img, box, thr=90):
    """Lettering on a flat dark label box: refill each row of box with the most common dark
    (luminance < thr) colour of that row, leaving rows/pixels outside the box untouched."""
    a = np.array(img.convert('RGBA'))
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        row = a[y, x0:x1]
        lum = row[:, :3].astype(int) @ np.array([3, 6, 1]) // 10
        dark = row[lum < thr]
        if not len(dark):
            continue
        vals, cnt = np.unique(dark, axis=0, return_counts=True)
        c = vals[cnt.argmax()]
        # only the run of the box: between the first and last dark pixel of the row
        xs = np.nonzero(lum < thr)[0]
        a[y, x0 + xs[0]:x0 + xs[-1] + 1] = c
    return Image.fromarray(a)

RIDDLE_G2 = "The goddess's staff is red light."

def white_lettering_mask(a, box, grow=1):
    """White lettering with a dark outline inside box."""
    from PIL import ImageFilter
    r, g, b = (a[..., k].astype(int) for k in range(3))
    white = (r > 215) & (g > 215) & (b > 215)
    dark = (r * 3 + g * 6 + b) < 900
    m = np.zeros(a.shape[:2], bool); x0, y0, x1, y1 = box; m[y0:y1, x0:x1] = True
    wm = white & m
    near = np.array(Image.fromarray((wm * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    out = wm | (dark & near & m)
    out = np.array(Image.fromarray((out * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * grow + 1))) > 0
    return out & m

OB = 'OUT/RES/BG/'

def footer(im, text, box):
    """Footer hint bar (A-button icon kept): rebuild the bar after the icon, write the hint."""
    im = bg_rows(im, box, (box[2], box[2]))     # copy the clean bar column right of the old hint
    return bg_text(im, text, (box[0] + 1, box[1] - 1, box[2], box[3]), size=11, face='sans',
                   fill=(255, 255, 255), outline=(16, 48, 80))

@job
def title_screens():
    sky = [OB + 'UI_CB2', OB + 'UI_CB3', OB + 'UI_CB7']
    # coupon guide header (yellow) next to the pig
    im = bg_siblings(OB + 'UI_CB2', [s for s in sky if 'CB2' not in s], (44, 16, 230, 38))
    im = bg_text(im, 'Coupon Guide', (46, 17, 230, 37), size=14, face='arialbold', fill=(255, 214, 0),
                 outline=(96, 48, 0), shadow=(40, 24, 0))
    save_bg(OB + 'UI_CB2', im)
    im = bg_siblings(OB + 'UI_CB3', [s for s in sky if 'CB3' not in s], (12, 5, 180, 24))
    im = bg_text(im, 'View Coupons', (15, 5, 180, 23), size=14, face='arialbold', fill=(255, 255, 255),
                 outline=(24, 56, 96))
    save_bg(OB + 'UI_CB3', im)
    im = bg_siblings(OB + 'UI_CB7', [s for s in sky if 'CB7' not in s], (8, 17, 250, 34))
    im = bg_text(im, 'Enter Magic Number', (11, 17, 250, 33), size=14, face='arialbold', fill=(255, 255, 255),
                 outline=(24, 56, 96))
    im = bg_rows(im, (24, 131, 108, 146), (23, 23))
    im = bg_text(im, 'Magic Number', (26, 130, 108, 146), size=11, face='sans', fill=(255, 255, 255),
                 outline=(40, 88, 140))
    save_bg(OB + 'UI_CB7', im)
    # greyed copies of the coupon menu buttons behind the sprites
    im = render_bg(OB + 'UI_CB1')
    for (y0, y1), t in (((45, 88), 'View Coupons'), ((101, 145), 'Enter Magic No.')):
        im = clean_rows(im, (y0, y1), 9, cols=(70, 186))
        f, o = text_colours(render_bg(OB + 'UI_CB1'), (72, y0, 184, y1))
        im = bg_text(im, t, (66, y0, 190, y1), size=13, face='bold', align='center', fill=(160, 160, 160),
                     outline=(96, 96, 96))
    save_bg(OB + 'UI_CB1', im)
    im = render_bg(OB + 'UI_CB8')
    im = clean_rows(im, (152, 168), 0, cols=(203, 246))
    save_bg(OB + 'UI_CB8', bg_text(im, 'Done', (200, 151, 249, 169), size=12, face='bold', align='center',
                                   fill=(176, 176, 176), outline=(88, 88, 88)))
    save_bg(OB + 'UI_CB9', footer(render_bg(OB + 'UI_CB9'), 'OK', (22, 176, 70, 190)))
    im = bg_rows(render_bg(OB + 'UI_CB10'), (174, 130, 205, 146))
    save_bg(OB + 'UI_CB10', bg_text(im, 'OK', (176, 129, 210, 146), size=11, face='sans',
                                    fill=(255, 255, 255), outline=(16, 48, 96)))
    # entry screen: delete / OK greyed buttons
    im = render_bg(OB + 'UI_CS3')
    for (x0, x1), t in (((46, 99), 'Delete'), ((158, 210), 'OK')):
        im = clean_rows(im, (145, 174), 0, cols=(x0, x1))
        im = bg_text(im, t, (x0, 144, x1, 174), size=12, face='bold', align='center', fill=(176, 176, 176),
                     outline=(88, 88, 88))
    save_bg(OB + 'UI_CS3', im)
    # gallery / movie list headers (gridded panel) and footers
    for n, t, box, hint in (('UI_GL', 'Gallery', (84, 17, 240, 35), 'Zoom'), ('UI_MV', 'Movies', (84, 17, 240, 35), 'Play')):
        im = bg_period(render_bg(OB + n), box, 16)
        im = bg_text(im, t, (84, 17, 236, 35), size=14, face='arialbold', align='right', fill=(96, 176, 255),
                     outline=(8, 32, 64))
        im = footer(im, hint, (22, 176, 96, 190))
        save_bg(OB + n, im)
    # options sign on the title background: the English sign exists in UI_CSBG01
    im = render_bg(OB + 'UI_CS1')
    im.paste(render_bg(OB + 'UI_CSBG01').crop((0, 128, 32, 148)), (0, 128))
    save_bg(OB + 'UI_CS1', im)
    # name entry keyboards: 'Done' button
    for n in ('UI_NQ4', 'UI_NQ5', 'UI_NQ6', 'UI_NQ7', 'UI_NQ8'):
        im = render_bg(OB + n)
        im = clean_rows(im, (166, 182), 0, cols=(162, 236))
        f, o = text_colours(render_bg(OB + n), (164, 166, 236, 182))
        save_bg(OB + n, bg_text(im, 'Done', (158, 164, 240, 184), size=12, face='bold', align='center',
                                fill=f, outline=o))


def main(filt=''):
    for j in JOBS:
        if filt in j.__name__ or not filt:
            j()
            print('made', j.__name__)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '')
