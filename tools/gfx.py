"""Readers/writers for the Nitro 2D graphics formats used by MapleStory DS.

None of the files in RESOURCE.NXARC are compressed; they are plain Nitro G2D files:
  NCLR (RLCN)  palette               -> NCLR
  NCGR (RGCN)  character (tile) data -> NCGR, char_fmt 0 = 8x8 tiles
  NCBR (RGCN)  same container, char_fmt 1 = "bitmap" chars: each OAM's pixels are
               stored as one linear w*h bitmap (used by every cell set here)
  NSCR (RCSN)  BG screen (tilemap)   -> NSCR
  NCER (RECN)  OBJ cell banks        -> NCER
  NANR (RNAN)  cell animations       -> NANR (read only; never modified)

usage:
  python tools/gfx.py dump [subdir-filter]   render everything to work/gfx/<dir>/<name>[_cNN].png
  python tools/gfx.py info <file>
"""
import os, sys, struct
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NX = os.path.join(ROOT, 'extracted', 'nx')

OBJ_SIZES = {  # (shape, size) -> (w, h)
    (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
    (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
    (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
}

def bgr555(v):
    r, g, b = v & 31, (v >> 5) & 31, (v >> 10) & 31
    return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2)

def to_bgr555(rgb):
    r, g, b = rgb[:3]
    return (r >> 3) | (g >> 3) << 5 | (b >> 3) << 10

def _sections(d):
    """Yield (magic, offset, size) for each section of a Nitro file."""
    hsz, nsec = struct.unpack_from('<HH', d, 0xC)
    p = hsz
    for _ in range(nsec):
        if p + 8 > len(d):
            break
        mg = d[p:p + 4]; sz = struct.unpack_from('<I', d, p + 4)[0]
        yield mg, p, sz
        p += sz

def _fix_total(out):
    struct.pack_into('<I', out, 8, len(out))


class NCLR:
    def __init__(self, d):
        self.raw = bytearray(d)
        for mg, p, sz in _sections(d):
            if mg == b'TTLP':
                self.sec = p
                self.depth, = struct.unpack_from('<H', d, p + 8)
                dsz, doff = struct.unpack_from('<II', d, p + 0x10)
                self.dofs = p + 8 + doff
                self.dsz = dsz
        n = self.dsz // 2
        # some files declare a size larger than the data actually present
        n = min(n, (len(d) - self.dofs) // 2)
        self.colors = [bgr555(v) for v in struct.unpack_from('<%dH' % n, d, self.dofs)]
        self.bpp = 4 if self.depth == 3 else 8

    def palette(self, bank=0):
        """256-entry RGB list; for 4bpp the 16 colours of `bank` come first."""
        if self.bpp == 4:
            c = self.colors[bank * 16:bank * 16 + 16]
        elif len(self.colors) > 256:  # extended palette set: one 256-colour slot per OAM palette no.
            c = self.colors[bank * 256:bank * 256 + 256]
        else:
            c = self.colors[:256]
        return (c + [(0, 0, 0)] * 256)[:256]

    def build(self):
        out = bytearray(self.raw)
        for i, c in enumerate(self.colors):
            struct.pack_into('<H', out, self.dofs + i * 2, to_bgr555(c))
        return bytes(out)


class NCGR:
    """Character data. Pixels are kept as a flat bytearray of palette indices."""
    def __init__(self, d):
        self.raw = bytearray(d)
        for mg, p, sz in _sections(d):
            if mg == b'RAHC':
                self.sec = p
                self.th, self.tw, depth, self.mapping, self.char_fmt, dsz, doff = struct.unpack_from('<HHIIIII', d, p + 8)
                self.dofs = p + 8 + doff
                self.dsz = dsz
        self.bpp = 4 if depth == 3 else 8
        data = d[self.dofs:self.dofs + self.dsz]
        if self.bpp == 8:
            self.px = bytearray(data)
        else:
            px = bytearray(len(data) * 2)
            px[0::2] = bytes(b & 15 for b in data)
            px[1::2] = bytes(b >> 4 for b in data)
            self.px = px

    @property
    def tiled(self):
        return self.char_fmt == 0

    def pack(self):
        if self.bpp == 8:
            return bytes(self.px)
        p = self.px
        return bytes((p[i] & 15) | (p[i + 1] & 15) << 4 for i in range(0, len(p), 2))

    def build(self):
        data = self.pack()
        out = bytearray(self.raw[:self.dofs]) + data + self.raw[self.dofs + self.dsz:]
        struct.pack_into('<I', out, self.dofs - 8, len(data))  # RAHC data size
        delta = len(data) - self.dsz
        struct.pack_into('<I', out, self.sec + 4, struct.unpack_from('<I', out, self.sec + 4)[0] + delta)
        _fix_total(out)
        return bytes(out)

    # --- tile helpers (char_fmt 0) ---
    def tile(self, idx):
        """64 palette indices of 8x8 tile `idx` (in units of whole tiles of this bpp)."""
        return self.px[idx * 64:idx * 64 + 64]

    def to_image(self, pal, width_tiles=None):
        n = len(self.px) // 64
        tw = width_tiles or (self.tw if self.tw not in (0, 0xffff) else 16)
        th = (n + tw - 1) // tw
        im = Image.new('P', (tw * 8, th * 8))
        im.putpalette(sum(pal, ()))
        for t in range(n):
            tx, ty = (t % tw) * 8, (t // tw) * 8
            if self.tiled:
                blk = Image.frombytes('P', (8, 8), bytes(self.tile(t)))
                im.paste(blk, (tx, ty))
        return im


class NSCR:
    def __init__(self, d):
        self.raw = bytearray(d)
        for mg, p, sz in _sections(d):
            if mg == b'NRCS':
                self.sec = p
                self.w, self.h, self.unk, self.bgtype, dsz = struct.unpack_from('<HHHHI', d, p + 8)
                self.dofs = p + 0x14
                self.ents = list(struct.unpack_from('<%dH' % (dsz // 2), d, self.dofs))

    def build(self):
        out = bytearray(self.raw)
        struct.pack_into('<%dH' % len(self.ents), out, self.dofs, *self.ents)
        return bytes(out)

    def render(self, ncgr, nclr):
        tw, th = self.w // 8, self.h // 8
        im = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))
        for i, e in enumerate(self.ents[:tw * th]):
            t, hf, vf, pal = e & 0x3ff, e >> 10 & 1, e >> 11 & 1, e >> 12
            if t * 64 + 64 > len(ncgr.px):
                continue
            blk = Image.frombytes('P', (8, 8), bytes(ncgr.tile(t)))
            if ncgr.bpp == 4:
                p = nclr.palette(pal)
                blk.putpalette(sum(p, ()))
                blk.info['transparency'] = 0
            else:
                blk.putpalette(sum(nclr.palette(), ()))
                blk.info['transparency'] = 0
            blk = blk.convert('RGBA')
            if hf: blk = blk.transpose(Image.FLIP_LEFT_RIGHT)
            if vf: blk = blk.transpose(Image.FLIP_TOP_BOTTOM)
            im.paste(blk, ((i % tw) * 8, (i // tw) * 8))
        return im


class OAM:
    __slots__ = ('a0', 'a1', 'a2')
    def __init__(self, a0, a1, a2):
        self.a0, self.a1, self.a2 = a0, a1, a2
    @property
    def y(self):
        v = self.a0 & 0xff
        return v - 256 if v >= 128 else v
    @property
    def x(self):
        v = self.a1 & 0x1ff
        return v - 512 if v >= 256 else v
    @property
    def size(self):
        return OBJ_SIZES[(self.a0 >> 14, self.a1 >> 14)]
    @property
    def bpp8(self):
        return bool(self.a0 >> 13 & 1)
    @property
    def affine(self):
        return bool(self.a0 >> 8 & 1)
    @property
    def hflip(self):
        return not self.affine and bool(self.a1 >> 12 & 1)
    @property
    def vflip(self):
        return not self.affine and bool(self.a1 >> 13 & 1)
    @property
    def tile(self):
        return self.a2 & 0x3ff
    @property
    def pal(self):
        return self.a2 >> 12
    def set_tile(self, t):
        self.a2 = (self.a2 & ~0x3ff) | (t & 0x3ff)


class NCER:
    def __init__(self, d):
        self.raw = bytearray(d)
        for mg, p, sz in _sections(d):
            if mg == b'KBEC':
                self.sec = p
                self.ncells, self.battr, coff, self.mapping = struct.unpack_from('<HHII', d, p + 8)
                self.cofs = p + 8 + coff
        ent = 16 if self.battr == 1 else 8
        self.ent = ent
        self.oam_base = self.cofs + self.ncells * ent
        self.cells = []
        for i in range(self.ncells):
            q = self.cofs + i * ent
            n, attr, ooff = struct.unpack_from('<HHI', d, q)
            bbox = struct.unpack_from('<hhhh', d, q + 8) if ent == 16 else None
            oams = [OAM(*struct.unpack_from('<HHH', d, self.oam_base + ooff + k * 6)) for k in range(n)]
            self.cells.append({'attr': attr, 'bbox': bbox, 'oams': oams, 'ooff': ooff})

    @property
    def shift(self):
        # 1D boundary: 0=32K (32-byte units), 1=64K, 2=128K, 3=256K
        return self.mapping if self.mapping < 4 else 0

    def build(self):
        out = bytearray(self.raw)
        for c in self.cells:
            for k, o in enumerate(c['oams']):
                struct.pack_into('<HHH', out, self.oam_base + c['ooff'] + k * 6, o.a0, o.a1, o.a2)
        return bytes(out)

    def oam_pixels(self, ncgr, o):
        """Return (w, h, bytes) of palette indices for one OAM."""
        w, h = o.size
        bpp8 = o.bpp8 or ncgr.bpp == 8
        unit = 32 << self.shift  # bytes per tile-number step
        start = o.tile * unit * (2 if ncgr.bpp == 4 else 1)  # px offset (4bpp px = half byte)
        if ncgr.bpp == 4:
            start = o.tile * unit * 2
        else:
            start = o.tile * unit
        npx = w * h
        raw = bytes(ncgr.px[start:start + npx]).ljust(npx, b'\0')
        if ncgr.tiled:
            # 1D mapped tiles: (w/8)*(h/8) consecutive 8x8 tiles, row-major
            buf = bytearray(npx)
            tw = w // 8
            for t in range(npx // 64):
                tx, ty = (t % tw) * 8, (t // tw) * 8
                for yy in range(8):
                    buf[(ty + yy) * w + tx:(ty + yy) * w + tx + 8] = raw[t * 64 + yy * 8:t * 64 + yy * 8 + 8]
            raw = bytes(buf)
        return w, h, raw, start

    def cell_bounds(self, i):
        oams = self.cells[i]['oams']
        if not oams:
            return 0, 0, 1, 1
        x0 = min(o.x for o in oams); y0 = min(o.y for o in oams)
        x1 = max(o.x + o.size[0] for o in oams); y1 = max(o.y + o.size[1] for o in oams)
        return x0, y0, x1, y1

    def render(self, i, ncgr, nclr, bounds=None):
        x0, y0, x1, y1 = bounds or self.cell_bounds(i)
        im = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
        # OAMs earlier in the list are drawn on top on DS hardware -> paste in reverse
        for o in reversed(self.cells[i]['oams']):
            w, h, raw, _ = self.oam_pixels(ncgr, o)
            blk = Image.frombytes('P', (w, h), raw)
            pal = nclr.palette(o.pal)
            blk.putpalette(sum(pal, ()))
            blk.info['transparency'] = 0
            blk = blk.convert('RGBA')
            if o.hflip: blk = blk.transpose(Image.FLIP_LEFT_RIGHT)
            if o.vflip: blk = blk.transpose(Image.FLIP_TOP_BOTTOM)
            im.alpha_composite(blk, (o.x - x0, o.y - y0))
        return im


class NANR:
    def __init__(self, d):
        self.anims = []
        for mg, p, sz in _sections(d):
            if mg == b'KNBA':
                na, nf, aoff, foff, doff = struct.unpack_from('<HHIII', d, p + 8)
                base = p + 8
                for i in range(na):
                    q = base + aoff + i * 16
                    nfr, start, ftype, atype, ploop, fofs = struct.unpack_from('<IHHHHI', d, q)
                    frames = []
                    for k in range(nfr):
                        dp, dur, _ = struct.unpack_from('<IHH', d, base + foff + fofs + k * 8)
                        frames.append((struct.unpack_from('<H', d, base + doff + dp)[0], dur))
                    self.anims.append(frames)


def load(path):
    return open(path, 'rb').read()

# palettes the game pairs at runtime with files that have no NCLR of their own (checked visually)
PALETTE_OVERRIDE = {
    'IN/UI_T7': 'IN/UI_T5.NCLR',
    'OUT/UI_OP': 'OUT/UI_OP2.NCLR',
    'OUT/UI_OP8': 'OUT/UI_OP6.NCLR',
    'OUT/RES/BG/UI_NQ5': 'OUT/RES/BG/UI_NQ4.NCLR',
    'OUT/RES/BG/UI_NQ6': 'OUT/RES/BG/UI_NQ4.NCLR',
    'OUT/RES/BG/UI_NQ7': 'OUT/RES/BG/UI_NQ4.NCLR',
    'OUT/RES/BG/UI_NQ8': 'OUT/RES/BG/UI_NQ4.NCLR',
}

def entry_name(path):
    """Archive entry name (as in RESOURCE.NXARC) of a file under extracted/nx."""
    return os.path.relpath(path, NX).replace(os.sep, '/')

def find_palette(path):
    """NCLR belonging to a graphics file (same base name, else first NCLR in the dir)."""
    base = os.path.splitext(path)[0]
    ov = PALETTE_OVERRIDE.get(entry_name(base))
    if ov:
        return os.path.join(NX, ov)
    if os.path.exists(base + '.NCLR'):
        return base + '.NCLR'
    d, b = os.path.split(base)
    # tiled 8bpp UI cells without their own palette use the screen's extended palette set
    for shared in ('UI_DS.NCLR', 'UI_CS.NCLR'):
        if b.startswith('UI_') and os.path.exists(os.path.join(d, shared)) and os.path.exists(base + '.NCGR'):
            return os.path.join(d, shared)
    # shared palette: the NCLR in the same dir with the longest common name prefix
    best, bl = None, 0
    for f in sorted(os.listdir(d)):
        if f.endswith('.NCLR'):
            n = os.path.commonprefix([f[:-5], b])
            if len(n) > bl:
                best, bl = os.path.join(d, f), len(n)
    return best

def ncer_charfile(path):
    base = os.path.splitext(path)[0]
    for ext in ('.NCBR', '.NCGR'):
        if os.path.exists(base + ext):
            return base + ext
    return None


def render_cellset(ncer_path, scale=1):
    """Return list of RGBA images, one per cell."""
    nc = NCER(load(ncer_path))
    cf = ncer_charfile(ncer_path); pf = find_palette(ncer_path)
    if not cf or not pf:
        return []
    cg = NCGR(load(cf)); pl = NCLR(load(pf))
    return [nc.render(i, cg, pl) for i in range(nc.ncells)]

def sheet(images, bg=(48, 48, 64, 255), label=True, maxw=1024):
    """Pack images onto one sheet with index labels."""
    from PIL import ImageDraw
    pad = 4
    rows = []; row = []; x = 0
    for i, im in enumerate(images):
        w = max(im.width, 16)
        if x + w + pad > maxw and row:
            rows.append(row); row = []; x = 0
        row.append((i, im)); x += w + pad
    if row: rows.append(row)
    H = sum(max(im.height for _, im in r) + 12 + pad for r in rows) + pad
    W = maxw
    out = Image.new('RGBA', (W, max(H, 8)), bg)
    d = ImageDraw.Draw(out)
    y = pad
    for r in rows:
        x = pad
        rh = max(im.height for _, im in r)
        for i, im in r:
            if label: d.text((x, y), str(i), fill=(255, 255, 0, 255))
            out.alpha_composite(im, (x, y + 12))
            x += max(im.width, 16) + pad
        y += rh + 12 + pad
    return out


def dump(filt=''):
    outroot = os.path.join(ROOT, 'work', 'gfx')
    n = 0
    for dp, dn, fn in os.walk(NX):
        rel = os.path.relpath(dp, NX).replace(os.sep, '/')
        if '/STAGE' in '/' + rel or filt not in rel:
            continue
        od = os.path.join(outroot, rel)
        for f in sorted(fn):
            p = os.path.join(dp, f)
            ext = f.split('.')[-1]
            try:
                if ext == 'NCER':
                    ims = render_cellset(p)
                    if ims:
                        os.makedirs(od, exist_ok=True)
                        sheet(ims).save(os.path.join(od, f[:-5] + '.png')); n += 1
                elif ext == 'NSCR':
                    base = p[:-5]
                    pf = find_palette(p)
                    if os.path.exists(base + '.NCGR') and pf:
                        im = NSCR(load(p)).render(NCGR(load(base + '.NCGR')), NCLR(load(pf)))
                        os.makedirs(od, exist_ok=True)
                        im.save(os.path.join(od, f[:-5] + '.png')); n += 1
            except Exception as e:
                print('ERR', p, e)
    print('rendered', n)


if __name__ == '__main__':
    if sys.argv[1] == 'dump':
        dump(sys.argv[2] if len(sys.argv) > 2 else '')
    elif sys.argv[1] == 'info':
        p = sys.argv[2]; d = load(p); ext = p.split('.')[-1]
        if ext in ('NCGR', 'NCBR'):
            g = NCGR(d); print(vars(g).keys(), g.bpp, g.tw, g.th, g.mapping, g.char_fmt, len(g.px))
        elif ext == 'NCER':
            c = NCER(d); print(c.ncells, c.battr, c.mapping)
            for i, cl in enumerate(c.cells):
                print(i, cl['bbox'], [(o.x, o.y, o.size, o.tile, o.pal, o.bpp8) for o in cl['oams']])
        elif ext == 'NCLR':
            c = NCLR(d); print(c.bpp, len(c.colors))
        elif ext == 'NANR':
            print(NANR(d).anims)
