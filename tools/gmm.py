"""MapleStory DS message table ('GMM') format.
  u16 total_size, u16 count
  count * { char key[8]; u32 offset }   offsets relative to string block
  string block: u16 block_size, then strings: { u16 byte_len; UTF-16LE text }
"""
import struct

def parse_gmm(d):
    total, cnt = struct.unpack_from('<HH', d, 0)
    ents = []
    base = 4 + cnt*12
    for i in range(cnt):
        key = d[4+i*12:4+i*12+8].rstrip(b'\0').decode('latin1')
        off = struct.unpack_from('<I', d, 4+i*12+8)[0]
        ln = struct.unpack_from('<H', d, base+off)[0]
        txt = d[base+off+2:base+off+2+ln].decode('utf-16le')
        ents.append((key, txt))
    return ents

def looks_like_gmm(d):
    if len(d) < 4: return False
    total, cnt = struct.unpack_from('<HH', d, 0)
    if total != len(d) and total != (len(d) & 0xffff): return False
    if cnt == 0 or 4 + cnt*12 + 2 > len(d): return False
    try:
        parse_gmm(d); return True
    except Exception:
        return False

def build_gmm(ents):
    keys = b''; strs = b''
    for k, t in ents:
        kb = k.encode('latin1')[:8].ljust(8, b'\0')
        enc = t.encode('utf-16le')
        keys += kb + struct.pack('<I', 2 + len(strs))
        strs += struct.pack('<H', len(enc)) + enc
    block = struct.pack('<H', (2 + len(strs)) & 0xffff) + strs
    body = struct.pack('<H', len(ents)) + keys + block
    total = 2 + len(body)
    return struct.pack('<H', total & 0xffff) + body
