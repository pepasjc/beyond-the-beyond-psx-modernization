"""Minimal MODE2/2352 PS1 disc helpers: ISO9660 lookup, file read/write with EDC/ECC,
and moving a grown file into the tail of a padding file."""
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

    def _record(self, name):
        """(sector lba, offset) of the directory record of a file."""
        pvd = self.user(16)
        root = pvd[156:190]
        lba, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
        parts = name.strip("\\/").split("\\")
        for part in parts[:-1]:
            lba, size = self._lookup(lba, size, part.upper())
        for s in range((size + 2047) // 2048):
            d = self.user(lba + s)
            p = 0
            while p < 2048 and d[p]:
                nl = d[p + 32]
                n = d[p + 33:p + 33 + nl].decode("latin1").split(";")[0]
                if n.upper() == parts[-1].upper():
                    return lba + s, p
                p += d[p]
        raise KeyError(name)

    def _set_extent(self, name, lba, size):
        sec, p = self._record(name)
        o = sec * SEC
        s = self.buf[o:o + SEC]
        struct.pack_into("<II", s, HDR + p + 2, lba, int.from_bytes(lba.to_bytes(4, "little"), "big"))
        struct.pack_into("<II", s, HDR + p + 10, size, int.from_bytes(size.to_bytes(4, "little"), "big"))
        fix_form1(s)
        self.buf[o:o + SEC] = s

    def move_file_into(self, name, data, donor):
        """Write `name` with new contents (any size) into the last sectors of
        the file `donor`, which shrinks by as many sectors (a padding file)."""
        dlba, dsize = self.find(donor)
        n = (len(data) + 2047) // 2048
        dn = (dsize + 2047) // 2048
        assert dsize % 2048 == 0 and n < dn
        lba = dlba + dn - n
        for i in range(n):
            o = (lba + i) * SEC
            s = self.buf[o:o + SEC]
            sub = 0x89 if i == n - 1 else 0x08         # data, last one also end of record/file
            s[16:24] = bytes((0, 0, sub, 0)) * 2
            s[HDR:HDR + 2048] = data[i * 2048:(i + 1) * 2048].ljust(2048, b"\0")
            fix_form1(s)
            self.buf[o:o + SEC] = s
        self._set_extent(donor, dlba, dsize - n * 2048)
        self._set_extent(name, lba, len(data))

    def save(self, path):
        open(path, "wb").write(self.buf)
