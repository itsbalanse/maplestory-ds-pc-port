"""Reader/writer for MapleStory DS RESOURCE.NXARC ('NxAC') archives.

Layout (reverse engineered from ARM9 FUN_02001728 / FUN_020018b4):
  0x00 'NxAC'
  0x04 u16 ndirs, u16 nfiles
  0x08 u32 fat_off      (8 bytes per file: u32 offset rel. data_off, u32 size)
  0x0C u32 data_off
  0x10 u32 dirblock_size (ndirs*4 dir entries + dir names), starting at 0x20
  0x14 u32 namepool_size
  0x20 ndirs * (u16 count, u16 first_file)  -- files sorted by encoded name per dir
       dir names (C strings)
       nfiles * u16 name index (byte offset/2 into name pool)
       name pool: 6-bit packed, token-compressed names
"""
import struct, os, sys

TOKENS = [(63,'.NXATARI'),(62,'.NANR'),(61,'.NARC'),(60,'.NCBR'),(59,'.NCER'),(58,'.NCGR'),
          (57,'.NCLR'),(56,'.NSCR'),(55,'DO020'),(54,'IC100'),(53,'EF_'),(52,'IC0'),(51,'IC1'),
          (50,'MN0'),(49,'NC0'),(48,'NC1'),(47,'SK0'),(46,'UI_'),(45,'00'),(44,'01'),(43,'02'),
          (42,'03'),(41,'04'),(40,'05'),(39,'BU'),(38,'CI'),(37,'DO')]

def load_charmap(arm9_path):
    d = open(arm9_path, 'rb').read()
    cm = struct.unpack_from('<I', d, 0x1aa0)[0] - 0x2000000
    m = d[cm:cm + 0x60]
    dec = {}
    for i, c in enumerate(m):
        if c != 0xff and c not in dec:
            dec[c] = chr(0x20 + i)
    return dec

_CHARMAP = None
def decode_name(raw, charmap):
    # unpack 6-bit codes MSB-first
    codes = []
    bits = 0; acc = 0
    for b in raw:
        acc = (acc << 8) | b; bits += 8
        while bits >= 6:
            bits -= 6
            c = (acc >> bits) & 0x3f
            if c == 0:
                return ''.join(codes)
            codes.append(c)
    tokd = dict(TOKENS)
    out = []
    return ''.join(codes)

def decode_codes(codes, charmap):
    tokd = dict(TOKENS)
    return ''.join(tokd.get(c, charmap.get(c, '?')) for c in codes)

class NxArc:
    def __init__(self, path, arm9_path):
        self.path = path
        self.d = d = open(path, 'rb').read()
        assert d[:4] == b'NxAC'
        self.ndirs, self.nfiles, self.fat_off, self.data_off, self.dirblk, self.poolsz = struct.unpack_from('<HHIIII', d, 4)
        self.dirs = [struct.unpack_from('<HH', d, 0x20 + i*4) for i in range(self.ndirs)]
        p = 0x20 + self.ndirs*4
        names = d[p:0x20 + self.dirblk].split(b'\0')[:self.ndirs]
        self.dirnames = [n.decode() for n in names]
        nt = 0x20 + self.dirblk
        self.nameidx = struct.unpack_from('<%dH' % self.nfiles, d, nt)
        self.pool_off = nt + self.nfiles*2
        cm = load_charmap(arm9_path)
        self.entries = []  # (path, offset, size)
        fname = {}
        for di, (cnt, first) in enumerate(self.dirs):
            for fi in range(first, first + cnt):
                fname[fi] = self.dirnames[di] + '/' + self._name(fi, cm)
        for fi in range(self.nfiles):
            off, sz = struct.unpack_from('<II', d, self.fat_off + fi*8)
            self.entries.append((fname.get(fi, 'unk/%05d' % fi), self.data_off + off, sz))

    def _name(self, fi, cm):
        p = self.pool_off + self.nameidx[fi]*2
        codes = []; acc = 0; bits = 0
        while True:
            acc = ((acc << 8) | self.d[p]) & 0xffffff; p += 1; bits += 8
            done = False
            while bits >= 6:
                bits -= 6
                c = (acc >> bits) & 0x3f
                if c == 0: done = True; break
                codes.append(c)
            if done: break
        return decode_codes(codes, cm)

    def read(self, i):
        _, off, sz = self.entries[i]
        return self.d[off:off+sz]

if __name__ == '__main__':
    a = NxArc(sys.argv[1], sys.argv[2])
    print('dirs', a.ndirs, 'files', a.nfiles)
    if len(sys.argv) > 3:
        out = sys.argv[3]
        for i, (name, off, sz) in enumerate(a.entries):
            fp = os.path.join(out, name)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, 'wb').write(a.d[off:off+sz])
    else:
        for e in a.entries[:50]: print(e)


def rebuild_nxarc(arc, replacements):
    """Return new archive bytes. replacements: {entry_path: bytes}. Keeps header, names, and data order."""
    d = arc.d
    fat = [struct.unpack_from('<II', d, arc.fat_off + i*8) for i in range(arc.nfiles)]
    order = sorted(range(arc.nfiles), key=lambda i: fat[i][0])
    head = bytearray(d[:arc.data_off])
    data = bytearray()
    newfat = [None] * arc.nfiles
    moved = False
    for i in order:
        name = arc.entries[i][0]
        blob = replacements.get(name)
        if blob is None:
            blob = d[arc.data_off + fat[i][0]: arc.data_off + fat[i][0] + fat[i][1]]
        if len(data) <= fat[i][0] and d[arc.data_off + len(data): arc.data_off + fat[i][0]].count(0) == 0 and len(data) % 4:
            pass
        # reuse original padding bytes while layout is unchanged; otherwise zero-pad to 4
        if len(data) < fat[i][0] and fat[i][0] - len(data) < 4 and not moved:
            data += d[arc.data_off + len(data): arc.data_off + fat[i][0]]
        while len(data) % 4: data.append(0)
        if len(data) != fat[i][0]: moved = True
        newfat[i] = (len(data), len(blob))
        data += blob
        if name in replacements: moved = True
    for i, (o, s) in enumerate(newfat):
        struct.pack_into('<II', head, arc.fat_off + i*8, o, s)
    if not moved:
        data += d[arc.data_off + len(data):]
    return bytes(head) + bytes(data)
