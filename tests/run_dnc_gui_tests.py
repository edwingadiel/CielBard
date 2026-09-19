"""Regression for CielDancer.lua: settings are persisted to MMOMinion's DB
proxy as flat primitives only, the ACR profile drives the engine through
Step(true) regardless of config.enabled, the ACR stub survives being evaluated
before the module, the Optimized preset is a complete reset, and the module
coexists with CielBard in one Lua state."""
from pathlib import Path
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "CielDancer"
DATA_LUA = (MODULE / "CielDancer_Data.lua").read_text(encoding="utf-8")
ROTATION_LUA = (MODULE / "CielDancer_Rotation.lua").read_text(encoding="utf-8")
MAIN_LUA = (MODULE / "CielDancer.lua").read_text(encoding="utf-8")
ACR_STUB_LUA = (MODULE / "acr" / "CielDancer.lua").read_text(encoding="utf-8")
CASCADE = 15989

ENV_LUA = r'''
ticks = 5000
Now = function() ticks = ticks + 100; return ticks end
d = function() end
handlers = {}
RegisterEventHandler = function(ev, fn, name) handlers[name] = fn end
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
Player = { id = 100, alive = true, job = 38, incombat = true, hp = { percent = 100 }, buffs = {}, gauge = {},
    castinginfo = { lastcastid = 0, timesincecast = 999999 }, GetTarget = function() return target end }
local actions = {}
ActionList = { Get = function(self, t, id)
    if not actions[id] then
        actions[id] = { id = id, name = "A" .. id, usable = true, cd = 0, cdmax = 0, recasttime = 2.5,
            IsReady = function(s) return id == 15989 end,
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

# Init through the registered handlers; must not raise the copy error.
lua.execute('handlers["CielDancer.Init"]()')
lua.execute('handlers["CielDancer.Update"]()')
lua.execute('handlers["CielDancer.Draw"]()')
lua.execute('CielDancerUI.DrawWindow()')
print("init/update/draw ok")

# Settings must contain flat primitive keys only.
flat_ok = lua.eval('''(function()
    local count, bad = 0, 0
    for k, v in pairs(Settings.CielDancer) do
        count = count + 1
        if type(v) == "table" or k:find("^abilities$") then bad = bad + 1 end
    end
    return count > 20 and bad == 0
end)()''')
assert flat_ok, "settings were not persisted as flat primitives"
assert lua.eval('Settings.CielDancer["abilities.TechnicalStep"]') is True
assert lua.eval('Settings.CielDancer["pulseMs"]') == 30
assert lua.eval('Settings.CielDancer["aoeTargets.FanDanceII"]') == 2
assert lua.eval('Settings.CielDancer["settingsVersion"]') == 1
assert lua.eval('Settings.CielBard') is None, "the Dancer module must not touch Bard's settings"
print("flat persistence ok")

# Standalone: config.enabled false -> no cast. ACR profile: casts anyway.
lua.execute('CielDancerEngine.config.pulseMs = 0; CielDancerEngine.config.requestThrottleMs = 0')
assert lua.eval('#castLog') == 0
lua.execute('ACR.IsActive = function() return true, "CielDancer" end')
lua.execute('handlers["CielDancer.Update"]()')  # standalone loop must yield to ACR
assert lua.eval('#castLog') == 0
profile = lua.eval('CielDancerACRProfile()')
assert profile.name == "CielDancer" and profile.classes[38] is True
assert profile.classes[23] is None, "the Dancer profile must not claim Bard"
assert lua.eval('CielDancerACRProfile().Cast()') is True
assert lua.eval('#castLog') == 1 and lua.eval('castLog[1]') == CASCADE
assert lua.eval('CielDancerACRProfile() == CielDancerACRProfile()')
print("ACR profile ok")

# --- Optimized preset is a complete reset ---------------------------------
lua.execute('''
local cfg = CielDancerUI.config
cfg.enabled = true
cfg.showWindow = false
cfg.lockToolNoticeDismissed = true
cfg.advancedEnabled = true
cfg.featherGaugeIndex = 7
cfg.espritGaugeIndex = 6
cfg.secondWindHP = 11
cfg.usePotion = true
cfg.saberOffcycleEsprit = 55
cfg.tillanaMaxEsprit = 50
cfg.featherOffcycleCount = 1
cfg.requestThrottleMs = 500
cfg.requestDedupeMs = 0
cfg.debug = true
cfg.maxWeaves = 1
cfg.executionMode = "GCD_ONLY"
cfg.abilities.TechnicalStep = false
cfg.aoeTargets.Windmill = 5
CielDancerUI.ApplyPreset("Optimized")
''')
assert lua.eval('CielDancerUI.config == CielDancerEngine.config'), \
    "applyPreset must mutate the live config table the engine holds"
reset_report = lua.eval('''(function()
    local defaults, cfg = CielDancerData.Defaults, CielDancerUI.config
    for key, value in pairs(defaults) do
        if type(value) ~= "table" and not CielDancerUI.PresetPreserved[key] and cfg[key] ~= value then
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
assert lua.eval('CielDancerUI.config.enabled') is True
assert lua.eval('CielDancerUI.config.showWindow') is False
assert lua.eval('CielDancerUI.config.lockToolNoticeDismissed') is True
assert lua.eval('CielDancerUI.config.advancedEnabled') is True
assert lua.eval('CielDancerUI.config.featherGaugeIndex') == 7
assert lua.eval('CielDancerUI.config.espritGaugeIndex') == 6
assert lua.eval('CielDancerUI.config.preset') == "Optimized"
# The shared default tables must never be mutated through a live config.
assert lua.eval('CielDancerData.AbilityDefaults.TechnicalStep') is True
assert lua.eval('CielDancerData.AoEDefaults.Windmill') == 2

lua.execute('CielDancerUI.config.secondWindHP = 12; CielDancerUI.ApplyPreset("NoPartyBuffs")')
assert lua.eval('CielDancerUI.config.secondWindHP') == lua.eval('CielDancerData.Defaults.secondWindHP')
assert lua.eval('CielDancerUI.config.abilities.Devilment') is False
assert lua.eval('CielDancerUI.config.abilities.StandardStep') is True
assert lua.eval('CielDancerUI.config.enabled') is True, "the master switch survives a preset"
for name in list(lua.eval('CielDancerData.Presets')):
    lua.execute(f'CielDancerUI.ApplyPreset("{name}")')
    assert lua.eval('CielDancerUI.config.preset') == name
    assert lua.eval('CielDancerUI.config.enabled') is True
lua.execute('CielDancerUI.ApplyPreset("Optimized")')
print("preset full reset ok")

# Reload path: flat keys restore nested config.
lua.execute('Settings.CielDancer["abilities.TechnicalStep"] = false; Settings.CielDancer["aoeTargets.Windmill"] = 4')
lua.execute(MAIN_LUA)
lua.execute('handlers["CielDancer.Init"]()')
assert lua.eval('CielDancerEngine.config.abilities.TechnicalStep') is False
assert lua.eval('CielDancerEngine.config.aoeTargets.Windmill') == 4
print("reload round-trip ok")

# --- Reverse load order: ACR evaluates the stub before CielDancer.lua ----
reverse = new_runtime()
stub = reverse.execute(ACR_STUB_LUA)
reverse.globals().stubProfile = stub
assert stub.name == "CielDancer", "the stub must keep the profile name"
assert stub.classes[38] is True, "the stub must advertise the Dancer job id"
assert reverse.eval('type(CielDancerACRProfile)') == "nil", "the module must not be loaded yet"
assert stub.Cast() is False, "the placeholder cannot cast before the module loads"
assert reverse.eval('stubProfile:Cast()') is False
reverse.eval('stubProfile.Draw()')
reverse.eval('stubProfile.OnUpdate(1, 2)')
assert reverse.eval('#castLog') == 0

reverse.execute(MAIN_LUA)
assert reverse.eval('type(CielDancerACRProfile)') == "function"
assert stub.Cast() is True, "the stub must delegate to the real profile once it exists"
assert reverse.eval('#castLog') == 1 and reverse.eval('castLog[1]') == CASCADE
# The engine holds the whole GCD tier until the client confirms the accepted
# weaponskill, so step the mock clock past the request-dedupe window first.
reverse.execute('ticks = ticks + 1000')
assert reverse.eval('stubProfile:Cast()') is True, "colon calls delegate too"
assert reverse.eval('#castLog') == 2
assert reverse.eval('stubProfile.tags') == "assistonly;grindmode;dungeons"
assert reverse.eval('stubProfile.GUI ~= nil and stubProfile.GUI.name == "Ciel Dancer"')
reverse.eval('stubProfile.OnUpdate(1, 2)')
reverse.eval('stubProfile.OnLoad()')
reverse.eval('stubProfile.OnClick(1, false, false, false, nil)')
assert reverse.eval('CielDancerUI.drivenByACR()') is True
print("ACR stub reverse load order ok")

# --- Both modules side by side: no shared globals, no cross-talk ------------
both = LuaRuntime(unpack_returned_tuples=True)
both.execute((ROOT / "CielBard" / "CielBard_Data.lua").read_text(encoding="utf-8"))
both.execute(DATA_LUA)
both.execute(ENV_LUA)
both.execute((ROOT / "CielBard" / "CielBard_Rotation.lua").read_text(encoding="utf-8"))
both.execute(ROTATION_LUA)
both.execute((ROOT / "CielBard" / "CielBard.lua").read_text(encoding="utf-8"))
both.execute(MAIN_LUA)
assert both.eval('CielBardEngine ~= CielDancerEngine and CielBardUI ~= CielDancerUI')
assert both.eval('CielBardACRProfile().classes[23] == true and CielBardACRProfile().classes[38] == nil')
assert both.eval('CielDancerACRProfile().classes[38] == true')
for name in ("CielBard.Init", "CielBard.Update", "CielDancer.Init", "CielDancer.Update"):
    both.execute(f'handlers["{name}"]()')
both.execute('CielBardEngine.config.enabled = true; CielBardEngine.config.pulseMs = 0')
both.execute('CielBardEngine.OnUpdate()')
assert both.eval('#castLog') == 0, "CielBard must stay idle on a Dancer"
assert both.eval('CielBardEngine.state.lastDecision') == "Requires Bard"
print("side-by-side with CielBard ok")

print("CielDancer GUI/settings/ACR invariants passed.")
