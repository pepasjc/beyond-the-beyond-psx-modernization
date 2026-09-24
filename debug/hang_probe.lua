-- Boot a test disc to the field without a person and log where the CPU is.
-- Every 30 vsyncs: frame, pc, ra, sp and the game's own frame counter
-- (0x800C9058, advanced by the per-vblank handler), so a hang shows the PC
-- it is stuck at.  Output: work/hang_probe.txt
local OUT = os.getenv('HANG_PROBE_OUT') or 'E:/projects/beyond-the-beyond-psx-modernization/work/hang_probe.txt'
local out = io.open(OUT, 'w')
local function W(s) out:write(s .. '\n') out:flush() end
W('loaded ' .. os.date())
_G.keep = {}
local mem = PCSX.getMemPtr()
local function u32(a) local o = a - 0x80000000 return mem[o] + mem[o+1]*256 + mem[o+2]*65536 + mem[o+3]*16777216 end
local pad = PCSX.SIO0.slots[1].pads[1]
local START, TRI = 3, 12
local f, held, held_at = 0, nil, 0
local function tap(b) pad:setOverride(b) held = b held_at = f end
local field_at = nil
_G.keep[#_G.keep + 1] = PCSX.Events.createEventListener('GPU::Vsync', function()
  f = f + 1
  if held and f - held_at >= 5 then pad:clearOverride(held) held = nil end
  if not field_at then
    if f >= 1800 and f < 3200 and f % 150 == 0 then tap(START) end
    if f >= 3200 and f % 40 == 0 then tap(TRI) end
    if u32(0x8010E0D8) ~= 0 then field_at = f W('field at ' .. f) end
  end
  if f % 30 == 0 then
    local r = PCSX.getRegisters()
    W(string.format('f=%d pc=%08x ra=%08x sp=%08x framecnt=%d marker=%d', f, r.pc, r.GPR.n.ra, r.GPR.n.sp,
      u32(0x800C9058), u32(0x801E6760)))
  end
  if f >= 7000 or (field_at and f - field_at > 600) then W('done') out:close() PCSX.quit() end
end)
_G.keep[#_G.keep + 1] = PCSX.Events.createEventListener('ExecutionFlow::Pause', function(e)
  local r = PCSX.getRegisters()
  local g = r.GPR.n
  W(string.format('PAUSED f=%d pc=%08x ra=%08x sp=%08x v0=%08x v1=%08x a0=%08x a1=%08x a2=%08x t0=%08x t1=%08x t2=%08x s0=%08x s1=%08x s2=%08x s3=%08x',
    f, r.pc, g.ra, g.sp, g.v0, g.v1, g.a0, g.a1, g.a2, g.t0, g.t1, g.t2, g.s0, g.s1, g.s2, g.s3))
  if e and e.exception then W('exception') end
  out:flush()
end)
PCSX.resumeEmulator()
