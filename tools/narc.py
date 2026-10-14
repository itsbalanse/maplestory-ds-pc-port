"""Nitro NARC container read/write (BTAF/BTNF/GMIF)."""
import struct

def parse_narc(d):
    assert d[:4] == b'NARC', d[:4]
    hdr_size = struct.unpack_from('<H', d, 0x0C)[0]
    p = hdr_size
    assert d[p:p+4] == b'BTAF'
    fat_size, n = struct.unpack_from('<IH', d, p+4)
    fat = [struct.unpack_from('<II', d, p+12+i*8) for i in range(n)]
    p += fat_size
    assert d[p:p+4] == b'BTNF'
    fnt_size = struct.unpack_from('<I', d, p+4)[0]
    fnt = d[p+8:p+fnt_size]
    names = _fnt_names(fnt, n)
    p += fnt_size
    assert d[p:p+4] == b'GMIF'
    base = p + 8
    files = [d[base+s:base+e] for s, e in fat]
    return names, files, fnt

def _fnt_names(fnt, n):
    if len(fnt) < 8: return [None]*n
    sub_off, first, ndirs = struct.unpack_from('<IHH', fnt, 0)
    names = [None]*n
    def walk(did, prefix):
        so, fid, _ = struct.unpack_from('<IHH', fnt, (did & 0xfff)*8)
        p = so
        while p < len(fnt):
            t = fnt[p]; p += 1
            if t == 0: break
            ln = t & 0x7f; nm = fnt[p:p+ln].decode('latin1'); p += ln
            if t & 0x80:
                sub = struct.unpack_from('<H', fnt, p)[0]; p += 2
                walk(sub, prefix + nm + '/')
            else:
                if fid < n: names[fid] = prefix + nm
                fid += 1
    if sub_off >= 8 and ndirs > 0 and sub_off < len(fnt):
        try: walk(0xF000, '')
        except Exception: pass
    return names

def build_narc(files, fnt):
    fat = b''; data = b''
    for f in files:
        s = len(data); data += f; e = len(data)
        fat += struct.pack('<II', s, e)
        while len(data) % 4: data += b'\xff'
    btaf = b'BTAF' + struct.pack('<IHH', 12 + len(fat), len(files), 0) + fat
    if not fnt:
        fnt = struct.pack('<IHH', 4, 0, 1)
    fntp = fnt
    while (len(fntp) + 8) % 4: fntp += b'\xff'
    btnf = b'BTNF' + struct.pack('<I', 8 + len(fntp)) + fntp
    gmif = b'GMIF' + struct.pack('<I', 8 + len(data)) + data
    body = btaf + btnf + gmif
    hdr = b'NARC' + struct.pack('<HHIHH', 0xFFFE, 0x0100, 16 + len(body), 16, 3)
    return hdr + body
