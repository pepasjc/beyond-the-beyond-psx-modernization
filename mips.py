import struct
from capstone import *
EXE = open('patched.exe','rb').read()
PC, GP, TADDR, TSIZE = struct.unpack_from('<IIII', EXE, 0x10)
BASE = TADDR - 0x800
md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 + CS_MODE_LITTLE_ENDIAN)
md.detail = False
def word(a): return struct.unpack_from('<I', EXE, a-BASE)[0]
def dis(a, n=40, exe=None):
    e = exe or EXE
    for i in md.disasm(e[a-BASE:a-BASE+n*4], a):
        print(f'{i.address:08x}: {i.mnemonic:8s} {i.op_str}')
_all = None
def all_insns():
    global _all
    if _all is None:
        _all = []
        for off in range(0x800, 0x800+TSIZE, 4):
            b = EXE[off:off+4]
            r = list(md.disasm(b, BASE+off))
            _all.append((BASE+off, r[0].mnemonic if r else '?', r[0].op_str if r else ''))
    return _all
