"""Decode a GPU state dump written by the port's `gpudump NAME` test command (NAME.gpu).

usage:
  python tools/gpudump.py NAME.gpu OUTDIR [x0 y0 x1 y1 screen]
Writes one PNG per enabled BG layer and an OBJ sheet per screen, and prints the OAM entries
(and BG tiles) that cover the given rectangle (screen 0 = top, 1 = bottom).
"""
import os, struct, sys
from PIL import Image


def bgr555(v):
    r, g, b = v & 31, (v >> 5) & 31, (v >> 10) & 31
    return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2, 255)


OBJ_SIZES = {(0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
             (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
             (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64)}


class Engine:
    pass


def load(path):
    d = open(path, 'rb').read()
    assert d[:6] == b'MSGPU1'
    p = 8
    pow_, = struct.unpack_from('<I', d, p); p += 4
    engines = []
    for i in range(2):
        e = Engine()
        e.num = i
        e.dispcnt, = struct.unpack_from('<I', d, p); p += 4
        e.bgcnt = struct.unpack_from('<4H', d, p); p += 8
        e.bgx = struct.unpack_from('<4H', d, p); p += 8
        e.bgy = struct.unpack_from('<4H', d, p); p += 8
        engines.append(e)
    pal = d[p:p + 2048]; p += 2048
    oam = d[p:p + 2048]; p += 2048
    abg = d[p:p + 0x80000]; p += 0x80000
    aobj = d[p:p + 0x40000]; p += 0x40000
    bbg = d[p:p + 0x20000]; p += 0x20000
    bobj = d[p:p + 0x20000]; p += 0x20000
    for e, bg, obj, off in ((engines[0], abg, aobj, 0), (engines[1], bbg, bobj, 0x400)):
        e.bgvram, e.objvram = bg, obj
        e.bgpal = [bgr555(struct.unpack_from('<H', pal, off + i * 2)[0]) for i in range(256)]
        e.objpal = [bgr555(struct.unpack_from('<H', pal, off + 0x200 + i * 2)[0]) for i in range(256)]
        e.oam = oam[off:off + 0x400]
    # POWCNT1 bit 15: engine A on the top screen
    top = 0 if pow_ & 0x8000 else 1
    engines[0].screen = 0 if top == 0 else 1
    engines[1].screen = 1 - engines[0].screen
    return engines


def objs(e):
    out = []
    for i in range(128):
        a0, a1, a2 = struct.unpack_from('<3H', e.oam, i * 8)
        rs = a0 >> 8 & 1
        if not rs and a0 >> 9 & 1:
            continue  # disabled
        shape, size = a0 >> 14, a1 >> 14
        if shape == 3:
            continue
        w, h = OBJ_SIZES[(shape, size)]
        x = a1 & 0x1FF
        if x >= 256: x -= 512
        y = a0 & 0xFF
        if y >= 192: y -= 256
        out.append(dict(i=i, x=x, y=y, w=w, h=h, tile=a2 & 0x3FF, pal=a2 >> 12, prio=a2 >> 10 & 3,
                        col256=a0 >> 13 & 1, mode=a0 >> 10 & 3, rs=rs, hf=a1 >> 12 & 1 if not rs else 0,
                        vf=a1 >> 13 & 1 if not rs else 0, a=(a0, a1, a2)))
    return out


def obj_tile_addr(e, tile, col256):
    if e.dispcnt & 0x10:  # 1D mapping
        bound = (e.dispcnt >> 20) & 3
        return tile * (32 << bound)
    return tile * 32


def render_obj(e, o):
    img = Image.new('RGBA', (o['w'], o['h']))
    px = img.load()
    base = obj_tile_addr(e, o['tile'], o['col256'])
    tw = o['w'] // 8
    bpt = 64 if o['col256'] else 32
    for ty in range(o['h'] // 8):
        for tx in range(tw):
            if e.dispcnt & 0x10:
                t = base + (ty * tw + tx) * bpt
            else:
                t = base + (ty * 32 + tx * (2 if o['col256'] else 1)) * 32
            for yy in range(8):
                for xx in range(8):
                    if o['col256']:
                        c = e.objvram[(t + yy * 8 + xx) & 0x3FFFF]
                        col = e.objpal[c]
                    else:
                        b = e.objvram[(t + yy * 4 + xx // 2) & 0x3FFFF]
                        c = (b >> 4) if xx & 1 else (b & 15)
                        col = e.objpal[o['pal'] * 16 + c]
                    if c:
                        X, Y = tx * 8 + xx, ty * 8 + yy
                        if o['hf']: X = o['w'] - 1 - X
                        if o['vf']: Y = o['h'] - 1 - Y
                        px[X, Y] = col
    return img


def bg_layer(e, n):
    """Render text BG n as a 256x192 screen image plus a per-pixel (map entry address) table."""
    cnt = e.bgcnt[n]
    charbase = ((cnt >> 2) & 15) * 0x4000
    scrbase = ((cnt >> 8) & 31) * 0x800
    if e.num == 0:
        charbase += ((e.dispcnt >> 24) & 7) * 0x10000
        scrbase += ((e.dispcnt >> 27) & 7) * 0x10000
    col256 = cnt >> 7 & 1
    size = cnt >> 14
    mw, mh = (256, 512, 256, 512)[size], (256, 256, 512, 512)[size]
    img = Image.new('RGBA', (256, 192))
    px = img.load()
    where = {}
    for sy in range(192):
        for sx in range(256):
            X = (sx + e.bgx[n]) % mw
            Y = (sy + e.bgy[n]) % mh
            blk = (X // 256) + (Y // 256) * (2 if mw == 512 else 1)
            ma = scrbase + blk * 0x800 + ((Y % 256) // 8) * 64 + ((X % 256) // 8) * 2
            ent = struct.unpack_from('<H', e.bgvram, ma % len(e.bgvram))[0]
            tile, hf, vf, pal = ent & 0x3FF, ent >> 10 & 1, ent >> 11 & 1, ent >> 12
            xx, yy = X % 8, Y % 8
            if hf: xx = 7 - xx
            if vf: yy = 7 - yy
            if col256:
                c = e.bgvram[(charbase + tile * 64 + yy * 8 + xx) % len(e.bgvram)]
                col = e.bgpal[c]
            else:
                b = e.bgvram[(charbase + tile * 32 + yy * 4 + xx // 2) % len(e.bgvram)]
                c = (b >> 4) if xx & 1 else (b & 15)
                col = e.bgpal[pal * 16 + c]
            if c:
                px[sx, sy] = col
            where[(sx, sy)] = (ma, ent, charbase + tile * (64 if col256 else 32))
    return img, where


def main():
    path, outdir = sys.argv[1], sys.argv[2]
    rect = tuple(map(int, sys.argv[3:8])) if len(sys.argv) >= 8 else None
    os.makedirs(outdir, exist_ok=True)
    for e in load(path):
        name = 'top' if e.screen == 0 else 'bot'
        print('engine %s (%s): DISPCNT=%08x BGCNT=%s X=%s Y=%s' % ('AB'[e.num], name, e.dispcnt,
              [hex(v) for v in e.bgcnt], e.bgx, e.bgy))
        mode = e.dispcnt & 7
        for n in range(4):
            if not e.dispcnt >> (8 + n) & 1:
                continue
            if n == 0 and e.num == 0 and e.dispcnt & 8:
                print('  BG0: 3D'); continue
            if mode >= 3 and n >= 2 or (mode in (1, 2) and n == 3) or (mode == 2 and n == 2):
                print('  BG%d: affine/extended (not rendered)' % n); continue
            img, where = bg_layer(e, n)
            img.save(os.path.join(outdir, '%s_bg%d.png' % (name, n)))
            if rect and rect[4] == e.screen:
                seen = {}
                for y in range(rect[1], rect[3]):
                    for x in range(rect[0], rect[2]):
                        ma, ent, ta = where[(x, y)]
                        seen.setdefault(ma, (x // 8 * 8, y // 8 * 8, ent, ta))
                print('  BG%d tiles in rect:' % n)
                for ma, (x, y, ent, ta) in sorted(seen.items(), key=lambda kv: (kv[1][1], kv[1][0])):
                    print('    map %05x at ~(%d,%d): entry %04x tiledata %05x' % (ma, x, y, ent, ta))
        sheet = Image.new('RGBA', (256, 192))
        for o in sorted(objs(e), key=lambda o: -o['prio']):
            if o['rs']:
                continue
            sheet.alpha_composite(render_obj(e, o), (max(0, o['x']), max(0, o['y']))) if o['x'] >= 0 and o['y'] >= 0 else None
        sheet.save(os.path.join(outdir, '%s_obj.png' % name))
        for o in objs(e):
            hit = rect and rect[4] == e.screen and o['x'] < rect[2] and o['x'] + o['w'] > rect[0] and \
                  o['y'] < rect[3] and o['y'] + o['h'] > rect[1]
            if hit or not rect:
                print('  OBJ %3d at (%d,%d) %dx%d tile %d pal %d prio %d %s' % (
                    o['i'], o['x'], o['y'], o['w'], o['h'], o['tile'], o['pal'], o['prio'],
                    'tileaddr %05x' % obj_tile_addr(e, o['tile'], o['col256'])))


if __name__ == '__main__':
    main()
