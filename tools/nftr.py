"""Nitro NFTR font parser/builder (FINF/CGLP/CWDH/CMAP)."""
import struct

class NFTR:
    def __init__(self, d):
        self.raw = d
        assert d[:4] == b'RTFN', d[:4]
        hsz = struct.unpack_from('<H', d, 0xC)[0]
        p = hsz
        self.blocks = {}
        while p < len(d):
            magic = d[p:p+4][::-1]; sz = struct.unpack_from('<I', d, p+4)[0]
            self.blocks.setdefault(magic, []).append((p, sz))
            if sz == 0: break
            p += sz
        fp, _ = self.blocks[b'FINF'][0]
        (self.ftype, self.line_feed, self.alt_char, self.def_left, self.def_glyph_w, self.def_char_w,
         self.encoding, self.cglp_ptr, self.cwdh_ptr, self.cmap_ptr) = struct.unpack_from('<BbHbBbBIII', d, fp+8)
        cp = self.cglp_ptr - 8
        self.cell_w, self.cell_h, self.cell_size, self.baseline, self.max_w, self.bpp, self.rot = struct.unpack_from('<BBHbBBB', d, cp+8)
        cg_sz = struct.unpack_from('<I', d, cp+4)[0]
        self.nglyphs = (cg_sz - 0x10) // self.cell_size
        self.glyph_off = cp + 0x10
        # widths
        self.widths = {}
        wp = self.cwdh_ptr - 8
        while wp:
            fi, li, nxt = struct.unpack_from('<HHI', d, wp+8)
            for i in range(fi, li+1):
                self.widths[i] = struct.unpack_from('<bBB', d, wp+16+(i-fi)*3)
            wp = nxt - 8 if nxt else 0
        # cmap: code -> glyph index
        self.cmap = {}
        mp = self.cmap_ptr - 8
        while mp:
            first, last, typ, nxt = struct.unpack_from('<HHHxxI', d, mp+8)
            body = mp + 20
            if typ == 0:
                base = struct.unpack_from('<H', d, body)[0]
                for c in range(first, last+1): self.cmap[c] = base + c - first
            elif typ == 1:
                for c in range(first, last+1):
                    g = struct.unpack_from('<H', d, body + (c-first)*2)[0]
                    if g != 0xffff: self.cmap[c] = g
            else:
                n = struct.unpack_from('<H', d, body)[0]
                for i in range(n):
                    c, g = struct.unpack_from('<HH', d, body+2+i*4); self.cmap[c] = g
            mp = nxt - 8 if nxt else 0

    def glyph_bits(self, gi):
        o = self.glyph_off + gi*self.cell_size
        data = self.raw[o:o+self.cell_size]
        px = []
        bit = 0
        for y in range(self.cell_h):
            row = []
            for x in range(self.cell_w):
                v = 0
                for b in range(self.bpp):
                    byte = data[bit >> 3]; v = (v << 1) | ((byte >> (7 - (bit & 7))) & 1); bit += 1
                row.append(v)
            px.append(row)
        return px
