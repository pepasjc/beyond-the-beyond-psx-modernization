"""Boot work/<cue> in Beetle, walk until the in-between pictures start, then
sample the main thread's saved context from the BIOS TCB (the BIOS stores it
on every interrupt) to see where a freeze is spinning."""
import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from emu import Game
from interp60 import STREAK

cue = sys.argv[1] if len(sys.argv) > 1 else 'work/smooth.cue'
g = Game(cue, 'card.mcd')
g.step(2120); g.press('start', 4, 4); g.step(480); g.press('start', 4, 4); g.step(600)
for _ in range(12): g.press('triangle', 4, 40)
g.step(240); g.press('triangle', 4, 20)
for i in range(300):
    g.step(1, hold=('right',))
    if g.u32(STREAK) >= 45: break
print('streak at', i, 'framecnt', g.u32(0x800C9058))
seen = collections.Counter()
for k in range(240):
    g.step(1)
    tcb = g.u32(g.u32(0x80000108))
    epc, ra, sp = g.u32(tcb + 0x88), g.u32(tcb + 0x84), g.u32(tcb + 0x7C)
    seen[(epc, ra)] += 1
    if k < 6 or k % 60 == 0:
        print(k, 'framecnt', g.u32(0x800C9058), 'tcb %08x epc %08x ra %08x sp %08x' % (tcb, epc, ra, sp))
for (epc, ra), n in seen.most_common(12):
    print('%08x ra %08x x%d' % (epc, ra, n))
print('queue', hex(g.u32(0x800CF240)), hex(g.u32(0x800CF244)))
names = 'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split()
tcb = g.u32(g.u32(0x80000108))
print(' '.join('%s=%08x' % (n, g.u32(tcb + 8 + 4 * i)) for i, n in enumerate(names)))
print('epc %08x hi %08x lo %08x sr %08x cause %08x' % tuple(g.u32(tcb + 0x88 + 4 * i) for i in range(5)))
sp = g.u32(tcb + 0x7C)
for a in range(sp - 0x60, sp + 0x100, 16):
    print('%08x' % a, ' '.join('%08x' % g.u32(a + j) for j in range(0, 16, 4)))
