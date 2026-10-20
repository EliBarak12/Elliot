-- Simulated battery for ArduPilot SITL driven by Gazebo (JSON backend).
--
-- SITL's JSON physics interface reports no battery current, so the stock analog monitor
-- sits at 100% forever and battery failsafes can never be exercised. This script is a
-- scripting battery backend (BATT_MONITOR 29): current is modelled from the four motor
-- outputs, integrated into consumed mAh, and reported to the autopilot exactly like a
-- real power module would. Everything downstream (SYS_STATUS, failsafes, the MCP server's
-- 30% reserve) then behaves as on hardware.

local CAPACITY_MAH = 3300
local CELLS = 4
local IDLE_A = 0.5        -- avionics, armed or not
local K_MOTOR = 8.3       -- A per motor at full throttle^1.5  (cruise ~13 A on this quad)
local R_INTERNAL = 0.015  -- ohm, voltage sag under load
local MOTOR_FUNCS = {33, 34, 35, 36}

local consumed_mah = 0.0
local last_ms = millis()

local function cell_voltage(frac_left)
  -- crude LiPo curve: 4.2 V full, plateau ~3.8 V, knee to 3.3 V
  local f = math.max(0.0, math.min(1.0, frac_left))
  if f > 0.2 then
    return 3.75 + 0.45 * (f - 0.2) / 0.8
  end
  return 3.3 + 0.45 * f / 0.2
end

local function update()
  local now = millis()
  local dt_s = (now - last_ms):tofloat() / 1000.0
  last_ms = now
  local current = IDLE_A
  if arming:is_armed() then
    for _, fn in ipairs(MOTOR_FUNCS) do
      local pwm = SRV_Channels:get_output_pwm(fn)
      if pwm then
        local thr = math.max(0.0, math.min(1.0, (pwm - 1100) / 800.0))
        current = current + K_MOTOR * thr ^ 1.5
      end
    end
  end
  consumed_mah = consumed_mah + current * dt_s / 3.6
  local frac = 1.0 - consumed_mah / CAPACITY_MAH
  local state = BattMonitorScript_State()
  state:healthy(true)
  state:cell_count(CELLS)
  state:voltage(CELLS * cell_voltage(frac) - current * R_INTERNAL)
  state:current_amps(current)
  state:consumed_mah(consumed_mah)
  state:capacity_remaining_pct(math.max(0, math.floor(frac * 100 + 0.5)))
  state:temperature(25)
  battery:handle_scripting(0, state)
  return update, 100
end

gcs:send_text(6, "sim_battery.lua: modelled battery active")
return update, 100
