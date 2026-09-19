local CielMachinist = {
    windowOpen = true,
    initialized = false,
    config = nil,
    dirty = false,
    lastSaveAt = 0,
}

local function deepCopy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, child in pairs(value) do result[key] = deepCopy(child) end
    return result
end

local function merge(destination, source)
    for key, value in pairs(source or {}) do
        if type(value) == "table" then
            destination[key] = type(destination[key]) == "table" and destination[key] or {}
            merge(destination[key], value)
        else
            destination[key] = value
        end
    end
end

-- Settings persistence ---------------------------------------------------------
-- MMOMinion's Settings object is a database-backed proxy. Assigning a table
-- that already has contents (or assigning the proxy back to itself) raises
-- "I was too lazy to implement a copy function for the DB-Settings Table".
-- The live config therefore stays in memory and is mirrored to the store as
-- flat primitive keys such as "abilities.Drill".

local function store()
    if type(Settings) ~= "table" then return nil end
    local ok, section = pcall(function() return Settings.CielMachinist end)
    if not ok then return nil end
    if section == nil then
        local okSet = pcall(function() Settings.CielMachinist = {} end)
        if not okSet then return nil end
        ok, section = pcall(function() return Settings.CielMachinist end)
        if not ok then return nil end
    end
    return section
end

local function flatten(tbl, prefix, out)
    for key, value in pairs(tbl) do
        local path = prefix and (prefix .. "." .. tostring(key)) or tostring(key)
        if type(value) == "table" then
            flatten(value, path, out)
        elseif type(value) ~= "function" then
            out[path] = value
        end
    end
    return out
end

local function setPath(tbl, path, value)
    local node = tbl
    local parts = {}
    for part in string.gmatch(path, "[^%.]+") do table.insert(parts, part) end
    for index = 1, #parts - 1 do
        local part = parts[index]
        if type(node[part]) ~= "table" then node[part] = {} end
        node = node[part]
    end
    node[parts[#parts]] = value
end

local function loadConfig()
    local config = deepCopy(CielMachinistData.Defaults)
    local section = store()
    if section then
        local ok, keys = pcall(function()
            local found = {}
            for key, value in pairs(section) do
                if type(key) == "string" and type(value) ~= "table" and type(value) ~= "function" then
                    found[key] = value
                end
            end
            return found
        end)
        if ok and keys then
            for path, value in pairs(keys) do setPath(config, path, value) end
        end
    end
    return config
end

local function saveConfig(config)
    local section = store()
    if not section then return false end
    local flat = flatten(config, nil, {})
    local ok = pcall(function()
        for path, value in pairs(flat) do
            if section[path] ~= value then section[path] = value end
        end
    end)
    return ok
end

local function settings()
    if not CielMachinist.config then CielMachinist.config = loadConfig() end
    return CielMachinist.config
end

local function markDirty()
    CielMachinist.dirty = true
end

local function flushIfDirty(force)
    if not CielMachinist.dirty and not force then return end
    local ticks = (type(Now) == "function" and Now()) or 0
    if not force and ticks - CielMachinist.lastSaveAt < 1000 then return end
    CielMachinist.lastSaveAt = ticks
    if saveConfig(settings()) then CielMachinist.dirty = false end
end

-- Settings migration ------------------------------------------------------------

local SETTINGS_VERSION = 1

-- One-time migrations for defaults that change after users have saved them.
-- Nothing to migrate yet; the version is stamped so later releases can tell.
local function migrateSettings(config)
    local version = tonumber(config.settingsVersion) or 0
    if version >= SETTINGS_VERSION then return end
    config.settingsVersion = SETTINGS_VERSION
    markDirty()
end

-- Lifecycle ----------------------------------------------------------------------

function CielMachinist.Init()
    local config = settings()
    migrateSettings(config)
    CielMachinist.windowOpen = config.showWindow ~= false
    CielMachinistEngine.Init(config)
    CielMachinist.initialized = true
    flushIfDirty(true)
    if type(d) == "function" then
        d("[CielMachinist] Loaded v" .. CielMachinistData.Version)
        if not config.lockToolNoticeDismissed then
            d("[CielMachinist] Tip: for better weaving, run XivAlexander (standalone) or NoClippy (Dalamud) alongside the bot. See the notice in the Ciel Machinist window.")
        end
    end
end

-- True when ACR is enabled with the CielMachinist profile selected. In that case
-- ACR's own Cast() callback drives the engine and the standalone loop stays out.
local lastACRReport = ""
local acrProfileRequested = false
local function drivenByACR()
    -- Once ACR has loaded the CielMachinist profile stub, ACR owns execution: the
    -- standalone loop never runs, even while ACR is disabled.
    if acrProfileRequested then return true end
    if type(ACR) ~= "table" or type(ACR.IsActive) ~= "function" then return false end
    local ok, active, name = pcall(ACR.IsActive)
    local report = tostring(ok) .. "/" .. tostring(active) .. "/" .. tostring(name)
    if report ~= lastACRReport then
        lastACRReport = report
        if type(d) == "function" then d("[CielMachinist] ACR.IsActive -> ok=" .. tostring(ok) .. " active=" .. tostring(active) .. " name=" .. tostring(name)) end
    end
    if not ok or active ~= true then return false end
    local label = type(name) == "table" and (name.name or name.alias) or name
    if label == nil and type(ACR.GetActiveProfile) == "function" then
        local okP, active = pcall(ACR.GetActiveProfile)
        if okP then label = type(active) == "table" and (active.name or active.alias) or active end
    end
    -- ACR.IsActive reports no name on current builds; the selected-profile
    -- table keyed by job is what other routines read.
    if label == nil and type(gACRSelectedProfiles) == "table" and Player then
        label = gACRSelectedProfiles[Player.job]
    end
    return tostring(label) == CielMachinistData.ACRProfileName
end
CielMachinist.drivenByACR = drivenByACR

local lastDecisionReport = ""
local function reportDecision()
    local decision = tostring(CielMachinistEngine.state.lastDecision)
    if decision ~= lastDecisionReport then
        lastDecisionReport = decision
        if type(d) == "function" then d("[CielMachinist] decision: " .. decision) end
    end
end

function CielMachinist.Update()
    if not CielMachinist.initialized then CielMachinist.Init() end
    if not drivenByACR() then CielMachinistEngine.OnUpdate() end
    reportDecision()
    flushIfDirty(false)
end

-- ACR profile ------------------------------------------------------------------------
-- A stub in LuaMods/ACR/CombatRoutines/CielMachinist.lua returns this table so the
-- profile shows up in the ACR dropdown. ACR's Enabled toggle is the master
-- switch in that mode; the window's "Execute rotation" applies to standalone use.

local acrProfile = nil

function CielMachinistACRProfile()
    acrProfileRequested = true
    if acrProfile then return acrProfile end
    local profile = {}
    profile.name = CielMachinistData.ACRProfileName
    profile.GUI = { open = false, visible = true, name = "Ciel Machinist" }
    profile.region = { 1, 2, 3 }
    profile.classes = { [CielMachinistData.MachinistJobID] = true }
    profile.tags = "assistonly;grindmode;dungeons"

    function profile.Cast()
        if not CielMachinist.initialized then CielMachinist.Init() end
        local cast = CielMachinistEngine.Step(true) == true
        reportDecision()
        return cast
    end

    function profile.Draw()
        if profile.GUI.open then
            CielMachinist.windowOpen = true
            CielMachinist.DrawWindow()
            profile.GUI.open = CielMachinist.windowOpen
        end
    end

    function profile.DrawHeader() end
    function profile.DrawFooter() end
    function profile.OnOpen() profile.GUI.open = true end
    function profile.OnLoad() if not CielMachinist.initialized then CielMachinist.Init() end end
    function profile.OnClick(mouse, shiftState, controlState, altState, entity) end
    function profile.OnUpdate(event, tickcount) flushIfDirty(false) end

    acrProfile = profile
    return profile
end

-- GUI helpers ----------------------------------------------------------------------------

local function checkbox(label, key)
    local config = settings()
    local value, changed = GUI:Checkbox(label, config[key])
    if changed then config[key] = value markDirty() end
end

local function customCheckbox(label, key)
    local config = settings()
    local value, changed = GUI:Checkbox(label, config[key])
    if changed then
        config[key] = value
        config.preset = "Custom"
        markDirty()
    end
end

local function abilityCheckbox(label, key)
    local config = settings()
    config.abilities = config.abilities or {}
    local value, changed = GUI:Checkbox("Auto: " .. label .. "##cielmach-" .. key, config.abilities[key] ~= false)
    if changed then
        config.abilities[key] = value
        config.preset = "Custom"
        markDirty()
    end
end

-- Settings a preset must never touch. Everything else in
-- CielMachinistData.Defaults is restored before the preset's overrides are
-- merged, so "Optimized" really is a complete reset:
--   enabled                 the master execution switch
--   showWindow              window visibility
--   lockToolNoticeDismissed a one-time notice the user already dismissed
--   settingsVersion         migration bookkeeping, never user-facing
--   *GaugeIndex             per-client gauge layout the user calibrated
--   advancedEnabled         the switch that exposes presets in the first place
local PRESET_PRESERVED = {
    enabled = true,
    showWindow = true,
    lockToolNoticeDismissed = true,
    settingsVersion = true,
    heatGaugeIndex = true,
    batteryGaugeIndex = true,
    advancedEnabled = true,
}
CielMachinist.PresetPreserved = PRESET_PRESERVED

local function applyPreset(name)
    local config = settings()
    for key, value in pairs(CielMachinistData.Defaults) do
        if not PRESET_PRESERVED[key] then config[key] = deepCopy(value) end
    end
    merge(config, CielMachinistData.Presets[name] or {})
    config.preset = name
    markDirty()
end
CielMachinist.ApplyPreset = applyPreset

local function presetButton(label, name)
    if GUI:Button(label, 118, 23) then applyPreset(name) end
end

local function executionButton(label, mode)
    local config = settings()
    local prefix = config.executionMode == mode and "[x] " or "[ ] "
    if GUI:Button(prefix .. label, 118, 23) then
        config.executionMode = mode
        config.preset = "Custom"
        markDirty()
    end
end

local function sliderInt(label, key, low, high)
    local config = settings()
    local current = tonumber(config[key]) or low
    local value = GUI:SliderInt(label, current, low, high)
    if value ~= nil and value ~= current then config[key] = value markDirty() end
end

local function sliderFloat(label, key, low, high)
    local config = settings()
    local current = tonumber(config[key]) or low
    local value = GUI:SliderFloat(label, current, low, high)
    if value ~= nil and math.abs(value - current) > 1e-6 then config[key] = value markDirty() end
end

local function aoeSlider(label, key)
    local config = settings()
    config.aoeTargets = config.aoeTargets or {}
    local current = tonumber(config.aoeTargets[key]) or tonumber(CielMachinistData.AoEDefaults[key]) or 2
    local value = GUI:SliderInt(label .. "##cielmach-aoe-" .. key, current, 1, 6)
    if value ~= nil and value ~= current then
        config.aoeTargets[key] = value
        config.preset = "Custom"
        markDirty()
    end
end

local LOCK_TOOL_TEXT = "CielMachinist works on its own, but weaving gets noticeably better with an animation-lock tool. " ..
    "XivAlexander (standalone, github.com/Soreepeong/XivAlexander) or NoClippy (Dalamud, github.com/UnknownX7/NoClippy) " ..
    "remove your ping from the client's animation lock so double weaves fit cleanly inside the GCD. Run only one of them. " ..
    "CielMachinist's polling is fast enough to use the shorter lock automatically; no setting needs changing."

local function drawLockToolNotice(config)
    if config.lockToolNoticeDismissed then return end
    GUI:TextWrapped("For even better results: install XivAlexander or NoClippy.")
    GUI:TextWrapped(LOCK_TOOL_TEXT)
    if GUI:Button("Got it##cielmach-locktool", 90, 22) then config.lockToolNoticeDismissed = true markDirty() end
    GUI:SameLine()
    GUI:Text("(details stay under 'Better weaving' below)")
    GUI:Separator()
end

-- Window ---------------------------------------------------------------------------------

local function chargeText(state)
    if not state or not state.info then return "?" end
    return tostring(state.charges) .. "/" .. tostring(state.max) ..
        (state.charges < state.max and string.format(" (+%.0fs)", state.remaining or 0) or "")
end

function CielMachinist.DrawWindow()
    local config = settings()
    local state = CielMachinistEngine.state
    GUI:SetNextWindowSize(420, 640, GUI.SetCond_FirstUseEver)
    local visible
    visible, CielMachinist.windowOpen = GUI:Begin("Ciel Machinist", CielMachinist.windowOpen)
    if config.showWindow ~= CielMachinist.windowOpen then config.showWindow = CielMachinist.windowOpen markDirty() end
    if visible then
        drawLockToolNotice(config)
        if drivenByACR() then
            GUI:TextWrapped("Driven by ACR: the ACR Enabled toggle starts and stops the rotation. Remove LuaMods/ACR/CombatRoutines/CielMachinist.lua to run standalone.")
        else
            checkbox("Execute rotation", "enabled")
        end
        GUI:SameLine()
        checkbox("Require combat", "requireCombat")
        checkbox("Use AoE replacements", "useAOE")
        if config.useAOE then
            aoeSlider("Scattergun targets", "Scattergun")
            aoeSlider("Bioblaster targets", "Bioblaster")
            aoeSlider("Auto Crossbow targets", "AutoCrossbow")
        end
        checkbox("Use Gemdraught of Dexterity", "usePotion")
        if config.usePotion then
            checkbox("Only with burst", "potionOnlyWithBurst")
            GUI:SameLine()
            checkbox("HQ only", "potionHQOnly")
            GUI:SameLine()
            checkbox("In pre-pull", "potionPrepull")
            GUI:Text("Potion found: " .. tostring(state.potionName or "None"))
        end

        checkbox("Pre-pull Reassemble", "prepull")
        if config.prepull and config.requireCombat then
            GUI:SameLine()
            if GUI:Button(CielMachinistEngine.PrepullArmed() and "Pre-pull armed##cielmach-prepull"
                    or "Pre-pull now##cielmach-prepull", 130, 22) then
                CielMachinistEngine.ArmPrepull(10)
            end
            GUI:TextWrapped("Target the enemy and press this about five seconds before the pull; Reassemble lasts five seconds.")
        end

        GUI:Separator()
        GUI:Text("Current decision: " .. tostring(state.lastDecision))
        GUI:Text("Last action: " .. tostring(state.lastActionName))
        GUI:Text("Heat: " .. tostring(state.heat or 0) .. "  Battery: " .. tostring(state.battery or 0) ..
            "  Overheated: " .. tostring(state.overheated == true))
        GUI:Text("Enemies near target: " .. tostring(state.enemyCount or 1) ..
            "  GCD remaining: " .. string.format("%.2f", state.gcdRemaining or 0) ..
            "  weaves: " .. tostring(state.weavesSinceGCD or 0))
        GUI:Text("Drill " .. chargeText(state.charges.Drill) ..
            "  Reassemble " .. chargeText(state.charges.Reassemble))
        GUI:Text("Double Check " .. chargeText(state.charges.DoubleCheck) ..
            "  Checkmate " .. chargeText(state.charges.Checkmate))

        local ttk = state.ttk
        GUI:Text("Estimated TTK: " .. (ttk and string.format("%.1fs", ttk) or "learning/unknown"))
        GUI:Text("TTK confidence: " .. string.format("%.0f%%", (state.ttkConfidence or 0) * 100))
        GUI:Text("Kill-time policy: " .. tostring(state.ttkBand or "LEARNING"))
        checkbox("Automatic TTK estimate", "autoTTK")
        if not config.autoTTK then sliderInt("Manual TTK seconds", "manualTTK", 1, 300) end

        if GUI:CollapsingHeader("Rotation tuning") then
            sliderFloat("No Hypercharge if a tool is due within (s)", "hyperchargeToolLeadSeconds", 5, 12)
            sliderInt("Keep Hypercharge for Wildfire within (s)", "hyperchargeHoldForBurstSeconds", 0, 30)
            sliderInt("Heat kept for a second burst Hypercharge (0 = off)", "hyperchargeBurstHeat", 0, 60)
            sliderInt("Wildfire minimum TTK", "wildfireMinimumTTK", 0, 20)
            GUI:Text("Wildfire placement")
            for _, mode in ipairs({ { "After Hypercharge", "AFTER" }, { "One weaponskill before", "BEFORE" } }) do
                local prefix = config.wildfirePlacement == mode[2] and "[x] " or "[ ] "
                if GUI:Button(prefix .. mode[1] .. "##cielmach-wf-" .. mode[2], 190, 23) then
                    config.wildfirePlacement = mode[2]
                    markDirty()
                end
                if mode[2] == "AFTER" then GUI:SameLine() end
            end
            sliderInt("Queen minimum battery off-cycle", "queenBatteryOffcycle", 50, 100)
            sliderInt("Queen minimum battery in burst", "queenBatteryBurst", 50, 100)
            sliderInt("Keep battery when burst within (s)", "queenRefillSeconds", 0, 90)
            sliderInt("Queen minimum TTK", "queenMinimumTTK", 0, 30)
            sliderInt("Pool Double Check / Checkmate when burst within (s)", "chargePoolSeconds", 0, 45)
            sliderInt("Reassemble charges kept for burst", "reassembleBurstCharges", 0, 2)
            sliderInt("Reassemble delay inside burst (s)", "reassembleBurstDelaySeconds", 0, 15)
            sliderFloat("Minimum TTK confidence", "minimumTTKConfidence", 0.2, 1.0)
            sliderInt("Terminal TTK", "terminalTTK", 10, 30)
            sliderInt("Maximum weaves per GCD", "maxWeaves", 1, 2)
            sliderFloat("Weave only if GCD remaining >= (s)", "weaveMinGcdRemaining", 0.3, 1.2)
            sliderInt("Potion minimum TTK", "potionMinimumTTK", 0, 30)
        end

        if GUI:CollapsingHeader("Advanced customization") then
            checkbox("Enable custom settings", "advancedEnabled")
            if not config.advancedEnabled then
                GUI:TextWrapped("Optimized defaults are active. Enable this only if you want presets, per-ability Auto/Off controls, utility rules, or partial execution modes.")
            else
                GUI:Text("Preset: " .. tostring(config.preset or "Custom"))
                presetButton("Optimized", "Optimized") GUI:SameLine()
                presetButton("Conservative", "Conservative") GUI:SameLine()
                presetButton("No Queen", "NoQueen")
                presetButton("Single target", "SingleTarget") GUI:SameLine()
                presetButton("GCD only", "GCDOnly")

                GUI:Separator()
                GUI:Text("Execution mode")
                executionButton("Full", "FULL") GUI:SameLine()
                executionButton("GCD only", "GCD_ONLY") GUI:SameLine()
                executionButton("oGCD only", "OGCD_ONLY")
                customCheckbox("Terminal resource dumping", "terminalDumping")
                customCheckbox("Pool resources for burst", "resourcePooling")
                customCheckbox("Require target line of sight", "requireLOS")

                if GUI:CollapsingHeader("Tools - Auto / Off") then
                    abilityCheckbox("Drill", "Drill")
                    abilityCheckbox("Air Anchor", "AirAnchor")
                    abilityCheckbox("Chain Saw", "ChainSaw")
                    abilityCheckbox("Excavator", "Excavator")
                    abilityCheckbox("Full Metal Field", "FullMetalField")
                    abilityCheckbox("Reassemble", "Reassemble")
                end
                if GUI:CollapsingHeader("Burst and Hypercharge - Auto / Off") then
                    abilityCheckbox("Barrel Stabilizer", "BarrelStabilizer")
                    abilityCheckbox("Wildfire", "Wildfire")
                    abilityCheckbox("Hypercharge", "Hypercharge")
                    abilityCheckbox("Blazing Shot", "BlazingShot")
                end
                if GUI:CollapsingHeader("Damage oGCDs and Queen - Auto / Off") then
                    abilityCheckbox("Double Check", "DoubleCheck")
                    abilityCheckbox("Checkmate", "Checkmate")
                    abilityCheckbox("Automaton Queen", "AutomatonQueen")
                    abilityCheckbox("Queen Overdrive before a kill", "QueenOverdrive")
                end
                if GUI:CollapsingHeader("AoE actions - Auto / Off") then
                    customCheckbox("Use AoE replacements", "useAOE")
                    abilityCheckbox("Scattergun", "Scattergun")
                    abilityCheckbox("Bioblaster", "Bioblaster")
                    abilityCheckbox("Auto Crossbow", "AutoCrossbow")
                end
                if GUI:CollapsingHeader("Utility - opt in") then
                    abilityCheckbox("Second Wind", "SecondWind")
                    sliderInt("Second Wind below HP%", "secondWindHP", 10, 90)
                    abilityCheckbox("Tactician", "Tactician")
                    sliderInt("Tactician below HP%", "tacticianHP", 10, 95)
                end
            end
        end

        local warnings = CielMachinistEngine.GetConfigurationWarnings()
        if #warnings > 0 then
            GUI:Separator()
            GUI:Text("Configuration warnings")
            for _, warning in ipairs(warnings) do GUI:TextWrapped("- " .. warning) end
        end

        if GUI:CollapsingHeader("Better weaving (optional tools)") then
            GUI:TextWrapped(LOCK_TOOL_TEXT)
            GUI:TextWrapped("Machinist weaves once inside every 1.5 s Overheated weaponskill, so it gains more from a shorter animation lock than most jobs. Both tools stay above the real server lock.")
            if config.lockToolNoticeDismissed and GUI:Button("Show startup notice again##cielmach-locktool2", 200, 22) then
                config.lockToolNoticeDismissed = false
                markDirty()
            end
        end

        if GUI:CollapsingHeader("Gauge diagnostics") then
            sliderInt("Heat gauge index", "heatGaugeIndex", 1, 8)
            sliderInt("Battery gauge index", "batteryGaugeIndex", 1, 8)
            GUI:Text("Selected Heat: " .. tostring(CielMachinistEngine.GetHeat()))
            GUI:Text("Selected Battery: " .. tostring(CielMachinistEngine.GetBattery()))
            if Player and Player.gauge then
                for index = 1, 8 do
                    GUI:Text("Gauge[" .. index .. "] = " .. tostring(Player.gauge[index]))
                end
            end
            GUI:Text("Combo: lastcomboid=" .. tostring(Player and Player.lastcomboid) ..
                "  remain=" .. tostring(Player and Player.combotimeremain) ..
                "  next step=" .. tostring(CielMachinistEngine.NextComboStep()))
            GUI:TextWrapped("Verify the index that climbs by 5 per combo weaponskill as Heat and the one that climbs by 10 on Heated Clean Shot as Battery, then set them above. Battery is treated as at least 50 whenever Automaton Queen is ready.")
            if GUI:Button("Rescan potion inventory", 170, 23) then
                CielMachinistEngine.RefreshPotion(true)
            end
        end

        if GUI:Button("Reset combat state", 170, 25) then
            CielMachinistEngine.ResetCombat("Manual reset")
        end
        GUI:SameLine()
        if not drivenByACR() and GUI:Button(config.enabled and "STOP" or "START", 100, 25) then
            config.enabled = not config.enabled
            markDirty()
        end
    end
    GUI:End()
end

function CielMachinist.Draw()
    if not CielMachinist.initialized then return end
    if drivenByACR() then return end -- ACR draws the window through the profile
    if not CielMachinist.windowOpen then return end
    CielMachinist.DrawWindow()
end

-- The module table itself is local so nothing can clobber it by accident.
-- This global is the read-only handle used by the offline test harnesses and
-- by anything that wants to drive the window or presets from outside.
CielMachinistUI = CielMachinist

RegisterEventHandler("Module.Initalize", CielMachinist.Init, "CielMachinist.Init")
RegisterEventHandler("Gameloop.Update", CielMachinist.Update, "CielMachinist.Update")
RegisterEventHandler("Gameloop.Draw", CielMachinist.Draw, "CielMachinist.Draw")
