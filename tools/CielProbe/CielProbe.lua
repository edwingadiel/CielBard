-- CielProbe: dumps the live MMOMinion Lua API surface to a text file so it
-- can be inspected offline. It never casts, never moves, and never changes
-- settings. Output: LuaMods/CielProbe/api_dump.txt (plus console summary).

CielProbe = CielProbe or {}
local probeDefaults = {
    initAt = 0,
    dumpsDone = 0,
    schedule = { 15000, 60000, 180000 },
    lastStatus = "waiting",
    windowOpen = true,
}
for key, value in pairs(probeDefaults) do
    if CielProbe[key] == nil then CielProbe[key] = value end
end

local KEYWORDS = { "anim", "lock", "latenc", "ping", "clip", "weave", "queue", "delay", "throttle", "rtt", "lag" }
local SPECIAL_ROOTS = { "Tensor", "Riku", "ACR", "gACR", "gTensor", "gRiku", "SkillMgr", "Hacks", "GameHacks" }

local function now()
    if type(Now) == "function" then return Now() end
    return math.floor(os.clock() * 1000)
end

local function safeTostring(value)
    local ok, result = pcall(tostring, value)
    return ok and result or "<tostring failed>"
end

local function matchesKeyword(name)
    local lower = string.lower(safeTostring(name))
    for _, keyword in ipairs(KEYWORDS) do
        if string.find(lower, keyword, 1, true) then return true end
    end
    return false
end

local function startsWithAny(name, prefixes)
    for _, prefix in ipairs(prefixes) do
        if string.sub(name, 1, #prefix) == prefix then return true end
    end
    return false
end

local function sortedKeys(tbl)
    local keys = {}
    local ok = pcall(function()
        for key in pairs(tbl) do table.insert(keys, key) end
    end)
    if not ok then return {}, false end
    table.sort(keys, function(a, b) return safeTostring(a) < safeTostring(b) end)
    return keys, true
end

local function describe(value)
    local kind = type(value)
    if kind == "string" then return string.format("%q", value) end
    if kind == "number" or kind == "boolean" or kind == "nil" then return safeTostring(value) end
    if kind == "function" then return "function" end
    if kind == "table" then
        local count = 0
        pcall(function() for _ in pairs(value) do count = count + 1 end end)
        return "table(" .. count .. ")"
    end
    return kind .. " " .. safeTostring(value)
end

-- Output buffer -------------------------------------------------------------

local lines = {}
local function out(text) table.insert(lines, text) end

local hits = {}
local function noteHit(path, value)
    table.insert(hits, path .. " = " .. describe(value))
end

-- Recursive dump with cycle protection ---------------------------------------

local visited = {}

local function dumpTable(tbl, path, depth, maxDepth, maxEntries)
    if depth > maxDepth then return end
    if visited[tbl] then out(path .. "  (already dumped)") return end
    visited[tbl] = true
    local keys, ok = sortedKeys(tbl)
    if not ok then out(path .. "  <pairs() failed>") return end
    local shown = 0
    for _, key in ipairs(keys) do
        shown = shown + 1
        if shown > maxEntries then out(path .. "  ... " .. (#keys - maxEntries) .. " more") break end
        local value = tbl[key]
        local childPath = path .. "." .. safeTostring(key)
        out(childPath .. " = " .. describe(value))
        if matchesKeyword(key) then noteHit(childPath, value) end
        if type(value) == "table" then
            dumpTable(value, childPath, depth + 1, maxDepth, maxEntries)
        end
    end
end

-- Function provenance -----------------------------------------------------------

local function describeFunction(fn)
    if type(fn) ~= "function" then return describe(fn) end
    if type(debug) ~= "table" or type(debug.getinfo) ~= "function" then return "function (no debug lib)" end
    local ok, info = pcall(debug.getinfo, fn, "S")
    if not ok or not info then return "function (getinfo failed)" end
    return string.format("function what=%s source=%s short=%s line=%s addr=%s",
        safeTostring(info.what), safeTostring(info.source), safeTostring(info.short_src),
        safeTostring(info.linedefined), safeTostring(fn))
end

local function probeFunctions(name, obj, fields)
    out("")
    out("### function provenance: " .. name)
    if obj == nil then out("  nil") return end
    for _, field in ipairs(fields) do
        local ok, value = pcall(function() return obj[field] end)
        if ok and value ~= nil then out("  " .. field .. " = " .. describeFunction(value)) end
    end
    local mt = getmetatable(obj)
    if type(mt) == "table" then
        for _, key in ipairs((sortedKeys(mt))) do
            out("  <mt>." .. safeTostring(key) .. " = " .. describeFunction(mt[key]))
        end
    end
end

-- Userdata/metatable probing --------------------------------------------------

local function probeObject(name, obj, candidates)
    out("")
    out("### " .. name .. "  (" .. type(obj) .. ")")
    if obj == nil then out("  nil") return end
    local mt = getmetatable(obj)
    if mt == nil then
        out("  metatable: none")
    elseif type(mt) ~= "table" then
        out("  metatable: protected (" .. type(mt) .. ")")
    else
        out("  metatable keys:")
        for _, key in ipairs((sortedKeys(mt))) do
            out("    " .. safeTostring(key) .. " = " .. describe(mt[key]))
            if matchesKeyword(key) then noteHit(name .. ".<mt>." .. safeTostring(key), mt[key]) end
        end
        if type(mt.__index) == "table" then
            out("  __index keys:")
            for _, key in ipairs((sortedKeys(mt.__index))) do
                out("    " .. safeTostring(key) .. " = " .. describe(mt.__index[key]))
                if matchesKeyword(key) then noteHit(name .. ".__index." .. safeTostring(key), mt.__index[key]) end
            end
        end
    end
    if type(obj) == "table" or type(obj) == "userdata" then
        local ok = pcall(function()
            local keys, okKeys = sortedKeys(obj)
            if okKeys and #keys > 0 then
                out("  pairs():")
                for _, key in ipairs(keys) do
                    out("    " .. safeTostring(key) .. " = " .. describe(obj[key]))
                    if matchesKeyword(key) then noteHit(name .. "." .. safeTostring(key), obj[key]) end
                end
            end
        end)
        if not ok then out("  pairs(): failed") end
    end
    if candidates then
        out("  candidate fields:")
        for _, field in ipairs(candidates) do
            local ok, value = pcall(function() return obj[field] end)
            if ok and value ~= nil then
                out("    " .. field .. " = " .. describe(value))
                if matchesKeyword(field) then noteHit(name .. "." .. field, value) end
            elseif not ok then
                out("    " .. field .. " = <error " .. safeTostring(value) .. ">")
            end
        end
    end
end

-- Main dump -------------------------------------------------------------------

function CielProbe.Dump(reason)
    lines, hits, visited = {}, {}, {}
    out("CielProbe API dump  reason=" .. tostring(reason) .. "  tick=" .. tostring(now()))
    out("")

    -- 1. Globals overview.
    out("## _G keys")
    local globals, ok = sortedKeys(_G)
    out("count=" .. #globals .. " pairs_ok=" .. tostring(ok))
    for _, key in ipairs(globals) do
        local name = safeTostring(key)
        local value = _G[key]
        out(name .. " = " .. describe(value))
        if matchesKeyword(name) then noteHit("_G." .. name, value) end
    end

    -- 2. Deep dump of addon roots (Tensor*, Riku*, ACR*, SkillMgr, Hacks).
    out("")
    out("## Addon roots (depth 3)")
    for _, key in ipairs(globals) do
        local name = safeTostring(key)
        local value = _G[key]
        if type(value) == "table" and startsWithAny(name, SPECIAL_ROOTS) then
            out("")
            out("### " .. name)
            dumpTable(value, name, 1, 3, 400)
        end
    end

    -- 3. Keyword scan across every global table, depth 2.
    out("")
    out("## Keyword scan of all global tables (depth 2)")
    visited = {}
    for _, key in ipairs(globals) do
        local value = _G[key]
        local name = safeTostring(key)
        if type(value) == "table" and value ~= _G and not startsWithAny(name, SPECIAL_ROOTS) then
            local inner, okInner = sortedKeys(value)
            if okInner then
                for _, innerKey in ipairs(inner) do
                    if matchesKeyword(innerKey) then noteHit(name .. "." .. safeTostring(innerKey), value[innerKey]) end
                    local child = value[innerKey]
                    if type(child) == "table" and child ~= _G and not visited[child] then
                        visited[child] = true
                        local deeper, okDeeper = sortedKeys(child)
                        if okDeeper then
                            for _, deepKey in ipairs(deeper) do
                                if matchesKeyword(deepKey) then
                                    noteHit(name .. "." .. safeTostring(innerKey) .. "." .. safeTostring(deepKey), child[deepKey])
                                end
                            end
                        end
                    end
                end
            end
        end
    end

    -- 4. Settings: Tensor/Riku/ACR sections in full, other sections by key.
    out("")
    out("## Settings")
    if type(Settings) == "table" then
        visited = {}
        local sections = sortedKeys(Settings)
        for _, section in ipairs(sections) do
            local name = safeTostring(section)
            local value = Settings[section]
            out("Settings." .. name .. " = " .. describe(value))
            if type(value) == "table" then
                if startsWithAny(name, SPECIAL_ROOTS) or string.find(string.lower(name), "tensor", 1, true) or
                    string.find(string.lower(name), "riku", 1, true) or string.find(string.lower(name), "acr", 1, true) then
                    dumpTable(value, "Settings." .. name, 1, 4, 600)
                else
                    for _, key in ipairs((sortedKeys(value))) do
                        if matchesKeyword(key) then noteHit("Settings." .. name .. "." .. safeTostring(key), value[key]) end
                    end
                end
            end
        end
    else
        out("Settings is " .. type(Settings))
    end

    -- 5. Native objects.
    out("")
    out("## Native objects")
    probeObject("Hacks", Hacks, { "SetAnimationLock", "AnimationLock", "SetAnimLock", "animationlock", "SetLatency", "Ping", "SkipCutscene", "SetPermaSprint", "SetPermaBuff", "WinMiniGame" })
    probeObject("GameHacks", GameHacks)
    probeObject("ActionList", ActionList, { "IsCasting", "CanCast", "Cast", "Get", "GetAnimationLock", "animationlock", "IsReady", "queued", "Queue" })
    probeObject("Player", Player, { "id", "job", "incombat", "action", "lastaction", "combotimeremain", "animationlock", "animlock", "gcd", "gcdremaining", "gcdmax", "latency", "ping", "castinginfo", "gauge", "gaugetest", "stats", "settings" })
    if Player then
        probeObject("Player.castinginfo", Player.castinginfo, { "castingid", "casttime", "castingtargetcount", "castinginterruptible", "lastcastid", "timesincecast", "channelingid", "channeltargetid", "channeltime", "animationlock", "animlock", "lock", "queued" })
        probeObject("Player.gauge", Player.gauge)
        probeObject("Player.gaugetest", Player.gaugetest)
        probeObject("Player.stats", Player.stats)
    end
    if ActionList then
        local okAction, actionObj = pcall(function() return ActionList:Get(1, 16495) end)
        if okAction then
            probeObject("Action(BurstShot 16495)", actionObj, { "id", "name", "type", "cd", "cdmax", "recasttime", "casttime", "isoncd", "isready", "usable", "highlighted", "statusgainedid", "animationlock", "animlock", "lock", "lockremaining", "queued", "isqueued", "cancast", "charges", "maxcharges", "cost", "range", "radius", "level", "job", "iscasting", "recasttimeremain", "castremaining", "combo", "iscombo" })
        else
            out("ActionList:Get(1,16495) failed: " .. safeTostring(actionObj))
        end
        local okItem, itemAction = pcall(function() return ActionList:Get(2, 45996) end)
        if okItem then probeObject("Action(type2 item 45996)", itemAction, { "id", "name", "type", "cd", "cdmax", "isoncd", "isready" }) end
    end
    probeObject("EntityList", EntityList)
    if type(Settings) == "table" and type(Settings.data) == "table" then
        out("")
        out("## Settings.data (full, depth 5)")
        visited = {}
        dumpTable(Settings.data, "Settings.data", 1, 5, 800)
    end
    if Player then probeObject("Player.settings", Player.settings) end
    if ActionList then
        local okA, a = pcall(function() return ActionList:Get(1, 16495) end)
        if okA and a then
            probeFunctions("Action(BurstShot)", a, { "Cast", "oCastT", "IsReady", "CanCastResult", "IsFacing", "IsInRange" })
            local same = false
            pcall(function() same = (a.Cast == a.oCastT) end)
            out("  Cast == oCastT: " .. tostring(same))
        end
        probeFunctions("ActionList", ActionList, { "Get", "IsReady", "IsCasting", "StopCasting", "GetTypes" })
    end
    probeFunctions("Hacks", Hacks, { "SkipCutscene", "TeleportToXYZ", "WinMiniGame" })
    probeFunctions("_G", _G, { "Now", "TimeSince", "RegisterEventHandler", "GetLuaModsPath", "GetPrivateModuleTable", "SetPrivateModuleTable", "GetPrivateModuleFunctions", "QueueEvent", "EventQueue" })
    out("")
    out("## Globals that are Lua functions (not native), with source")
    local luaFns = 0
    for _, key in ipairs(globals) do
        local value = _G[key]
        if type(value) == "function" and type(debug) == "table" then
            local okI, info = pcall(debug.getinfo, value, "S")
            if okI and info and info.what == "Lua" then
                luaFns = luaFns + 1
                if luaFns <= 400 then out(safeTostring(key) .. " <- " .. safeTostring(info.short_src) .. ":" .. safeTostring(info.linedefined)) end
            end
        end
    end
    out("lua function globals: " .. luaFns)
    probeObject("Inventory", Inventory, { "Get" })
    if type(GetPrivateModuleFunctions) == "function" then
        local okFns, fns = pcall(GetPrivateModuleFunctions)
        if okFns then probeObject("GetPrivateModuleFunctions()", fns) end
    end
    if type(modulefunctions) ~= "nil" then probeObject("modulefunctions", modulefunctions) end

    -- 6. Registered event handlers, if MinionLib exposes them.
    out("")
    out("## Event handlers")
    if type(ml_event_mgr) == "table" then
        dumpTable(ml_event_mgr, "ml_event_mgr", 1, 3, 300)
    elseif type(GetEventHandlers) == "function" then
        local okEv, ev = pcall(GetEventHandlers)
        if okEv and type(ev) == "table" then dumpTable(ev, "GetEventHandlers()", 1, 3, 300) end
    else
        out("no handler registry found")
    end

    -- 7. Keyword hits summary at the top of the file.
    local header = {}
    table.insert(header, "## KEYWORD HITS (" .. #hits .. ")  [anim lock latency ping clip weave queue delay throttle rtt lag]")
    table.sort(hits)
    local previous = nil
    for _, hit in ipairs(hits) do
        if hit ~= previous then table.insert(header, hit) end
        previous = hit
    end
    table.insert(header, "")
    for index = #header, 1, -1 do table.insert(lines, 1, header[index]) end

    return CielProbe.Write(reason)
end

function CielProbe.Write(reason)
    local text = table.concat(lines, "\n")
    local base = (type(GetLuaModsPath) == "function" and GetLuaModsPath()) or ""
    local path = base .. "CielProbe" .. "\\" .. "api_dump.txt"
    local written = false
    if type(io) == "table" and type(io.open) == "function" then
        local ok, file = pcall(io.open, path, "w")
        if ok and file then
            file:write(text)
            file:close()
            written = true
        end
    end
    if not written and type(persistence) == "table" and type(persistence.store) == "function" then
        local ok = pcall(persistence.store, base .. "CielProbe\\api_dump.lua", { text = text })
        written = ok
        path = base .. "CielProbe\\api_dump.lua"
    end
    CielProbe.dumpsDone = CielProbe.dumpsDone + 1
    CielProbe.lastStatus = (written and "wrote " or "FAILED to write ") .. path .. " (" .. #lines .. " lines, " .. #hits .. " keyword hits, " .. tostring(reason) .. ")"
    if type(d) == "function" then
        d("[CielProbe] " .. CielProbe.lastStatus)
        for index = 1, math.min(#hits, 40) do d("[CielProbe] hit: " .. hits[index]) end
    end
    return written
end

-- Cast timeline logger --------------------------------------------------------
-- Records every cast the client reports (manual, ACR, or CielBard) with a
-- millisecond timestamp. The gap between two consecutive oGCDs is the
-- effective animation lock as the client experiences it.

CielProbe.castLog = CielProbe.castLog or {}
CielProbe.lastLoggedCastID = CielProbe.lastLoggedCastID or 0
CielProbe.lastLoggedSince = CielProbe.lastLoggedSince or 999999
CielProbe.castLogSaves = CielProbe.castLogSaves or 0

local GCD_RECAST_MIN = 1.5  -- anything with recasttime in [1.5, 3.5] is treated as a GCD

local function actionInfo(id)
    if not ActionList then return "?", false end
    local ok, ac = pcall(function() return ActionList:Get(1, id) end)
    if not ok or not ac then return "?", false end
    local recast = tonumber(ac.recasttime) or 0
    return safeTostring(ac.name), recast >= GCD_RECAST_MIN and recast <= 3.5
end

function CielProbe.ObserveCasts()
    if not Player or not Player.castinginfo then return end
    local info = Player.castinginfo
    local castID = tonumber(info.lastcastid) or 0
    local since = tonumber(info.timesincecast) or 999999
    local isNew = castID ~= 0 and (castID ~= CielProbe.lastLoggedCastID or since + 30 < CielProbe.lastLoggedSince)
    CielProbe.lastLoggedSince = since
    if not isNew then return end
    CielProbe.lastLoggedCastID = castID
    local name, isGCD = actionInfo(castID)
    local tick = now()
    -- timesincecast says how long ago the cast really happened; use it to
    -- correct for polling delay so gaps are accurate to the frame.
    local castAt = tick - (since < 5000 and since or 0)
    local last = CielProbe.castLog[#CielProbe.castLog]
    if last and last.id == castID and castAt - last.t < 300 then return end
    table.insert(CielProbe.castLog, { t = castAt, seen = tick, id = castID, name = name, gcd = isGCD })
    while #CielProbe.castLog > 600 do table.remove(CielProbe.castLog, 1) end
end

local function pingSettingsSnapshot()
    local found = {}
    local function scan(tbl, path, depth)
        if depth > 5 or type(tbl) ~= "table" then return end
        local keys, ok = sortedKeys(tbl)
        if not ok then return end
        for _, key in ipairs(keys) do
            local name = safeTostring(key)
            local value = tbl[key]
            local lower = string.lower(name)
            if type(value) ~= "table" and (string.find(lower, "ping", 1, true) or string.find(lower, "queue", 1, true) or
                string.find(lower, "weave", 1, true) or string.find(lower, "anim", 1, true) or string.find(lower, "lock", 1, true)) then
                table.insert(found, path .. "." .. name .. " = " .. describe(value))
            elseif type(value) == "table" then
                scan(value, path .. "." .. name, depth + 1)
            end
        end
    end
    if type(Settings) == "table" then scan(Settings, "Settings", 1) end
    return found
end

local function gapStats(list)
    if #list == 0 then return "n=0" end
    table.sort(list)
    local sum = 0
    for _, v in ipairs(list) do sum = sum + v end
    return string.format("n=%d min=%d median=%d mean=%d max=%d", #list, list[1], list[math.ceil(#list / 2)], math.floor(sum / #list), list[#list])
end

function CielProbe.SaveCastLog(label)
    local text = {}
    table.insert(text, "==== cast log  label=" .. tostring(label) .. "  tick=" .. tostring(now()) .. "  entries=" .. #CielProbe.castLog)
    for _, line in ipairs(pingSettingsSnapshot()) do table.insert(text, "setting  " .. line) end
    table.insert(text, "t_ms\tgap_ms\tprev_kind\tkind\tid\tname")
    local prev = nil
    local ogcdGaps, gcdToOgcd = {}, {}
    for _, entry in ipairs(CielProbe.castLog) do
        local gap = prev and (entry.t - prev.t) or 0
        table.insert(text, string.format("%d\t%d\t%s\t%s\t%d\t%s",
            entry.t, gap, prev and (prev.gcd and "GCD" or "oGCD") or "-", entry.gcd and "GCD" or "oGCD", entry.id, entry.name))
        if prev and gap < 2000 then
            if not prev.gcd and not entry.gcd then table.insert(ogcdGaps, gap) end
            if prev.gcd and not entry.gcd then table.insert(gcdToOgcd, gap) end
        end
        prev = entry
    end
    local summary1 = "summary oGCD->oGCD gaps: " .. gapStats(ogcdGaps)
    local summary2 = "summary GCD->oGCD gaps:  " .. gapStats(gcdToOgcd)
    table.insert(text, summary1)
    table.insert(text, summary2)
    table.insert(text, "")
    local base = (type(GetLuaModsPath) == "function" and GetLuaModsPath()) or ""
    local path = base .. "CielProbe\\cast_log.txt"
    local written = false
    if type(io) == "table" and type(io.open) == "function" then
        local ok, file = pcall(io.open, path, "a")
        if ok and file then
            file:write(table.concat(text, "\n"))
            file:close()
            written = true
        end
    end
    CielProbe.castLogSaves = CielProbe.castLogSaves + 1
    CielProbe.lastStatus = (written and "appended cast log to " or "FAILED cast log ") .. path .. " (" .. #CielProbe.castLog .. " casts)"
    if type(d) == "function" then
        d("[CielProbe] " .. CielProbe.lastStatus)
        d("[CielProbe] " .. summary1)
        d("[CielProbe] " .. summary2)
    end
    CielProbe.castLog = {}
    return written
end

function CielProbe.Init()
    CielProbe.initAt = now()
    if type(d) == "function" then d("[CielProbe] loaded; dumps at 15s, 60s, 180s or via the window button") end
end

function CielProbe.Update()
    if CielProbe.initAt == 0 then CielProbe.Init() end
    pcall(CielProbe.ObserveCasts)
    local elapsed = now() - CielProbe.initAt
    local nextIndex = CielProbe.dumpsDone + 1
    local due = CielProbe.schedule[nextIndex]
    if due and elapsed >= due then
        pcall(CielProbe.Dump, "scheduled " .. tostring(due) .. "ms")
    end
end

function CielProbe.Draw()
    if not CielProbe.windowOpen or not GUI then return end
    GUI:SetNextWindowSize(560, 210, GUI.SetCond_FirstUseEver)
    local visible
    visible, CielProbe.windowOpen = GUI:Begin("Ciel Probe", CielProbe.windowOpen)
    if visible then
        GUI:TextWrapped("Dumps the live Lua API surface to LuaMods/CielProbe/api_dump.txt. Casts nothing.")
        if GUI:Button("Dump API now", 160, 25) then
            pcall(CielProbe.Dump, "manual")
        end
        GUI:SameLine()
        if GUI:Button("Save cast log: ping OFF", 170, 25) then
            pcall(CielProbe.SaveCastLog, "ZeroPing OFF")
        end
        GUI:SameLine()
        if GUI:Button("Save cast log: ping ON", 170, 25) then
            pcall(CielProbe.SaveCastLog, "ZeroPing ON")
        end
        if GUI:Button("Save cast log: CielBard + ping ON", 240, 25) then
            pcall(CielProbe.SaveCastLog, "CielBard with ZeroPing ON (ACR loaded, not running)")
        end
        GUI:SameLine()
        if GUI:Button("Save cast log: CielBard + ping OFF", 240, 25) then
            pcall(CielProbe.SaveCastLog, "CielBard with ZeroPing OFF")
        end
        GUI:Text("Casts recorded since last save: " .. tostring(#CielProbe.castLog))
        GUI:TextWrapped("Status: " .. tostring(CielProbe.lastStatus))
        GUI:Text("Dumps done: " .. tostring(CielProbe.dumpsDone))
    end
    GUI:End()
end

RegisterEventHandler("Module.Initalize", CielProbe.Init, "CielProbe.Init")
RegisterEventHandler("Gameloop.Update", CielProbe.Update, "CielProbe.Update")
RegisterEventHandler("Gameloop.Draw", CielProbe.Draw, "CielProbe.Draw")
