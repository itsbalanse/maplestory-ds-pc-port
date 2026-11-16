"""Templates of the game's DS button icons, for the PC port's prompt renderer (port/src/hudprompts.cpp).

The port finds these icons in each finished frame by exact pixel match and redraws them for the
player's bindings. Each template is cut from
  NAME.bmp      a reference screenshot taken by the port's test scripts (256x384 BMP: top screen above
                the bottom one; `rawshot` saves one without the port's prompts), looked up in work/ui/ref/
  asset:PATH    a graphics dump of the Japanese ROM (tools/gfx.py dump -> work/gfx/PATH)
  rom:ENTRY     a BG screen of the English ROM (build/MapleStory DS (English).nds), e.g. rom:IN/RES/BG/UI_M53
  cell:ENTRY:N  OBJ cell N of a cell set of the English ROM, rect in the cell's own (OAM) coordinates
The English ROM's archive is unpacked to build/en_nx on first use (again when the ROM is newer).

usage: python tools/prompt_templates.py          -> port/src/prompt_templates.inc
       python tools/prompt_templates.py --empty  -> port/src/prompt_templates_none.inc (no templates: the
                                                    port builds without the cut game graphics, icons stay DS)
"""
import os, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, 'work', 'ui', 'ref')

# Colour sets of the DS icons: outline, face, face highlight, ink (label), shade 1, shade 2
BLUE = dict(outline=0x001828, face=0xfbfbfb, light=0xc3d3d3, ink=0x083038, shade1=0x598292, shade2=0x285161)
GRAY = dict(outline=0x101010, face=0xfbfbfb, light=0xcbd3db, ink=0x282820, shade1=0x717982, shade2=0x414951)
SMALL = dict(outline=0x183049, face=0xfbfbfb, light=0xbacbcb, ink=0x183049, shade1=0x71a2b2, shade2=0x305161)
def emu(c):
    """A colour picked from a tools/gfx.py render, as the emulator shows it."""
    return sum(((c >> sh & 255) >> 3 << 3 | (c >> sh & 255) >> 6) << sh for sh in (0, 8, 16))


MAP = dict(outline=0x003051, face=0xfbfbfb, light=0xaadbfb, ink=0x003051, shade1=0x61a2d3, shade2=0x497182)
MAP_COLOURS = [0x003051, 0x61a2d3, 0xaadbfb, 0xebebeb, 0xfbfbfb, 0x497182]

# DS console illustration (UI_PRS): white keys with the orange highlight, pulsing like the original
PRS_PALE = dict(outline=emu(0xce5a29), face=emu(0xffffff), light=emu(0xffc6a5), ink=emu(0x292929),
                shade1=emu(0xffc6a5), shade2=emu(0xffc6a5))
PRS_DARK = dict(outline=emu(0x180808), face=emu(0xffffff), light=emu(0xffc6a5), ink=emu(0x292929),
                shade1=emu(0xffc6a5), shade2=emu(0xff8429))
DIALOG = dict(outline=0x0c344d, face=0xffffff, light=0xb6b6b6, ink=0x000000, shade1=0xb6b6b6, shade2=0x5d5d5d)

# name, reference shot, screen (0 top, 1 bottom), rect (x0, y0, x1, y1), role, style,
# mode: 'rect' = every pixel of the rect must match (static backgrounds; the rect is cleared to
#        `erase` before drawing) or a set of colours = only those pixels belong to the icon
#        (icons over moving backgrounds; the new icon is drawn over the old one).
TEMPLATES = [
    dict(name='skill_l', ref='hud.bmp', screen=1, rect=(9, 5, 20, 17), role='L', style=BLUE, mode='rect', erase=0x004969),
    dict(name='skill_y', ref='hud.bmp', screen=1, rect=(50, 5, 61, 17), role='Y', style=BLUE, mode='rect', erase=0x004969),
    dict(name='skill_x', ref='hud.bmp', screen=1, rect=(91, 5, 102, 17), role='X', style=BLUE, mode='rect', erase=0x004969),
    dict(name='skill_ul', ref='hud.bmp', screen=1, rect=(136, 4, 155, 17), role='UpL', style=GRAY, mode='rect', erase=0x384149),
    dict(name='skill_uy', ref='hud.bmp', screen=1, rect=(175, 4, 195, 17), role='UpY', style=GRAY, mode='rect', erase=0x384149),
    dict(name='skill_ux', ref='hud.bmp', screen=1, rect=(215, 4, 235, 17), role='UpX', style=GRAY, mode='rect', erase=0x384149),
    dict(name='dialog_a', ref='dialog.bmp', screen=0, rect=(235, 116, 246, 127), role='A', menu=True, style=DIALOG,
         mode=[0x0c344d, 0xb6b6b6, 0x5d5d5d, 0xffffff, 0x000000], align='right'),
    # START / SELECT buttons on the bottom HUD: keep the button, replace its lettering
    dict(name='select_on', ref='asset:IN/RES/BG/UI_MM1.png', screen=1, rect=(141, 48, 172, 62), role='Select', style=BLUE,
         mode='text', ink=0x003851, fill=0xfbfbfb, outside=(0x003851, 0x004161, 0x004969)),
    dict(name='start_on', ref='hud_free.bmp', screen=1, rect=(195, 48, 226, 62), role='Start', style=BLUE,
         mode='text', ink=0x003851, fill=0xfbfbfb, outside=(0x003851, 0x004161, 0x004969)),
    # the small A in menu bars ("A OK", "A Play") and on dialog buttons; screen 2 = either screen.
    # compact: followed by a word, so long key names become symbols (enter, shift, ...)
    dict(name='bar_a', ref='asset:OUT/RES/BG/UI_CB9.png', screen=2, rect=(10, 177, 21, 189), role='A', menu=True,
         style=SMALL, mode=[0x183049, 0x71a2b2, 0xbacbcb, 0xfbf3fb, 0xebe3eb, 0xfbfbfb, 0x305161], compact=True, shape=True),
    dict(name='button_a', ref='asset:OUT/RES/BG/UI_CB10.png', screen=2, rect=(163, 133, 174, 145), role='A', menu=True,
         style=SMALL, mode=[0x183049, 0x69829a, 0xbad3db, 0xfbfbfb, 0xdbe3eb, 0x003851, 0x304961], compact=True, shape=True),
    dict(name='select_off', ref='hud.bmp', screen=1, rect=(141, 48, 172, 62), role='Select', style=BLUE,
         mode='text', ink=0x003851, fill=0x205171, outside=(0x003851, 0x004161, 0x004969)),
    dict(name='start_off', ref='hud.bmp', screen=1, rect=(195, 48, 226, 62), role='Start', style=BLUE,
         mode='text', ink=0x003851, fill=0x205171, outside=(0x003851, 0x004161, 0x004969)),
    # orange START / SELECT while touched (UI_MS cells 71-73; 73 = 71 moved left for the MINIMAP layout)
    dict(name='start_press', ref='cell:IN/UI_MS:72', screen=1, rect=(67, -49, 98, -33), role='Start', style=BLUE,
         mode='text', ink=0xfbfbfb, fill=0xfb9a51, shadow=0xba7149, box=(2, 3, 29, 11), ty=4, key=0xfb9a51),
    dict(name='select_press', ref='cell:IN/UI_MS:71', screen=1, rect=(13, -49, 44, -33), role='Select', style=BLUE,
         mode='text', ink=0xfbfbfb, fill=0xfb9a51, shadow=0xba7149, box=(2, 4, 29, 12), ty=5, key=0xfb9a51),
    # Skills screen (UI_M3, top screen): the HUD's slots in the menu's palette
    dict(name='menu_skill_l', ref='rom:IN/RES/BG/UI_M3', screen=0, rect=(22, 30, 33, 42), role='L', style=BLUE,
         mode='rect', erase=0x004969),
    dict(name='menu_skill_y', ref='rom:IN/RES/BG/UI_M3', screen=0, rect=(64, 30, 75, 42), role='Y', style=BLUE,
         mode='rect', erase=0x004969),
    dict(name='menu_skill_x', ref='rom:IN/RES/BG/UI_M3', screen=0, rect=(106, 30, 117, 42), role='X', style=BLUE,
         mode='rect', erase=0x004969),
    dict(name='menu_skill_ul', ref='rom:IN/RES/BG/UI_M3', screen=0, rect=(20, 97, 39, 110), role='UpL', style=GRAY,
         mode='rect', erase=0x384149),
    dict(name='menu_skill_uy', ref='rom:IN/RES/BG/UI_M3', screen=0, rect=(61, 97, 81, 110), role='UpY', style=GRAY,
         mode='rect', erase=0x384149),
    dict(name='menu_skill_ux', ref='rom:IN/RES/BG/UI_M3', screen=0, rect=(103, 97, 123, 110), role='UpX', style=GRAY,
         mode='rect', erase=0x384149),
    # Map screens (UI_M52-55) and their hint picture (BG8117): "(R) Area Info (X) Map". Each screen shades the
    # icons with its own palette, so each gets its own template (the icon pixels of UI_M53's, in its colours).
    dict(name='map_r', ref='rom:IN/RES/BG/UI_M53', screen=0, rect=(143, 174, 154, 184), role='R', style=MAP,
         mode=MAP_COLOURS, compact=True),
    dict(name='map_x', ref='rom:IN/RES/BG/UI_M53', screen=0, rect=(206, 174, 217, 184), role='X', style=MAP,
         mode=MAP_COLOURS, compact=True),
] + [
    dict(name='map_%s_%s' % (k, bg.lower()), ref='rom:IN/RES/BG/' + bg, screen=0, rect=rect, role=k.upper(), style=MAP,
         mode='opaque', maskfrom='map_' + k, compact=True, key='saturated')
    for bg in ('UI_M52', 'UI_M54', 'UI_M55', 'BG8117')
    for k, rect in (('r', (143, 174, 154, 184)), ('x', (206, 174, 217, 184)))
] + [
    # DS console with an arrow at one button (UI_PRS cells 1-16, odd = pale, even = dark highlight):
    # the bound key or button is drawn over the highlighted DS button
    dict(name='console_%d' % cell, ref='cell:IN/UI_PRS:%d' % cell, screen=2, role=role, menu=role in ('A', 'B'),
         rect=(cx - 8, cy - 8, cx + 9, cy + 9), at=(cx + 0.5, cy + 0.5), mode='opaque', compact=True,
         style=PRS_PALE if cell % 2 else PRS_DARK, key=emu(0xffc6a5 if cell % 2 else 0xff8429))
    for cells, role, cx, cy in [((1, 2), 'B', 60, 36), ((3, 4), 'A', 70, 26), ((5, 6), 'Up', -62, 22),
                                ((7, 8), 'Down', -62, 37), ((9, 10), 'Left', -69, 29), ((11, 12), 'Right', -55, 29),
                                ((13, 14), 'R', 74, -8), ((15, 16), 'L', -74, -8)]
    for cell in cells
]
# hint animations (IN/RES/HL/8xxx, drawn in 3D): the lit d-pad arm / face button of the controller picture.
# Only the highlight's core colours are matched (the outline shade differs per class's hint set).
HINT_PAD = [0x00f3fb, 0x717171, 0xdbdbdb, 0xfbfbfb, 0xaaaaaa, 0xb2b2b2, 0xcbcbcb]  # the picture (shared by all sets)
HINT_PALE = [0xfbba92, 0xe3aa92, 0xcb9a61, 0xcbaa69, 0xe3ba92]
HINT_DARK = [0xfb8228]
TEMPLATES += [
    dict(name='hint_%s_%s' % (role.lower(), tone), ref='cell:IN/RES/HL/%s' % cell, screen=2, role=role, rect=rect,
         mode=(HINT_PALE if tone == 'pale' else HINT_DARK) + HINT_PAD, gpu3d=True, compact=True, key=HINT_PALE[0] if tone == 'pale' else HINT_DARK[0],
         style=PRS_PALE if tone == 'pale' else PRS_DARK,
         occluders=[] if tone == 'pale' else ['IN/RES/HL/' + c for c in stars],
         at={'B': (39.5, 82.5), 'A': (48.5, 72.5)}.get(role, ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)))
    for role, rect, pale, dark, stars in [
        # (pale cell, dark cell, cells drawn over the dark one: star bursts and the same frame of the other
        #  classes' hint sets, whose highlight shades differ in a few pixels)
        ('Right', (-37, 68, -26, 77), '8100:1', '8100:3', ['8100:2', '8204:3', '8300:4', '8400:3']),
        ('Up', (-44, 58, -35, 69), '8100:20', '8102:10', ['8100:21', '8102:9', '8302:11', '8402:10']),
        ('Down', (-44, 76, -35, 87), '8102:32', '8102:34', ['8102:33', '8302:26', '8402:34']),
        # face buttons: wide enough to take in the neighbouring buttons (a lit A and a lit B look alike)
        ('B', (28, 66, 50, 88), '8101:1', '8101:3', ['8201:4', '8301:4', '8401:3']),
        ('A', (34, 62, 55, 84), '8105:5', '8106:7', ['8306:7', '8407:7'])]
    for tone, cell in (('pale', pale), ('dark', dark))
]
# list paging tabs (IN/UI_US1 51-53 = L lit/light/grey, 54-56 = R; the Hint List draws them in 3D) and the small
# slot tags on skills (41 = L, 43 = X, 45 = Y); rects in OAM coordinates of each cell
TAB_GREY = dict(outline=0x182841, face=0xd3d3d3, light=0xfbfbfb, ink=0x616169, shade1=0x9a9a9a, shade2=0x797979)
TEMPLATES += [
    dict(name='tab_%d' % cell, ref='cell:IN/UI_US1:%d' % cell, screen=2, role=role, rect=(-8, -16, 8, 0), mode='opaque',
         compact=True, style=TAB_GREY if cell in (53, 56) else PRS_DARK, key='saturated')
    for cell, role in ((51, 'L'), (52, 'L'), (53, 'L'), (54, 'R'), (55, 'R'), (56, 'R'))
] + [
    dict(name='slot_tag_%d' % cell, ref='cell:IN/UI_US1:%d' % cell, screen=2, role=role, rect=rect, mode='opaque',
         compact=True, style=PRS_DARK, key='saturated')
    for cell, role, rect in ((41, 'L', (-89, -46, -73, -38)), (43, 'X', (-25, -35, -17, -27)), (45, 'Y', (-31, -29, -23, -21)))
]
# drawn in 3D as well (the prologue book may be; the Hint List is): those templates in 3D colours too
TEMPLATES += [dict(t, name=t['name'] + '_3d', gpu3d=True) for t in TEMPLATES
              if t['name'].startswith(('console_', 'tab_', 'slot_tag_'))]

def to_emu(im):
    """Colours of a tools/gfx.py render (c5<<3|c5>>2) as the emulator shows them (c5<<3|c5>>3)."""
    r, g, b, a = im.split()
    return Image.merge('RGBA', [c.point(lambda v: (v >> 3) << 3 | (v >> 3) >> 3) for c in (r, g, b)] + [a])


def en_gfx():
    """tools/gfx.py reading the English ROM's graphics (unpacked to build/en_nx)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gfx
    rom = os.path.join(ROOT, 'build', 'MapleStory DS (English).nds')
    out = os.path.join(ROOT, 'build', 'en_nx')
    stamp = os.path.join(out, '.stamp')
    if not os.path.exists(stamp) or os.path.getmtime(stamp) < os.path.getmtime(rom):
        from ndsfs import NDS
        from nxarc import NxArc
        nds = NDS(rom)
        os.makedirs(out, exist_ok=True)
        arc = os.path.join(out, 'RESOURCE.NXARC')
        open(arc, 'wb').write(nds.read(nds.files['RESOURCE.NXARC']))
        a = NxArc(arc, os.path.join(ROOT, 'extracted', 'arm9_dec.bin'))  # file names: the ROMs share the charmap
        for name, off, sz in a.entries:
            fp = os.path.join(out, name)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, 'wb').write(a.d[off:off + sz])
        open(stamp, 'w').write(rom)
    gfx.NX = out
    return gfx


def render_screen(entry):
    """'IN/RES/BG/UI_M53' -> RGBA image of that BG screen of the English ROM."""
    gfx = en_gfx()
    p = os.path.join(gfx.NX, entry)
    return gfx.NSCR(gfx.load(p + '.NSCR')).render(gfx.NCGR(gfx.load(p + '.NCGR')),
                                                  gfx.NCLR(gfx.load(gfx.find_palette(p + '.NSCR')))).convert('RGBA')


def to_3d(c):
    """An emulator colour (2D: c5<<3|c5>>3) as the 3D engine shows the same 5-bit colour."""
    out = 0
    for sh in (0, 8, 16):
        c5 = (c >> sh & 255) >> 3
        c6 = c5 * 2 + 1 if c5 else 0
        out |= (c6 << 2 | c6 >> 4) << sh
    return out


def render_cell(spec):
    """'IN/UI_MS:72' -> (RGBA image of cell 72 of cell set IN/UI_MS of the English ROM, x and y of the cell origin)."""
    gfx = en_gfx()
    name, idx = spec.rsplit(':', 1)
    path = os.path.join(gfx.NX, name + '.NCER')
    nc = gfx.NCER(gfx.load(path))
    cg = gfx.NCGR(gfx.load(gfx.ncer_charfile(path)))
    pl = gfx.NCLR(gfx.load(gfx.find_palette(path)))
    x0, y0, x1, y1 = nc.cell_bounds(int(idx))
    return nc.render(int(idx), cg, pl).convert('RGBA'), -x0, -y0


ROLES = ['A', 'B', 'X', 'Y', 'L', 'R', 'Up', 'Down', 'Left', 'Right', 'Start', 'Select', 'UpL', 'UpY', 'UpX']


def main():
    out = ['// generated by tools/prompt_templates.py - do not edit', '#pragma once', '#include <cstdint>', '',
           'struct PromptStyle { uint32_t outline, face, light, ink, shade1, shade2; };',
           'struct PromptTemplate {',
           '    const char* name; int screen; int w, h; int role; bool menu; PromptStyle style;',
           '    bool rect; uint32_t erase;      // rect: whole rect matches and is cleared to `erase`',
           '    const uint32_t* px; const uint8_t* mask; int anchor;  // anchor: index of a masked pixel',
           '    int align;                      // 0 centre, 1 right-align the new icon with the old one',
           '    bool text; uint32_t ink, fill;  // text: keep the button, redraw only its 5-pixel lettering',
           '    bool compact;                   // little room: long key names become symbols',
           '    bool shape;                     // match by shape in any palette (mask = brightness rank)',
           '    int cx2, cy2;                   // centre of the new icon in the template, in half pixels',
           '    int box[4]; int ty; uint32_t shadow;  // text: area to clear, top of the lettering, its drop shadow (0 none)',
           '};', '']
    entries = []
    masks = {}
    empty = '--empty' in sys.argv
    for t in ([] if empty else TEMPLATES):
        x0, y0, x1, y1 = t['rect']
        ox = oy = 0
        if t['ref'].startswith('asset:'):
            # graphics dump (tools/gfx.py)
            im = Image.open(os.path.join(ROOT, 'work', 'gfx', t['ref'][6:])).convert('RGBA')
        elif t['ref'].startswith('rom:'):
            im = render_screen(t['ref'][4:])
        elif t['ref'].startswith('cell:'):
            # one OBJ cell straight from the ROM data; rect in the cell's own coordinates (OAM x, y)
            im, ox, oy = render_cell(t['ref'][5:])
        else:
            im = Image.open(os.path.join(REF, t['ref'])).convert('RGBA')
            oy = 192 * min(t['screen'], 1)
        if not t['ref'].endswith('.bmp'):
            im = to_emu(im)
        px, mask = [], []
        for y in range(y0, y1):
            for x in range(x0, x1):
                r, g, b, a = im.getpixel((x + ox, y + oy))
                c = r << 16 | g << 8 | b
                px.append(c)
                if a < 128:
                    mask.append(0)  # transparent part of a cell: anything may show through
                elif t.get('shape'):
                    # shape: the mask holds the colour's rank by brightness (1 = darkest), so the icon can be
                    # recognised in any palette (same rank -> same colour, ranks keep their light/dark order)
                    ranked = sorted(t['mode'], key=lambda v: ((v >> 16) * 3 + (v >> 8 & 255) * 6 + (v & 255), v))
                    mask.append(ranked.index(c) + 1 if c in t['mode'] else 0)
                else:
                    mask.append(1 if t['mode'] in ('rect', 'text', 'opaque') or c in t['mode'] else 0)
        if 'outside' in t:  # background around a rounded button (reached from the rect's edge): not part of it
            w_ = x1 - x0
            todo = [i for i in range(len(px)) if (i % w_ in (0, w_ - 1) or i // w_ in (0, y1 - y0 - 1)) and px[i] in t['outside']]
            while todo:
                i = todo.pop()
                if not mask[i] or px[i] not in t['outside']:
                    continue
                mask[i] = 0
                x_, y_ = i % w_, i // w_
                todo += [j for j, ok in ((i - 1, x_ > 0), (i + 1, x_ < w_ - 1), (i - w_, y_ > 0), (i + w_, y_ < y1 - y0 - 1)) if ok]
        for occ in t.get('occluders', ()):  # pixels another frame draws over (a star burst): not matched
            oim, oox, ooy = render_cell(occ)
            oim = to_emu(oim)
            for i in range(len(px)):
                r_, g_, b_, a_ = oim.getpixel((x0 + i % (x1 - x0) + oox, y0 + i // (x1 - x0) + ooy))
                if (r_ << 16 | g_ << 8 | b_) != px[i] or a_ < 128:
                    mask[i] = 0
        if 'maskfrom' in t:  # the icon pixels of another template, in this template's colours
            mask = [min(m, 1) * a for m, a in zip(masks[t['maskfrom']], mask)]
        masks[t['name']] = mask
        assert sum(mask) > 10, t['name']
        # anchor: the first masked pixel whose colour is least common in the template (cheap scan key),
        # or of colour `key` (a colour that is rare on screen, e.g. a highlight)
        from collections import Counter
        cnt = Counter(c for c, m in zip(px, mask) if m)
        if t.get('key') == 'saturated':  # the most colourful colour of the icon (white and grey are everywhere)
            sat = lambda c: max(c >> 16, c >> 8 & 255, c & 255) - min(c >> 16, c >> 8 & 255, c & 255)
            best = max((c for c, m in zip(px, mask) if m and cnt[c] >= 3), key=lambda c: (sat(c), -cnt[c]))
            anchor = px.index(best)
        elif 'key' in t:
            anchor = next(i for i, (c, m) in enumerate(zip(px, mask)) if m and c == t['key'])
        else:
            anchor = min((cnt[c], i) for i, (c, m) in enumerate(zip(px, mask)) if m)[1]
        if t.get('gpu3d'):
            # drawn through the 3D engine (hint animations): 5-bit colours widened to 6 bits as c*2+1
            px = [to_3d(c) for c in px]
        n = t['name']
        w, h = x1 - x0, y1 - y0
        # where the new icon goes: `at` (x, y in rect coordinates) or the middle of the rect
        cx2, cy2 = (round(2 * (t['at'][0] - x0)), round(2 * (t['at'][1] - y0))) if 'at' in t else (w, h)
        box = t.get('box', (2, 3, w - 2, h - 3))
        ty = t.get('ty', (h - 5) // 2 - 1)
        out.append('static const uint32_t kTpl_%s_px[] = {%s};' % (n, ', '.join('0x%06x' % c for c in px)))
        out.append('static const uint8_t kTpl_%s_mask[] = {%s};' % (n, ', '.join(map(str, mask))))
        s = t['style']
        entries.append('    {"%s", %d, %d, %d, %d, %s, {0x%06x, 0x%06x, 0x%06x, 0x%06x, 0x%06x, 0x%06x}, %s, 0x%06x, kTpl_%s_px, kTpl_%s_mask, %d, %d, %s, 0x%06x, 0x%06x, %s, %s, %d, %d, {%d, %d, %d, %d}, %d, 0x%06x},' % (
            n, t['screen'], x1 - x0, y1 - y0, ROLES.index(t['role']), 'true' if t.get('menu') else 'false',
            s['outline'], s['face'], s['light'], s['ink'], s['shade1'], s['shade2'],
            'true' if t['mode'] == 'rect' else 'false', t.get('erase', 0), n, n, anchor,
            1 if t.get('align') == 'right' else 0, 'true' if t['mode'] == 'text' else 'false', t.get('ink', 0), t.get('fill', 0),
            'true' if t.get('compact') else 'false', 'true' if t.get('shape') else 'false',
            cx2, cy2, *box, ty, t.get('shadow', 0)))
    out += ['', 'static const PromptTemplate kPromptTemplates[] = {'] + entries + ['};']
    path = os.path.join(ROOT, 'port', 'src', 'prompt_templates_none.inc' if empty else 'prompt_templates.inc')
    open(path, 'w', newline='\n').write('\n'.join(out) + '\n')
    print('wrote', path, len(entries), 'templates')


if __name__ == '__main__':
    main()
