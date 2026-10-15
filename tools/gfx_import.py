"""Import edited PNGs back into Nitro graphics (cell sets and BG screens).

Cells: the PNG is one cell rendered at its bounding box (exactly what `render_cell` produces).
Only pixels that differ from the original render are written, into the topmost OAM covering
the pixel, re-quantized to that OAM's palette. Char data shared with other cells is split off
(copied to new chars appended to the file) when the cells would otherwise disagree. Pixels
outside every OAM get new 8x8..64x64 OAMs. Every cell of the set is re-rendered afterwards and
compared against the expected result, so shared-tile bleeding cannot slip through.

BG screens: the PNG is the whole screen as `NSCR.render` produces it. Changed 8x8 tiles reuse an
identical existing tile, overwrite the tile in place when nothing else uses it, or get a new tile.
"""
import os, sys, struct
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from gfx import NCER, NCGR, NCLR, NSCR, OAM, OBJ_SIZES, load, _fix_total

class ImportError_(Exception):
    pass


def _pal_array(nclr, bank):
    return np.array(nclr.palette(bank), dtype=np.int32) & 0xF8

def quantize(rgba, pal, ncolors):
    """rgba: HxWx4 uint8 -> HxW palette indices (0 = transparent), using entries 1..ncolors-1."""
    a = rgba[..., 3] >= 128
    rgb = rgba[..., :3].astype(np.int32)
    cand = pal[1:ncolors]
    # perceptual-ish weights
    w = np.array([3, 4, 2])
    d = (((rgb[..., None, :] - cand[None, None, :, :]) ** 2) * w).sum(-1)
    idx = d.argmin(-1) + 1
    return np.where(a, idx, 0).astype(np.uint8)


def _bgr(c):
    return ((c[0] >> 3) << 3, (c[1] >> 3) << 3, (c[2] >> 3) << 3)

def snap(img):
    """Reduce an RGBA image to 15-bit colour + 1-bit alpha (what the DS can show)."""
    a = np.array(img.convert('RGBA'))
    a[..., :3] &= 0xF8
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    return a


class CellImporter:
    def __init__(self, ncer_bytes, char_bytes, pal_bytes):
        self.nc = NCER(ncer_bytes)
        self.cg = NCGR(char_bytes)
        self.pl = NCLR(pal_bytes)
        self.ncol = 16 if self.cg.bpp == 4 else 256
        self.unit_px = (32 << self.nc.shift) * (2 if self.cg.bpp == 4 else 1)
        self.log = []
        self.fresh = set()      # ids of OAMs created here: they never share char data

    # ---- geometry helpers ----
    def oam_range(self, o):
        w, h = o.size
        start = o.tile * self.unit_px
        return start, start + w * h

    def px_index(self, o, lx, ly):
        """char pixel index for OAM-local screen coords (lx, ly), honouring flips."""
        w, h = o.size
        sx = w - 1 - lx if o.hflip else lx
        sy = h - 1 - ly if o.vflip else ly
        start = o.tile * self.unit_px
        if self.cg.tiled:
            t = (sy // 8) * (w // 8) + sx // 8
            return start + t * 64 + (sy % 8) * 8 + sx % 8
        return start + sy * w + sx

    def render_idx(self, i, bounds):
        """Render cell i to (palette-bank, index) arrays for exact comparison."""
        x0, y0, x1, y1 = bounds
        H, W = y1 - y0, x1 - x0
        out = np.zeros((H, W, 4), np.uint8)
        for o in reversed(self.nc.cells[i]['oams']):
            w, h = o.size
            pal = _pal_array(self.pl, o.pal)
            for ly in range(h):
                yy = o.y - y0 + ly
                if not 0 <= yy < H: continue
                for lx in range(w):
                    xx = o.x - x0 + lx
                    if not 0 <= xx < W: continue
                    v = self.cg.px[self.px_index(o, lx, ly)] if self.px_index(o, lx, ly) < len(self.cg.px) else 0
                    if v:
                        c = pal[v]
                        out[yy, xx] = (c[0] & 0xF8, c[1] & 0xF8, c[2] & 0xF8, 255)
        return out

    def apply(self, edits):
        """edits: {cell index: RGBA PIL image at the cell's original bounds (or larger, see below)}.
        A larger image must carry its origin in img.info['origin'] = 'x,y' (cell coords)."""
        nc = self.nc
        bounds = {i: nc.cell_bounds(i) for i in range(nc.ncells)}
        # expected final images for every cell
        orig = {i: self.render_idx(i, bounds[i]) for i in range(nc.ncells)}
        targets = {}
        for i, img in edits.items():
            if 'origin' in img.info:
                ox, oy = map(int, img.info['origin'].split(','))
            else:
                ox, oy = bounds[i][0], bounds[i][1]
            targets[i] = (ox, oy, snap(img))

        self._repack(targets)
        # 3) verify
        bad = []
        for i in range(nc.ncells):
            b = nc.cell_bounds(i)
            got = self.render_idx(i, b)
            if i in targets:
                ox, oy, tgt = targets[i]
                exp = self._expected(ox, oy, tgt, b, i)
            else:
                exp = orig[i]
                if b != bounds[i]:
                    bad.append((i, 'bounds changed')); continue
            diff = int((got != exp).any(-1).sum())
            if diff:
                bad.append((i, diff))
        return bad

    # ---- repacking ----
    def _orig_screen(self, o, base=None):
        """Char pixels of OAM o (current data, or `base` block bytes) in screen orientation."""
        w, h = o.size
        s, e = self.oam_range(o)
        if base is None:
            base = bytes(self.cg.px[s:e]).ljust(w * h, b'\0')
        raw = np.frombuffer(base, np.uint8)
        if self.cg.tiled:
            idx = raw.reshape(h // 8, w // 8, 8, 8).transpose(0, 2, 1, 3).reshape(h, w)
        else:
            idx = raw.reshape(h, w)
        if o.hflip: idx = idx[:, ::-1]
        if o.vflip: idx = idx[::-1, :]
        return idx.copy()

    def _block(self, o, q, ox, oy, resolved, base=None, below=None):
        """Char-order block for OAM o so that, drawn under the OAMs above it, the cell shows the
        quantized target q. `resolved` (target-sized bool) marks pixels already shown by an
        opaque OAM above; those keep their old (hidden) value. Updates `resolved`.
        Returns (bytes, fixed): fixed marks the pixels this cell actually depends on."""
        w, h = o.size
        th, tw = q.shape[:2]
        pal = _pal_array(self.pl, o.pal)
        idx = self._orig_screen(o, base)
        fixed = np.zeros((h, w), bool)
        for ly in range(h):
            Y = o.y - oy + ly
            for lx in range(w):
                X = o.x - ox + lx
                inside = 0 <= X < tw and 0 <= Y < th
                if inside and resolved[Y, X]:
                    continue
                fixed[ly, lx] = True
                t = q[Y, X] if inside else (0, 0, 0, 0)
                if t[3] == 0:
                    idx[ly, lx] = 0
                    continue
                v = idx[ly, lx]
                if v == 0 and below is not None and below[Y, X]:
                    continue        # transparent here and an OAM underneath can show the pixel
                if not (v and (pal[v] == t[:3]).all()):
                    idx[ly, lx] = int(quantize(np.array(t, np.uint8)[None, None], pal, self.ncol)[0, 0])
                resolved[Y, X] = True
        return self._to_char(o, idx).astype(np.uint8).tobytes(), self._to_char(o, fixed)

    def _to_char(self, o, a):
        """Screen-oriented h x w array -> flat char-order array (undo flips, tile order)."""
        w, h = o.size
        if o.hflip: a = a[:, ::-1]
        if o.vflip: a = a[::-1, :]
        if self.cg.tiled:
            a = a.reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3)
        return np.ascontiguousarray(a).reshape(-1)

    def _to_screen(self, o, flat):
        w, h = o.size
        a = flat.reshape(h // 8, w // 8, 8, 8).transpose(0, 2, 1, 3).reshape(h, w) if self.cg.tiled else flat.reshape(h, w)
        if o.hflip: a = a[:, ::-1]
        if o.vflip: a = a[::-1, :]
        return a

    def _repack(self, targets):
        """Rebuild the char data of the edited cells' OAMs so each cell shows its target image.

        Char ranges used by unedited cells keep their content. A range used by several edited
        cells is written by the first one; a later cell that needs different pixels there gets
        small overlay OAMs on top instead of a full copy. OAMs that become fully transparent are
        dropped (their space is recycled), identical blocks are shared, target pixels outside
        every OAM get new OAMs, and new blocks go into free space before the file is grown."""
        nc, U = self.nc, self.unit_px
        edited = sorted(targets)
        committed = {}          # (start, end) -> [block bytes, fixed mask]: pixels some cell depends on
        for ci, c in enumerate(nc.cells):
            if ci in targets: continue
            for o in c['oams']:
                s, e = self.oam_range(o)
                committed[(s, e)] = [bytes(self.cg.px[s:e]).ljust(e - s, b'\0'), np.ones(e - s, bool)]
        plan = {}
        for i in edited:
            ox, oy, tgt = targets[i]
            q = self._quant_target(i, ox, oy, tgt)
            covered = np.zeros(q.shape[:2], bool)
            for o in nc.cells[i]['oams']:
                w, h = o.size
                X0, Y0 = o.x - ox, o.y - oy
                covered[max(0, Y0):max(0, Y0 + h), max(0, X0):max(0, X0 + w)] = True
            unc = np.argwhere((q[..., 3] > 0) & ~covered)
            if len(unc):
                self._add_oams(i, [(ox + x, oy + y) for y, x in unc])
            for attempt in range(4):
                resolved = np.zeros(q.shape[:2], bool)
                blocks = []
                fix = []
                oams = nc.cells[i]['oams']
                # what the OAMs below each one already show: an OAM with a transparent pixel there
                # may stay transparent when that is already exactly the target colour
                unders, acc = [None] * len(oams), np.zeros(q.shape, np.uint8)
                for k in range(len(oams) - 1, -1, -1):
                    unders[k] = (acc[..., 3] > 0) & (acc == q).all(-1)
                    o2 = oams[k]
                    if id(o2) in self.fresh:
                        continue
                    c2 = committed.get(self.oam_range(o2))
                    scr = self._orig_screen(o2, c2[0] if c2 else None)
                    pal2 = _pal_array(self.pl, o2.pal)
                    w, h = o2.size
                    X0, Y0 = o2.x - ox, o2.y - oy
                    for ly, lx in np.argwhere(scr):
                        Y, X = Y0 + ly, X0 + lx
                        if 0 <= Y < q.shape[0] and 0 <= X < q.shape[1]:
                            acc[Y, X, :3] = pal2[scr[ly, lx]]; acc[Y, X, 3] = 255
                for k, o in enumerate(oams):
                    before = resolved.copy()
                    key = self.oam_range(o)
                    c = None if id(o) in self.fresh else committed.get(key)
                    blk, fx = self._block(o, q, ox, oy, resolved, c[0] if c else None, unders[k])
                    clash = np.zeros(len(blk), bool)
                    if c:
                        clash = fx & c[1] & (np.frombuffer(blk, np.uint8) != np.frombuffer(c[0], np.uint8))
                        if clash.any() and attempt < 3:
                            fix += self._clash_pixels(o, clash, ox, oy, q, before)
                    blocks.append((blk, fx, clash))
                if not fix:
                    break
                self._add_oams(i, fix, top=True)
            keep = []
            for o, (blk, fx, clash) in zip(nc.cells[i]['oams'], blocks):
                if not np.frombuffer(blk, np.uint8)[fx].any():
                    continue                         # shows nothing in this cell
                keep.append(o)
                key = self.oam_range(o)
                c = None if id(o) in self.fresh else committed.get(key)
                if id(o) in self.fresh:
                    plan[id(o)] = ('own', blk)
                elif c is not None and not clash.any():
                    merged = np.where(c[1], np.frombuffer(c[0], np.uint8), np.frombuffer(blk, np.uint8))
                    c[0] = merged.astype(np.uint8).tobytes(); c[1] = c[1] | fx
                    plan[id(o)] = ('shared', key)
                elif c is None and not any(s2 < key[1] and key[0] < e2 for s2, e2 in committed):
                    committed[key] = [blk, fx.copy()]    # claim the range: written in place below
                    plan[id(o)] = ('shared', key)
                else:
                    plan[id(o)] = ('own', blk)
            dropped = len(nc.cells[i]['oams']) - len(keep)
            if dropped:
                self.log.append('cell %d: %d empty OAMs removed' % (i, dropped))
            if len(keep) != len(nc.cells[i]['oams']) or any(a is not b for a, b in zip(keep, nc.cells[i]['oams'])):
                nc.cells[i]['grown'] = True
            nc.cells[i]['oams'] = keep
        # space map
        orig_tiles = (len(self.cg.px) + U - 1) // U
        used = np.zeros(max(orig_tiles, 1024) + 1, bool)
        known = {}
        for (s, e) in committed:
            used[s // U:(e + U - 1) // U] = True
        for (s, e), (blk, fx) in committed.items():
            if e > len(self.cg.px):
                self.cg.px.extend(b'\0' * (e - len(self.cg.px)))
            self.cg.px[s:e] = blk
        moving = []
        for i in edited:
            for o in nc.cells[i]['oams']:
                kind, v = plan[id(o)]
                if kind == 'shared':
                    known.setdefault((o.size, committed[v][0]), o.tile)
                    continue
                s, e = self.oam_range(o)
                if id(o) not in self.fresh and e <= len(self.cg.px) and bytes(self.cg.px[s:e]) == v:
                    known.setdefault((o.size, v), o.tile)      # already holds the right pixels
                else:
                    moving.append(o)
        for o in moving:
            blk = plan[id(o)][1]
            k = (o.size, blk)
            if k in known:
                o.set_tile(known[k]); continue
            n = (len(blk) + U - 1) // U
            t = self._find_free(used, n, orig_tiles)
            used[t:t + n] = True
            end = t * U + len(blk)
            if end > len(self.cg.px):
                self.cg.px.extend(b'\0' * (end - len(self.cg.px)))
            self.cg.px[t * U:end] = blk
            o.set_tile(t)
            known[k] = t
        if len(self.cg.px) % U:
            self.cg.px.extend(b'\0' * (U - len(self.cg.px) % U))
        grow = len(self.cg.px) - orig_tiles * U
        if grow > 0:
            self.log.append('char data grew by %d px' % grow)

    def _clash_pixels(self, o, clash, ox, oy, q, resolved_before):
        """Screen pixels of OAM o whose shared char data is pinned to other content by another
        cell; only those an opaque overlay can fix (target opaque, not already shown from above)."""
        th, tw = q.shape[:2]
        pts = []
        for ly, lx in np.argwhere(self._to_screen(o, clash)):
            X, Y = o.x - ox + lx, o.y - oy + ly
            if 0 <= X < tw and 0 <= Y < th and q[Y, X, 3] and not resolved_before[Y, X]:
                pts.append((o.x + lx, o.y + ly))
        return pts

    def _find_free(self, used, n, prefer_below):
        for lim in (prefer_below, 1024):
            run = 0
            for t in range(lim):
                run = run + 1 if not used[t] else 0
                if run == n:
                    return t - n + 1
        raise ImportError_('char data full')

    def _add_oams(self, i, pts, top=False):
        """Add OAMs (strips of 8x8 blocks on the template OAM's 8 px grid) covering pts."""
        cell = self.nc.cells[i]
        tmpl = cell['oams'][0 if top else -1] if cell['oams'] else OAM(0x2000 if self.cg.bpp == 8 else 0, 0, 0)
        gx0, gy0 = tmpl.x % 8, tmpl.y % 8
        blocks = set(((x - gx0) // 8, (y - gy0) // 8) for x, y in pts)
        done = set(); new = []
        for bx, by in sorted(blocks, key=lambda b: (b[1], b[0])):
            if (bx, by) in done: continue
            run = 1
            while run < 4 and (bx + run, by) in blocks and (bx + run, by) not in done:
                run += 1
            if run == 3: run = 2
            for k in range(run): done.add((bx + k, by))
            shape, size = {1: (0, 0), 2: (1, 0), 4: (1, 1)}[run]
            X, Y = gx0 + bx * 8, gy0 + by * 8
            a0 = (tmpl.a0 & 0x3C00) | (Y & 0xff) | shape << 14   # keep mode/mosaic/bpp, no affine
            a1 = (X & 0x1ff) | size << 14
            new.append(OAM(a0, a1, tmpl.a2 & 0xFC00))
            self.fresh.add(id(new[-1]))
        cell['grown'] = True
        if top:
            cell['oams'][:0] = new     # first = drawn above everything (overlay patch)
        else:
            cell['oams'].extend(new)   # last = drawn underneath existing graphics
        self.log.append('cell %d: added %d %sOAMs' % (i, len(new), 'overlay ' if top else ''))

    def _expected(self, ox, oy, tgt, b, i):
        x0, y0, x1, y1 = b
        H, W = y1 - y0, x1 - x0
        exp = np.zeros((H, W, 4), np.uint8)
        th, tw = tgt.shape[:2]
        # quantized target, placed in new bounds
        q = self._quant_target(i, ox, oy, tgt)
        for yy in range(th):
            for xx in range(tw):
                X, Y = ox + xx - x0, oy + yy - y0
                if 0 <= X < W and 0 <= Y < H:
                    exp[Y, X] = q[yy, xx]
        return exp

    def _top_oam(self, i, x, y):
        for o in self.nc.cells[i]['oams']:
            w, h = o.size
            if o.x <= x < o.x + w and o.y <= y < o.y + h:
                return o
        return None

    def _quant_target(self, i, ox, oy, tgt):
        """Target snapped to the palette of the OAM that will hold each pixel."""
        if not hasattr(self, '_qcache'): self._qcache = {}
        key = (i, ox, oy)
        if key in self._qcache: return self._qcache[key]
        th, tw = tgt.shape[:2]
        q = np.zeros_like(tgt)
        bank = self._default_bank(i)
        banks = {}
        for yy in range(th):
            for xx in range(tw):
                if tgt[yy, xx, 3] == 0: continue
                o = self._top_oam(i, ox + xx, oy + yy)
                b = o.pal if o else bank
                banks.setdefault(b, []).append((yy, xx))
        for b, pts in banks.items():
            pal = _pal_array(self.pl, b)
            arr = np.array([tgt[y, x] for y, x in pts], np.uint8)[None]
            idx = quantize(arr, pal, self.ncol)[0]
            for (y, x), v in zip(pts, idx):
                c = pal[v]
                q[y, x] = (c[0] & 0xF8, c[1] & 0xF8, c[2] & 0xF8, 255)
        self._qcache[key] = q
        return q

    def _default_bank(self, i):
        oams = self.nc.cells[i]['oams']
        return oams[0].pal if oams else 0

    def build(self):
        return build_ncer(self.nc), self.cg.build()


def build_ncer(nc):
    """Rebuild the KBEC section (cells + OAM table), keeping any later sections."""
    raw = nc.raw
    if not any(c.get('grown') for c in nc.cells):
        return nc.build()
    ent = nc.ent
    cells = bytearray(); oams = bytearray()
    for c in nc.cells:
        off = len(oams)
        for o in c['oams']:
            oams += struct.pack('<HHH', o.a0, o.a1, o.a2)
        cells += struct.pack('<HHI', len(c['oams']), c['attr'], off)
        if ent == 16:
            if c['oams']:
                xs = [o.x for o in c['oams']]; ys = [o.y for o in c['oams']]
                xe = [o.x + o.size[0] for o in c['oams']]; ye = [o.y + o.size[1] for o in c['oams']]
                bb = (max(xe), max(ye), min(xs), min(ys))
            else:
                bb = c['bbox']
            cells += struct.pack('<hhhh', *bb)
    sec = nc.sec
    secsize = struct.unpack_from('<I', raw, sec + 4)[0]
    head = bytearray(raw[sec:nc.cofs])
    body = head + cells + oams
    while len(body) % 4: body += b'\0'
    struct.pack_into('<I', body, 4, len(body))
    out = bytearray(raw[:sec]) + body + raw[sec + secsize:]
    _fix_total(out)
    return bytes(out)


def import_cells(ncer_b, char_b, pal_b, edits):
    ci = CellImporter(ncer_b, char_b, pal_b)
    bad = ci.apply(edits)
    if bad:
        raise ImportError_('verification failed: %s; log=%s' % (bad[:10], ci.log))
    ne, ncg = ci.build()
    return ne, ncg, ci.log


# ---------------------------------------------------------------- BG screens

def import_bg(nscr_b, ncgr_b, nclr_b, img, extra_users=()):
    """Return (nscr, ncgr, log). extra_users: other NSCR bytes sharing this NCGR (their tiles are kept)."""
    sc = NSCR(nscr_b); cg = NCGR(ncgr_b); pl = NCLR(nclr_b)
    ncol = 16 if cg.bpp == 4 else 256
    orig = snap(sc.render(cg, pl))
    tgt = snap(img)
    if tgt.shape != orig.shape:
        raise ImportError_('size mismatch %s vs %s' % (tgt.shape, orig.shape))
    tw = sc.w // 8
    ntiles = len(cg.px) // 64
    uses = {}
    for k, e in enumerate(sc.ents[:tw * (sc.h // 8)]):
        uses.setdefault(e & 0x3ff, []).append(k)
    for ob in extra_users:
        for e in NSCR(ob).ents:
            uses.setdefault(e & 0x3ff, []).append(-1)
    log = []
    tiles = {bytes(cg.tile(t)): t for t in range(ntiles - 1, -1, -1)}
    for k, e in enumerate(sc.ents[:tw * (sc.h // 8)]):
        bx, by = (k % tw) * 8, (k // tw) * 8
        a = tgt[by:by + 8, bx:bx + 8]; b = orig[by:by + 8, bx:bx + 8]
        if (a == b).all():
            continue
        if cg.bpp == 4:
            # pick the palette bank that reproduces this tile best (text may need colours the
            # tile's original bank lacks)
            best = None
            for bank in range(min(16, len(pl.colors) // 16)):
                pal_b = np.array(pl.palette(bank), np.int32) & 0xF8
                qb = quantize(a, pal_b, ncol)
                err = int((np.abs(pal_b[qb] - a[..., :3].astype(int)).sum(-1) * (a[..., 3] > 0)).sum())
                if bank == e >> 12: err -= 1          # prefer the original bank on ties
                if best is None or err < best[0]:
                    best = (err, bank, qb)
            _, bank, q = best
            e = (e & ~0xF000) | bank << 12
        else:
            pal = np.array(pl.palette(0), np.int32) & 0xF8
            q = quantize(a, pal, ncol)
        hf, vf = e >> 10 & 1, e >> 11 & 1
        if hf: q = q[:, ::-1]
        if vf: q = q[::-1, :]
        data = bytes(q.astype(np.uint8).tobytes())
        t = e & 0x3ff
        if data in tiles:
            nt = tiles[data]
        elif len(uses.get(t, [])) == 1:
            nt = t
            cg.px[t * 64:t * 64 + 64] = data
            tiles[data] = t
        else:
            nt = len(cg.px) // 64
            if nt >= 1024:
                raise ImportError_('BG tile space full')
            cg.px.extend(data)
            tiles[data] = nt
            log.append('new tile %d at screen %d,%d' % (nt, bx, by))
        uses.setdefault(t, []).remove(k) if k in uses.get(t, []) else None
        uses.setdefault(nt, []).append(k)
        sc.ents[k] = (e & ~0x3ff) | nt
    # verify
    got = snap(sc.render(cg, pl))
    exp = tgt.copy()
    # compare after quantization: re-render is the truth; measure residual vs target
    diff = int((np.abs(got.astype(int) - exp.astype(int)).sum(-1) > 24).sum())
    if diff > 0:
        log.append('quantization residual: %d px differ noticeably' % diff)
    return sc.build(), cg.build(), log
