"""Compile a RetroAchievements set (the `r=patch` JSON) into the tables of ra/src/eval.h.

    python ra/compile_set.py <patch.json> <out set.c> [<out set.txt>]

set.txt (one "ach  id  points  memaddr  title" line per achievement) feeds ra/host/diff.c.
Anything eval.c does not implement raises an error, so a new revision of the set can't be
evaluated wrongly in silence.
"""
import json
import re
import sys
import textwrap

# memory reference: the byte or 16-bit word read; the operand picks the part of it
WORD = {"H": 0, " ": 1, "": 1}
PART = {"H": 0, " ": 0, "": 0, **{c: 1 + i for i, c in enumerate("MNOPQRST")}, "L": 9, "U": 10, "K": 11}
FLAGS = {None: 0, "A": 1, "B": 2, "N": 3, "O": 4, "Z": 5, "C": 6, "D": 7, "R": 8, "M": 9, "T": 10}
OPS = {None: 0, "=": 1, "!=": 2, "<": 3, "<=": 4, ">": 5, ">=": 6}
COND = re.compile(r"^(?:([A-Z]):)?(.+?)(?:(!=|<=|>=|=|<|>)(.+?))?(?:\.(\d+)\.)?$")
MEM = re.compile(r"^(d?)0x([ HMNOPQRSTLUK]?)([0-9a-fA-F]+)$")


def achievements(patch_json):
    p = json.load(open(patch_json, encoding="utf-8"))["PatchData"]
    # 101000001 is the server's "unknown emulator" warning; Flags 3 = core set
    return p, [a for a in p["Achievements"] if a["ID"] < 101000000 and a["Flags"] == 3]


def split_groups(memaddr):
    """Groups are separated by 'S', which is also a size letter after '0x'."""
    out, cur = [], ""
    for i, ch in enumerate(memaddr):
        if ch == "S" and not (i > 0 and memaddr[i - 1] == "x"):
            out.append(cur); cur = ""
        else:
            cur += ch
    return out + [cur]


class Set:
    def __init__(self):
        self.mem, self.consts, self.conds, self.groups, self.achs = [], [], [], [], []

    def _operand(self, s):
        m = MEM.match(s)
        if m:
            size, addr = m.group(2), int(m.group(3), 16)
            assert addr < 0x200000, hex(addr)
            ref = WORD.get(size, 0) << 24 | addr
            if ref not in self.mem:
                self.mem.append(ref)
            assert len(self.mem) <= 0x400
            return (2 if m.group(1) else 1) << 14 | PART[size] << 10 | self.mem.index(ref)
        if re.fullmatch(r"h[0-9a-fA-F]+", s):
            v = int(s[1:], 16)
        elif re.fullmatch(r"-?\d+", s):
            v = int(s) & 0xFFFFFFFF
        else:
            raise ValueError(f"operand not supported: {s}")
        if v not in self.consts:
            self.consts.append(v)
        return self.consts.index(v)

    def add(self, memaddr):
        first = len(self.groups)
        for g in split_groups(memaddr):
            start = len(self.conds)
            for c in g.split("_") if g else []:
                m = COND.match(c)
                if not m:
                    raise ValueError(c)
                flag, lhs, op, rhs, hits = m.groups()
                if flag not in FLAGS:
                    raise ValueError(f"flag not supported: {c}")
                if flag in ("A", "B"):
                    if op is not None:
                        raise ValueError(f"AddSource with an operator: {c}")
                elif op is None:
                    raise ValueError(f"no comparison: {c}")
                hits = int(hits or 0)
                if hits > 255:
                    raise ValueError(f"hit target over 255: {c}")
                self.conds.append((FLAGS[flag], OPS[op], self._operand(lhs), self._operand(rhs) if rhs else 0, hits))
            if self.conds[start:] and self.conds[-1][0] in (1, 2, 3, 4, 5, 6, 7):
                raise ValueError(f"group ends in a combining condition: {g}")
            self.groups.append((start, len(self.conds) - start))
        conds = self.conds[self.groups[first][0]:]
        pure = all(h == 0 and t not in (5, 6, 7, 8) for t, o, l, r, h in conds)
        self.achs.append((first, len(self.groups) - first, int(pure)))


def ascii(s):
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
         .replace("…", "...").replace("–", "-").replace("—", "-").replace("é", "e"))
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in " ".join(s.split()))


TITLE_COLS, DESC_COLS, DESC_LINES = 34, 36, 4


def texts(A):
    """Per achievement "title" NUL "line1\\nline2..." NUL, wrapped for the menu."""
    out = []
    for a in A:
        t = ascii(a["Title"])
        assert len(t) <= TITLE_COLS, t
        d = textwrap.wrap(ascii(a["Description"]), DESC_COLS)
        assert len(d) <= DESC_LINES, (a["Title"], d)
        out += [t, "\n".join(d)]
    return out


def pack_texts(strings):
    """A word dictionary: bytes 0x80.. stand for its entries (phrases of whole words, each
    with the space after it). Greedy: the phrase that saves the most bytes, until none
    saves any or the dictionary is full. Returns (dictionary, packed strings)."""
    toks = [re.findall(r"[^ \n]+ ?|\n", s) for s in strings]
    dic = []
    while len(dic) < 128:
        gain = {}
        for t in toks:
            for i in range(len(t)):
                for n in range(1, 7):
                    if i + n > len(t):
                        break
                    ph = tuple(t[i:i + n])
                    if any(isinstance(x, int) for x in ph) or "\n" in ph:
                        continue
                    gain[ph] = gain.get(ph, 0) + 1
        best, score = None, 0
        for ph, cnt in gain.items():
            ln = sum(len(x) for x in ph)
            s = cnt * (ln - 1) - (ln + 1)
            if s > score:
                best, score = ph, s
        if not best:
            break
        k = len(dic)
        dic.append("".join(best))
        new = []
        for t in toks:
            o, i = [], 0
            while i < len(t):
                if tuple(t[i:i + len(best)]) == best:
                    o.append(k); i += len(best)
                else:
                    o.append(t[i]); i += 1
            new.append(o)
        toks = new
    packed = [b"".join(bytes((0x80 + x,)) if isinstance(x, int) else x.encode() for x in t) for t in toks]
    return dic, packed


def unpack(dic, b):
    return "".join(dic[c - 0x80] if c >= 0x80 else chr(c) for c in b)


def carray(ctype, name, vals, per=16):
    vals = list(vals)
    rows = [", ".join(vals[i:i + per]) for i in range(0, len(vals), per)] or ["0"]
    return f"const {ctype} {name}[] = {{\n\t" + ",\n\t".join(rows) + "\n};\n"


def compile_set(patch_json, out_c, out_txt=None):
    p, A = achievements(patch_json)
    s = Set()
    for a in A:
        s.add(a["MemAddr"])
    strings = texts(A)
    dic, packed = pack_texts(strings)
    assert all(unpack(dic, b) == t for b, t in zip(packed, strings))
    blob, offs = bytearray(), []
    for b in packed:
        offs.append(len(blob)); blob += b + b"\0"
    dblob, doffs = bytearray(), []
    for d in dic:
        doffs.append(len(dblob)); dblob += d.encode() + b"\0"
    assert len(blob) < 0x10000 and len(dblob) < 0x10000
    with open(out_c, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"/* generated by ra/compile_set.py from RetroAchievements game {p['ID']}, \"{ascii(p['Title'])}\" */\n")
        f.write('#include "eval.h"\n#include "meta.h"\n')
        f.write(f"const uint16_t ra_nmem = {len(s.mem)}, ra_nconst = {len(s.consts)}, ra_ncond = {len(s.conds)}, ra_nach = {len(A)};\n")
        f.write(carray("uint32_t", "ra_mem", (f"{m:#010x}" for m in s.mem), 8))
        assert max(s.consts) < 0x10000
        f.write(carray("uint16_t", "ra_const", (str(v) for v in s.consts), 12))
        code, at = bytearray(), []
        for t, o, l, r, h in s.conds:
            at.append(len(code))
            code += bytes((t | o << 4, l & 255, l >> 8))
            if t not in (1, 2):
                code += bytes((r & 255, r >> 8, h))
        assert len(code) < 0x10000
        f.write(carray("uint8_t", "ra_code", map(str, code), 24))
        f.write(carray("struct ra_group", "ra_group", (f"{{{at[a] if n else 0},{a},{n},0}}" for a, n in s.groups), 8))
        f.write(carray("struct ra_ach", "ra_ach", (f"{{{a},{n},{p}}}" for a, n, p in s.achs), 10))
        f.write(f"uint16_t ra_val[{len(s.mem)}], ra_dlt[{len(s.mem)}];\n")
        f.write(f"uint8_t ra_hit[{len(s.conds)}];\nuint8_t ra_st[{len(A)}], ra_hh[{len(A)}];\n")
        f.write(f"const uint16_t ra_total_points = {sum(a['Points'] for a in A)};\n")
        f.write(carray("uint8_t", "ra_points", (str(a["Points"]) for a in A), 20))
        f.write(carray("uint8_t", "ra_text", map(str, blob), 24))
        f.write(carray("char", "ra_dict", map(str, dblob), 24))
    if out_txt:
        with open(out_txt, "w", encoding="utf-8", newline="\n") as f:
            for a in A:
                f.write(f"ach\t{a['ID']}\t{a['Points']}\t{a['MemAddr']}\t{ascii(a['Title'])}\n")
    return dict(achievements=len(A), points=sum(a["Points"] for a in A), memrefs=len(s.mem),
                conditions=len(s.conds), consts=len(s.consts), text=sum(map(len, strings)),
                packed=len(blob) + len(dblob))


if __name__ == "__main__":
    print(compile_set(*sys.argv[1:]))
