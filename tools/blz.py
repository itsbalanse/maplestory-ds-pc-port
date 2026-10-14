"""Nintendo DS backward-LZ (BLZ) decompression used for ARM9/overlays."""
import struct

def blz_decompress(data: bytes) -> bytes:
    if len(data) < 8:
        return data
    footer, extra = struct.unpack_from('<II', data, len(data) - 8)
    hdr_len = footer >> 24
    enc_len = footer & 0xFFFFFF
    if extra == 0 and hdr_len == 0:
        return data
    src = bytearray(data)
    out_len = len(data) + extra
    out = bytearray(out_len)
    out[:len(data)] = data
    in_pos = len(data) - hdr_len
    in_end = len(data) - enc_len
    out_pos = out_len
    while in_pos > in_end:
        in_pos -= 1
        flags = src[in_pos]
        for _ in range(8):
            if in_pos <= in_end:
                break
            if flags & 0x80:
                in_pos -= 2
                v = src[in_pos] | (src[in_pos + 1] << 8)
                ln = (v >> 12) + 3
                disp = (v & 0xFFF) + 3
                for _ in range(ln):
                    out_pos -= 1
                    out[out_pos] = out[out_pos + disp]
            else:
                in_pos -= 1
                out_pos -= 1
                out[out_pos] = src[in_pos]
            flags = (flags << 1) & 0xFF
    return bytes(out)
