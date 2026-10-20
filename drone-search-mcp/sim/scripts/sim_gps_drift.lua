-- Slowly wandering GPS bias for SITL, like a real receiver's multipath/ionosphere error.
--
-- SITL's GPS is otherwise perfect apart from white noise, which the EKF averages away;
-- a real receiver's position is off by 1-3 m and that error drifts over minutes. Every
-- position the drone reports - and so every target position projected from it - carries
-- this bias. Drives SIM_GPS1_GLTCH_X/Y (degrees) with a mean-reverting random walk.
--   SCR_USER1: bias standard deviation (m), 0 disables
--   SCR_USER2: correlation time (s)
--   SCR_USER3: random seed

local DEG_PER_M = 1.0 / 111319.5
local bx, by = 0.0, 0.0
local seeded = false

local function gauss()
  local u1 = math.max(math.random(), 1e-9)
  local u2 = math.random()
  return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
end

local function update()
  local sigma = param:get("SCR_USER1") or 0
  local tau = math.max(param:get("SCR_USER2") or 120, 1)
  if not seeded then
    math.randomseed(math.floor(param:get("SCR_USER3") or 1))
    -- start somewhere on the stationary distribution, not at zero
    bx, by = sigma * gauss(), sigma * gauss()
    seeded = true
  end
  if sigma <= 0 then
    return update, 1000
  end
  local dt = 0.2
  local a = math.exp(-dt / tau)
  local q = sigma * math.sqrt(1 - a * a)
  bx = a * bx + q * gauss()
  by = a * by + q * gauss()
  param:set("SIM_GPS1_GLTCH_X", bx * DEG_PER_M)
  param:set("SIM_GPS1_GLTCH_Y", by * DEG_PER_M / math.cos(math.rad(47.4)))
  return update, 200
end

gcs:send_text(6, "sim_gps_drift.lua: GPS bias random walk active")
return update, 1000
