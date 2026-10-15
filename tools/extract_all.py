"""Regenerate extracted/ from the Japanese ROM (extracted/ is git-ignored).

usage: python tools/extract_all.py ["MapleStory DS (Japan).nds"]
Produces:
  extracted/data/...            NDS filesystem
  extracted/arm9.bin/arm7.bin   raw binaries
  extracted/arm9_dec.bin        BLZ-decompressed ARM9 (load address 0x02000000)
  extracted/overlay_dec/ovNNN_<ram>.bin  decompressed overlays
  extracted/nx/...              RESOURCE.NXARC contents
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(__file__))
from ndsfs import NDS
from blz import blz_decompress
from nxarc import NxArc

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))

def main(rom_path):
    out = os.path.join(ROOT, 'extracted')
    rom = NDS(rom_path)
    for p, fid in rom.files.items():
        fp = os.path.join(out, 'data', p)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, 'wb').write(rom.read(fid))
    a9 = rom.data[rom.arm9_off:rom.arm9_off + rom.arm9_size]
    open(os.path.join(out, 'arm9.bin'), 'wb').write(a9)
    open(os.path.join(out, 'arm7.bin'), 'wb').write(rom.data[rom.arm7_off:rom.arm7_off + rom.arm7_size])
    mp = a9.find(struct.pack('<I', 0xDEC00621)) - 0x1c
    cend = struct.unpack_from('<I', a9, mp + 0x14)[0] - rom.arm9_load
    dec = bytearray(a9[:0x4000] + blz_decompress(a9[0x4000:cend]) + a9[cend:])
    struct.pack_into('<I', dec, mp + 0x14, 0)
    open(os.path.join(out, 'arm9_dec.bin'), 'wb').write(dec)
    od = os.path.join(out, 'overlay_dec')
    os.makedirs(od, exist_ok=True)
    for oid, ram, rsz, bss, _, _, fid, flags in rom.overlays():
        raw = rom.read(fid)
        if flags & 0x01000000:
            raw = blz_decompress(raw)
        open(os.path.join(od, 'ov%03d_%08x.bin' % (oid, ram)), 'wb').write(raw)
    # The Mobiclip movie decoder is copied from the static ARM9 into ITCM (over overlay 0) while a
    # movie plays; the recompiler treats it as pseudo-overlay 200 at 0x01ff8500.
    open(os.path.join(od, 'ov200_01ff8500.bin'), 'wb').write(bytes(dec[0x124ca4:0x124ca4 + 0x65e0]))
    arc = NxArc(os.path.join(out, 'data', 'RESOURCE.NXARC'), os.path.join(out, 'arm9_dec.bin'))
    for name, off, size in arc.entries:
        fp = os.path.join(out, 'nx', name)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, 'wb').write(arc.d[off:off + size])
    print('extracted to', out)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'MapleStory DS (Japan).nds'))
