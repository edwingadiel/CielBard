"""Regression: CielBard.lua must never assign a populated table or a proxy into
Settings (MMOMinion's DB proxy rejects both), the ACR profile must drive the
engine through Step(true) regardless of config.enabled, the ACR stub must
survive being evaluated before the module (0.5.1 review, High #4), and the
Optimized preset must be a complete reset of CielBardData.Defaults."""
from pathlib import Path
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
DATA_LUA = (ROOT / "CielBard" / "CielBard_Data.lua").read_text(encoding="utf-8")
ROTATION_LUA = (ROOT / "CielBard" / "CielBard_Rotation.lua").read_text(encoding="utf-8")
MAIN_LUA = (ROOT / "CielBard" / "CielBard.lua").read_text(encoding="utf-8")
ACR_STUB_LUA = (ROOT / "CielBard" / "acr" / "CielBard.lua").read_text(encoding="utf-8")

ENV_LUA = r'''
ticks = 5000
Now = function() ticks = ticks + 100; return ticks end
d = function() end
handlers = {}
RegisterEventHandler = function(ev, fn, name) handlers[ev] = fn end
GUI = setmetatable({}, { __index = function(t, k) return function(...) return false, false end end })
GUI.SetCond_FirstUseEver = 1

-- DB-proxy imitation: refuses populated tables and refuses proxy re-assignment.
local function makeProxy(id)
    local data = {}
    return setmetatable({ _id = id }, {
        __index = function(t, k) return data[k] end,
        __newindex = function(t, k, v)
            if type(v) == "table" then
                if getmetatable(v) ~= nil or next(v) ~= nil then
                    error("[Settings] - Error: I was too lazy to implement a copy function for the DB-Settings Table")
                end
                v = makeProxy(id .. "." .. tostring(k))
            end
            data[k] = v
        end,
        __pairs = function(t) return next, data, nil end,
    })
end
local root = {}
Settings = setmetatable({}, {
    __index = function(t, k) return root[k] end,
    __newindex = function(t, k, v)
        if type(v) == "table" then
            if getmetatable(v) ~= nil or next(v) ~= nil then
                error("[Settings] - Error: I was too lazy to implement a copy function for the DB-Settings Table")
            end
            v = makeProxy(k)
        end
        root[k] = v
    end,
})

MIsLoading = function() return false end
MIsLocked = function() return false end
MIsCasting = function() return false end
EntityList = function() return {} end
castLog = {}
local target = { id = 200, alive = true, targetable = true, distance2d = 10, los = true,
    hp = { current = 1000, percent = 100 }, buffs = {}, pos = { x = 0, y = 0, z = 0 } }
Player = { id = 100, alive = true, job = 23, incombat = true, hp = { percent = 100 }, buffs = {}, gauge = {},
    castinginfo = { lastcastid = 0, timesincecast = 999999 }, GetTarget = function() return target end }
local actions = {}
ActionList = { Get = function(self, t, id)
    if not actions[id] then
        actions[id] = { id = id, name = "A" .. id, usable = true, cd = 0, cdmax = 0, recasttime = 2.5,
            IsReady = function(s) return id == 16495 end,
            Cast = function(s, tid) table.insert(castLog, id) return true end }
    end
    return actions[id]
end, IsCasting = function() return false end }
ACR = { IsActive = function() return false, "" end }
'''


def new_runtime():
    """A fresh MMOMinion imitation with the data table and the engine loaded."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(DATA_LUA)
    lua.execute(ENV_LUA)
    lua.execute(ROTATION_LUA)
    return lua


lua = new_runtime()
lua.execute(MAIN_LUA)

# Init through the registered handler; must not raise the copy error.
lua.execute('handlers["Module.Initalize"]()')
lua.execute('handlers["Gameloop.Update"]()')
lua.execute('handlers["Gameloop.Draw"]()')
print("init/update/draw ok")

# Settings must contain flat primitive keys only.
flat_ok = lua.eval('''(function()
    local count, bad = 0, 0
    for k, v in pairs(Settings.CielBard) do
        count = count + 1
        if type(v) == "table" or k:find("^abilities$") then bad = bad + 1 end
    end
    return count > 20 and bad == 0
end)()''')
assert flat_ok, "settings were not persisted as flat primitives"
assert lua.eval('Settings.CielBard["abilities.ApexArrow"]') is True
assert lua.eval('Settings.CielBard["pulseMs"]') == 30
assert lua.eval('Settings.CielBard["aoeTargets.ShadowbiteBarrage"]') == 3
print("flat persistence ok")

# Standalone: config.enabled false -> no cast. ACR profile: casts anyway.
lua.execute('CielBardEngine.config.pulseMs = 0; CielBardEngine.config.requestThrottleMs = 0')
assert lua.eval('#castLog') == 0
lua.execute('ACR.IsActive = function() return true, "CielBard" end')
lua.execute('handlers["Gameloop.Update"]()')  # standalone loop must yield to ACR
assert lua.eval('#castLog') == 0
profile = lua.eval('CielBardACRProfile()')
assert profile.name == "CielBard" and profile.classes[23] is True
assert lua.eval('CielBardACRProfile().Cast()') is True
assert lua.eval('#castLog') == 1 and lua.eval('castLog[1]') == 16495
assert lua.eval('CielBardACRProfile() == CielBardACRProfile()')
print("ACR profile ok")

# --- Optimized preset is a complete reset (0.5.1 review, medium finding) ----
# Everything in CielBardData.Defaults is restored except the documented
# preserve list, then the preset's own overrides are merged on top.
lua.execute('''
local cfg = CielBardUI.config
-- preserved settings
cfg.enabled = true
cfg.showWindow = false
cfg.lockToolNoticeDismissed = true
cfg.advancedEnabled = true
cfg.soulVoiceGaugeIndex = 7
cfg.repertoireGaugeIndex = 6
cfg.songTimerGaugeIndex = 5
-- settings the old applyPreset did not restore
cfg.secondWindHP = 11
cfg.usePotion = true
cfg.potionMinimumTTK = 29
cfg.wmSwapRemaining = 4.4
cfg.apexOffcycleGauge = 100
cfg.dotRefreshSeconds = 5.5
cfg.requestThrottleMs = 500
cfg.requestDedupeMs = 0
cfg.debug = true
cfg.multiDot = true
cfg.maxWeaves = 1
cfg.executionMode = "GCD_ONLY"
cfg.abilities.ApexArrow = false
cfg.aoeTargets.Ladonsbite = 5
cfg.aoeTargets.ShadowbiteBarrage = 6
CielBardUI.ApplyPreset("Optimized")
''')
assert lua.eval('CielBardUI.config == CielBardEngine.config'), \
    "applyPreset must mutate the live config table the engine holds"
reset_report = lua.eval('''(function()
    local defaults, cfg = CielBardData.Defaults, CielBardUI.config
    for key, value in pairs(defaults) do
        if type(value) ~= "table" and not CielBardUI.PresetPreserved[key] and cfg[key] ~= value then
            return "not reset: " .. key .. " = " .. tostring(cfg[key])
        end
    end
    for key, value in pairs(defaults.abilities) do
        if cfg.abilities[key] ~= value then return "ability not reset: " .. key end
    end
    for key, value in pairs(defaults.aoeTargets) do
        if cfg.aoeTargets[key] ~= value then return "aoe threshold not reset: " .. key end
    end
    return "ok"
end)()''')
assert reset_report == "ok", reset_report
assert lua.eval('CielBardUI.config.enabled') is True
assert lua.eval('CielBardUI.config.showWindow') is False
assert lua.eval('CielBardUI.config.lockToolNoticeDismissed') is True
assert lua.eval('CielBardUI.config.advancedEnabled') is True
assert lua.eval('CielBardUI.config.soulVoiceGaugeIndex') == 7
assert lua.eval('CielBardUI.config.repertoireGaugeIndex') == 6
assert lua.eval('CielBardUI.config.songTimerGaugeIndex') == 5
assert lua.eval('CielBardUI.config.timingVersion') == 4
assert lua.eval('CielBardUI.config.multiDot') is False
assert lua.eval('CielBardUI.config.debug') is False
assert lua.eval('CielBardUI.config.preset') == "Optimized"

# A non-empty preset resets first and then applies only its own overrides.
lua.execute('CielBardUI.config.secondWindHP = 12; CielBardUI.ApplyPreset("Conservative")')
assert lua.eval('CielBardUI.config.secondWindHP') == lua.eval('CielBardData.Defaults.secondWindHP')
assert lua.eval('CielBardUI.config.maxWeaves') == 1
assert lua.eval('CielBardUI.config.burstDotGate') == "BOTH"
assert lua.eval('CielBardUI.config.preset') == "Conservative"
assert lua.eval('CielBardUI.config.enabled') is True, "the master switch survives a preset"
lua.execute('CielBardUI.ApplyPreset("Optimized")')
print("preset full reset ok")

# Reload path: flat keys restore nested config.
lua.execute('Settings.CielBard["abilities.ApexArrow"] = false; Settings.CielBard["aoeTargets.Ladonsbite"] = 4')
lua.execute(MAIN_LUA)
lua.execute('handlers["Module.Initalize"]()')
assert lua.eval('CielBardEngine.config.abilities.ApexArrow') is False
assert lua.eval('CielBardEngine.config.aoeTargets.Ladonsbite') == 4
print("reload round-trip ok")

# --- Saved multiDot=true is migrated off once (0.5.1 review, High #3) -------
lua.execute('Settings.CielBard["multiDot"] = true; Settings.CielBard["timingVersion"] = 3')
lua.execute(MAIN_LUA)
lua.execute('handlers["Module.Initalize"]()')
assert lua.eval('CielBardEngine.config.multiDot') is False, "multiDot should be migrated off"
assert lua.eval('CielBardEngine.config.timingVersion') == 4
# ...but a user who turns it back on afterwards keeps it.
lua.execute('Settings.CielBard["multiDot"] = true')
lua.execute(MAIN_LUA)
lua.execute('handlers["Module.Initalize"]()')
assert lua.eval('CielBardEngine.config.multiDot') is True, "the migration must only run once"
print("multiDot migration ok")

# --- Reverse load order: ACR evaluates the stub before CielBard.lua ---------
# The placeholder must still list the Bard job, must not error, and must start
# driving the real engine as soon as the module finishes loading.
reverse = new_runtime()
stub = reverse.execute(ACR_STUB_LUA)
reverse.globals().stubProfile = stub
assert stub.name == "CielBard", "the stub must keep the profile name"
assert stub.classes[23] is True, "the stub must advertise the Bard job id"
assert reverse.eval('type(CielBardACRProfile)') == "nil", "the module must not be loaded yet"
assert stub.Cast() is False, "the placeholder cannot cast before the module loads"
assert reverse.eval('stubProfile:Cast()') is False
reverse.eval('stubProfile.Draw()')  # lifecycle hooks must be safe before load
reverse.eval('stubProfile.OnUpdate(1, 2)')
assert reverse.eval('#castLog') == 0

reverse.execute(MAIN_LUA)
assert reverse.eval('type(CielBardACRProfile)') == "function"
assert stub.Cast() is True, "the stub must delegate to the real profile once it exists"
assert reverse.eval('#castLog') == 1 and reverse.eval('castLog[1]') == 16495
# The engine holds the whole GCD tier until the client confirms the accepted
# weaponskill, so step the mock clock past the request-dedupe window first.
reverse.execute('ticks = ticks + 1000')
assert reverse.eval('stubProfile:Cast()') is True, "colon calls delegate too"
assert reverse.eval('#castLog') == 2
# Fields the placeholder does not define itself read through to the profile.
assert reverse.eval('stubProfile.tags') == "assistonly;grindmode;dungeons"
assert reverse.eval('stubProfile.GUI ~= nil and stubProfile.GUI.name == "Ciel Bard"')
reverse.eval('stubProfile.OnUpdate(1, 2)')
reverse.eval('stubProfile.OnLoad()')
reverse.eval('stubProfile.OnClick(1, false, false, false, nil)')
# ACR owning execution means the standalone loop stays out.
assert reverse.eval('CielBardUI.drivenByACR()') is True
print("ACR stub reverse load order ok")

print("CielBard GUI/settings/ACR invariants passed.")
