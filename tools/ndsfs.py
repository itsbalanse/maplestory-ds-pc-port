"""Minimal NDS ROM filesystem reader/extractor."""
import struct, sys, os

class NDS:
    def __init__(self, path):
        self.data = open(path, 'rb').read()
        h = self.data
        self.title = h[0:12].rstrip(b'\0').decode()
        self.code = h[12:16].decode()
        (self.arm9_off, self.arm9_entry, self.arm9_load, self.arm9_size,
         self.arm7_off, self.arm7_entry, self.arm7_load, self.arm7_size,
         self.fnt_off, self.fnt_size, self.fat_off, self.fat_size,
         self.ovt9_off, self.ovt9_size, self.ovt7_off, self.ovt7_size) = struct.unpack_from('<16I', h, 0x20)
        n = self.fat_size // 8
        self.fat = [struct.unpack_from('<II', h, self.fat_off + i*8) for i in range(n)]
        self.files = {}  # path -> file id
        self._walk(0xF000, '')

    def _walk(self, dir_id, prefix):
        h = self.data
        base = self.fnt_off + (dir_id & 0xFFF) * 8
        sub_off, first_id, _ = struct.unpack_from('<IHH', h, base)
        p = self.fnt_off + sub_off
        fid = first_id
        while True:
            t = h[p]; p += 1
            if t == 0: break
            ln = t & 0x7F
            name = h[p:p+ln].decode('shift_jis', 'replace'); p += ln
            if t & 0x80:
                sub = struct.unpack_from('<H', h, p)[0]; p += 2
                self._walk(sub, prefix + name + '/')
            else:
                self.files[prefix + name] = fid; fid += 1

    def read(self, fid):
        s, e = self.fat[fid]
        return self.data[s:e]

    def overlays(self):
        out = []
        for i in range(self.ovt9_size // 32):
            ent = struct.unpack_from('<8I', self.data, self.ovt9_off + i*32)
            out.append(ent)  # id, ram, ramsize, bss, sinit_s, sinit_e, file_id, flags
        return out

if __name__ == '__main__':
    rom = NDS(sys.argv[1])
    print(rom.title, rom.code, 'files:', len(rom.files), 'fat:', len(rom.fat))
    print('arm9 off=%x load=%x size=%x entry=%x' % (rom.arm9_off, rom.arm9_load, rom.arm9_size, rom.arm9_entry))
    print('overlays9:', len(rom.overlays()))
    if len(sys.argv) > 2:
        out = sys.argv[2]
        for p, fid in rom.files.items():
            fp = os.path.join(out, 'data', p)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, 'wb').write(rom.read(fid))
        open(os.path.join(out, 'arm9.bin'), 'wb').write(rom.data[rom.arm9_off:rom.arm9_off+rom.arm9_size])
        open(os.path.join(out, 'arm7.bin'), 'wb').write(rom.data[rom.arm7_off:rom.arm7_off+rom.arm7_size])
        os.makedirs(os.path.join(out, 'overlay'), exist_ok=True)
        for ov in rom.overlays():
            open(os.path.join(out, 'overlay', 'overlay_%04d.bin' % ov[0]), 'wb').write(rom.read(ov[6]))
