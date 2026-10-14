"""Rebuild an NDS ROM, replacing files by FAT id. Files are re-laid out after the first replaced one."""
import struct

def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def rebuild_rom(rom, replacements, align=0x200):
    d = bytearray(rom.data)
    fat = list(rom.fat)
    first = min(replacements)
    # everything from the first replaced file's start onward is re-laid out in original order
    order = sorted([i for i in range(len(fat)) if fat[i][0] >= fat[first][0] and fat[i][1] > fat[i][0]], key=lambda i: fat[i][0])
    pos = fat[first][0]
    out = bytearray(d[:pos])
    for i in order:
        blob = replacements.get(i, bytes(rom.data[fat[i][0]:fat[i][1]]))
        while len(out) % align: out.append(0xFF)
        fat[i] = (len(out), len(out) + len(blob))
        out += blob
    used = len(out)
    for i, (s, e) in enumerate(fat):
        struct.pack_into('<II', out, rom.fat_off + i*8, s, e)
    struct.pack_into('<I', out, 0x80, used)
    cap = 0x20000 << out[0x14]
    while len(out) < cap and len(out) < used: out.append(0xFF)
    # pad to power-of-two capacity like the original
    target = len(rom.data) if used <= len(rom.data) else 1 << (used - 1).bit_length()
    out += b'\xff' * (target - len(out))
    if target > len(rom.data):
        out[0x14] = max(0, (target >> 17).bit_length() - 1)
    struct.pack_into('<H', out, 0x15E, crc16(out[:0x15E]))
    return bytes(out)
