-- Interactive: the player plays; this logs who moves the party in battle.
--
-- Write breakpoints on the three party actors' position/velocity
-- (actor+0x00 x, +0x04 z, +0x08 vx, +0x0C vz; actors at 0x800F9B20,
-- 0x48 bytes each).  Every distinct writer PC is logged once with its
-- registers, and each frame in which a party velocity is non-zero is logged
-- with the actor state/counter, so the walk-up can be matched to its code.

local OUT = 'E:/projects/beyond-the-beyond-psx-modernization/work/battle_walk_watch.txt'
local out = io.open(OUT, 'w')
local function W(s) out:write(s .. '\n') out:flush() end
W('loaded ' .. os.date())

_G.keep = {}
local mem = PCSX.getMemPtr()
local function u16(a) local o = a - 0x80000000 return mem[o] + mem[o + 1] * 256 end
local function s16(a) local v = u16(a) if v >= 0x8000 then v = v - 0x10000 end return v end

local ACT = 0x800F9B20
local f = 0
local seen = {}

local function watch(addr, name)
  _G.keep[#_G.keep + 1] = PCSX.addBreakpoint(addr, 'Write', 2, name, function(address, width, cause)
    local r = PCSX.getRegisters()
    local key = name .. string.format('%08x', r.pc)
    seen[key] = (seen[key] or 0) + 1
    if seen[key] == 1 then
      local g = r.GPR.n
      W(string.format('NEW %s pc=%08x f=%d ra=%08x v0=%08x v1=%08x a0=%08x a1=%08x a2=%08x t0=%08x t1=%08x s0=%08x s1=%08x s2=%08x s3=%08x',
        name, r.pc, f, g.ra, g.v0, g.v1, g.a0, g.a1, g.a2, g.t0, g.t1, g.s0, g.s1, g.s2, g.s3))
    end
    return true
  end)
end

for i = 0, 2 do
  local b = ACT + i * 0x48
  watch(b + 0x00, 'a' .. i .. '.x')
  watch(b + 0x04, 'a' .. i .. '.z')
  watch(b + 0x08, 'a' .. i .. '.vx')
  watch(b + 0x0C, 'a' .. i .. '.vz')
end

local t0 = os.clock()
_G.keep[#_G.keep + 1] = PCSX.Events.createEventListener('GPU::Vsync', function()
  f = f + 1
  for i = 0, 2 do
    local b = ACT + i * 0x48
    local vx, vz = s16(b + 8), s16(b + 12)
    if vx ~= 0 or vz ~= 0 then
      W(string.format('f=%d a%d pos=(%d,%d,%d) v=(%d,%d) state=%d cnt=%d',
        f, i, s16(b), s16(b + 2), s16(b + 4), vx, vz, s16(b + 0x14), s16(b + 0x16)))
    end
  end
  if f % 600 == 0 then
    W(string.format('vsync %d  %.1f fps', f, 600 / (os.clock() - t0)))
    t0 = os.clock()
  end
end)

W('armed')
