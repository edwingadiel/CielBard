"""Regression: CielBard.lua must never assign a populated table or a proxy into
Settings (MMOMinion's DB proxy rejects both), and the ACR profile must drive
the engine through Step(true) regardless of config.enabled."""
from pathlib import Path
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute((ROOT / "CielBard" / "CielBard_Data.lua").read_text(encoding="utf-8"))
lua.execute(r'''
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
''')
lua.execute((ROOT / "CielBard" / "CielBard_Rotation.lua").read_text(encoding="utf-8"))
lua.execute((ROOT / "CielBard" / "CielBard.lua").read_text(encoding="utf-8"))

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

# Reload path: flat keys restore nested config.
lua.execute('Settings.CielBard["abilities.ApexArrow"] = false; Settings.CielBard["aoeTargets.Ladonsbite"] = 4')
lua.execute((ROOT / "CielBard" / "CielBard.lua").read_text(encoding="utf-8"))
lua.execute('handlers["Module.Initalize"]()')
assert lua.eval('CielBardEngine.config.abilities.ApexArrow') is False
assert lua.eval('CielBardEngine.config.aoeTargets.Ladonsbite') == 4
print("reload round-trip ok")
print("CielBard GUI/settings/ACR invariants passed.")
