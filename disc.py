"""Minimal MODE2/2352 PS1 disc helpers: ISO9660 lookup, file read/write with EDC/ECC."""
import struct

SEC = 2352
HDR = 24  # sync(12) + header(4) + subheader(8)


def _edc_table():
    t = []
    for i in range(256):
        e = i
        for _ in range(8):
            e = (e >> 1) ^ (0xD8018001 if e & 1 else 0)
        t.append(e)
    return t


EDC = _edc_table()
ECC_F = [0] * 256
ECC_B = [0] * 256
for i in range(256):
    j = (i << 1) ^ (0x11D if i & 0x80 else 0)
    ECC_F[i] = j & 0xFF
    ECC_B[i ^ j & 0xFF] = i


def edc(data):
    e = 0
    for b in data:
        e = (e >> 8) ^ EDC[(e ^ b) & 0xFF]
    return e


def _ecc_pq(sector, major_count, minor_count, major_mult, minor_inc, out_off):
    # sector: bytearray of full 2352 sector; operates on bytes from offset 12
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            temp = sector[12 + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= temp
            b ^= temp
            a = ECC_F[a]
        a = ECC_B[ECC_F[a] ^ b]
        sector[12 + out_off + major] = a
        sector[12 + out_off + major + major_count] = a ^ b


def fix_form1(sector):
    """Recompute EDC+ECC of a MODE2 Form1 sector in place."""
    struct.pack_into("<I", sector, 0x818, edc(sector[16:0x818]))
    hdr = bytes(sector[12:16])
    sector[12:16] = b"\0\0\0\0"  # mode2: header zeroed for ECC
    _ecc_pq(sector, 86, 24, 2, 86, 0x81C - 12)
    _ecc_pq(sector, 52, 43, 86, 88, 0x8C8 - 12)
    sector[12:16] = hdr


class Disc:
    def __init__(self, path):
        self.buf = bytearray(open(path, "rb").read())

    def user(self, lba):
        o = lba * SEC + HDR
        return bytes(self.buf[o:o + 2048])

    def find(self, name):
        pvd = self.user(16)
        root = pvd[156:190]
        lba, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        for part in name.strip("\\/").split("\\"):
            lba, size = self._lookup(lba, size, part.upper())
        return lba, size

    def _lookup(self, lba, size, name):
        for s in range((size + 2047) // 2048):
            d = self.user(lba + s)
            p = 0
            while p < 2048 and d[p]:
                ln = d[p]
                nl = d[p + 32]
                n = d[p + 33:p + 33 + nl].decode("latin1").split(";")[0]
                if n.upper() == name:
                    return struct.unpack_from("<I", d, p + 2)[0], struct.unpack_from("<I", d, p + 10)[0]
                p += ln
        raise KeyError(name)

    def read_file(self, name):
        lba, size = self.find(name)
        return b"".join(self.user(lba + i) for i in range((size + 2047) // 2048))[:size]

    def write_file(self, name, data):
        lba, size = self.find(name)
        assert len(data) == size, "size change not supported"
        for i in range((size + 2047) // 2048):
            chunk = data[i * 2048:(i + 1) * 2048]
            o = (lba + i) * SEC
            old = bytes(self.buf[o + HDR:o + HDR + len(chunk)])
            if old == chunk:
                continue
            self.buf[o + HDR:o + HDR + len(chunk)] = chunk
            sec = self.buf[o:o + SEC]
            fix_form1(sec)
            self.buf[o:o + SEC] = sec

    def save(self, path):
        open(path, "wb").write(self.buf)
