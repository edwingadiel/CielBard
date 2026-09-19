local CielDancer = {
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
-- flat primitive keys such as "abilities.TechnicalStep".

local function store()
    if type(Settings) ~= "table" then return nil end
    local ok, section = pcall(function() return Settings.CielDancer end)
    if not ok then return nil end
    if section == nil then
        local okSet = pcall(function() Settings.CielDancer = {} end)
        if not okSet then return nil end
        ok, section = pcall(function() return Settings.CielDancer end)
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
    local config = deepCopy(CielDancerData.Defaults)
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
    if not CielDancer.config then CielDancer.config = loadConfig() end
    return CielDancer.config
end

local function markDirty()
    CielDancer.dirty = true
end

local function flushIfDirty(force)
    if not CielDancer.dirty and not force then return end
    local ticks = (type(Now) == "function" and Now()) or 0
    if not force and ticks - CielDancer.lastSaveAt < 1000 then return end
    CielDancer.lastSaveAt = ticks
    if saveConfig(settings()) then CielDancer.dirty = false end
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

function CielDancer.Init()
    local config = settings()
    migrateSettings(config)
    CielDancer.windowOpen = config.showWindow ~= false
    CielDancerEngine.Init(config)
    CielDancer.initialized = true
    flushIfDirty(true)
    if type(d) == "function" then
        d("[CielDancer] Loaded v" .. CielDancerData.Version)
        if not config.lockToolNoticeDismissed then
            d("[CielDancer] Tip: for better weaving, run XivAlexander (standalone) or NoClippy (Dalamud) alongside the bot. See the notice in the Ciel Dancer window.")
        end
    end
end

-- True when ACR is enabled with the CielDancer profile selected. In that case
-- ACR's own Cast() callback drives the engine and the standalone loop stays out.
local lastACRReport = ""
local acrProfileRequested = false
local function drivenByACR()
    -- Once ACR has loaded the CielDancer profile stub, ACR owns execution: the
    -- standalone loop never runs, even while ACR is disabled.
    if acrProfileRequested then return true end
    if type(ACR) ~= "table" or type(ACR.IsActive) ~= "function" then return false end
    local ok, active, name = pcall(ACR.IsActive)
    local report = tostring(ok) .. "/" .. tostring(active) .. "/" .. tostring(name)
    if report ~= lastACRReport then
        lastACRReport = report
        if type(d) == "function" then d("[CielDancer] ACR.IsActive -> ok=" .. tostring(ok) .. " active=" .. tostring(active) .. " name=" .. tostring(name)) end
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
    return tostring(label) == CielDancerData.ACRProfileName
end
CielDancer.drivenByACR = drivenByACR

local lastDecisionReport = ""
local function reportDecision()
    local decision = tostring(CielDancerEngine.state.lastDecision)
    if decision ~= lastDecisionReport then
        lastDecisionReport = decision
        if type(d) == "function" then d("[CielDancer] decision: " .. decision) end
    end
end

function CielDancer.Update()
    if not CielDancer.initialized then CielDancer.Init() end
    if not drivenByACR() then CielDancerEngine.OnUpdate() end
    reportDecision()
    flushIfDirty(false)
end

-- ACR profile ------------------------------------------------------------------------
-- A stub in LuaMods/ACR/CombatRoutines/CielDancer.lua returns this table so the
-- profile shows up in the ACR dropdown. ACR's Enabled toggle is the master
-- switch in that mode; the window's "Execute rotation" applies to standalone use.

local acrProfile = nil

function CielDancerACRProfile()
    acrProfileRequested = true
    if acrProfile then return acrProfile end
    local profile = {}
    profile.name = CielDancerData.ACRProfileName
    profile.GUI = { open = false, visible = true, name = "Ciel Dancer" }
    profile.region = { 1, 2, 3 }
    profile.classes = { [CielDancerData.DancerJobID] = true }
    profile.tags = "assistonly;grindmode;dungeons"

    function profile.Cast()
        if not CielDancer.initialized then CielDancer.Init() end
        local cast = CielDancerEngine.Step(true) == true
        reportDecision()
        return cast
    end

    function profile.Draw()
        if profile.GUI.open then
            CielDancer.windowOpen = true
            CielDancer.DrawWindow()
            profile.GUI.open = CielDancer.windowOpen
        end
    end

    function profile.DrawHeader() end
    function profile.DrawFooter() end
    function profile.OnOpen() profile.GUI.open = true end
    function profile.OnLoad() if not CielDancer.initialized then CielDancer.Init() end end
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
    local value, changed = GUI:Checkbox("Auto: " .. label .. "##cieldnc-" .. key, config.abilities[key] ~= false)
    if changed then
        config.abilities[key] = value
        config.preset = "Custom"
        markDirty()
    end
end

-- Settings a preset must never touch. Everything else in
-- CielDancerData.Defaults is restored before the preset's overrides are
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
    featherGaugeIndex = true,
    espritGaugeIndex = true,
    stepGaugeIndex = true,
    stepsDoneGaugeIndex = true,
    advancedEnabled = true,
}
CielDancer.PresetPreserved = PRESET_PRESERVED

local function applyPreset(name)
    local config = settings()
    for key, value in pairs(CielDancerData.Defaults) do
        if not PRESET_PRESERVED[key] then config[key] = deepCopy(value) end
    end
    merge(config, CielDancerData.Presets[name] or {})
    config.preset = name
    markDirty()
end
CielDancer.ApplyPreset = applyPreset

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
    local current = tonumber(config.aoeTargets[key]) or tonumber(CielDancerData.AoEDefaults[key]) or 2
    local value = GUI:SliderInt(label .. "##cieldnc-aoe-" .. key, current, 1, 6)
    if value ~= nil and value ~= current then
        config.aoeTargets[key] = value
        config.preset = "Custom"
        markDirty()
    end
end

local LOCK_TOOL_TEXT = "CielDancer works on its own, but weaving gets noticeably better with an animation-lock tool. " ..
    "XivAlexander (standalone, github.com/Soreepeong/XivAlexander) or NoClippy (Dalamud, github.com/UnknownX7/NoClippy) " ..
    "remove your ping from the client's animation lock so double weaves fit cleanly inside the GCD. Run only one of them. " ..
    "CielDancer's polling is fast enough to use the shorter lock automatically; no setting needs changing."

local function drawLockToolNotice(config)
    if config.lockToolNoticeDismissed then return end
    GUI:TextWrapped("For even better results: install XivAlexander or NoClippy.")
    GUI:TextWrapped(LOCK_TOOL_TEXT)
    if GUI:Button("Got it##cieldnc-locktool", 90, 22) then config.lockToolNoticeDismissed = true markDirty() end
    GUI:SameLine()
    GUI:Text("(details stay under 'Better weaving' below)")
    GUI:Separator()
end

-- Window ---------------------------------------------------------------------------------

function CielDancer.DrawWindow()
    local config = settings()
    local state = CielDancerEngine.state
    GUI:SetNextWindowSize(420, 640, GUI.SetCond_FirstUseEver)
    local visible
    visible, CielDancer.windowOpen = GUI:Begin("Ciel Dancer", CielDancer.windowOpen)
    if config.showWindow ~= CielDancer.windowOpen then config.showWindow = CielDancer.windowOpen markDirty() end
    if visible then
        drawLockToolNotice(config)
        if drivenByACR() then
            GUI:TextWrapped("Driven by ACR: the ACR Enabled toggle starts and stops the rotation. Remove LuaMods/ACR/CombatRoutines/CielDancer.lua to run standalone.")
        else
            checkbox("Execute rotation", "enabled")
        end
        GUI:SameLine()
        checkbox("Require combat", "requireCombat")
        checkbox("Use AoE replacements", "useAOE")
        if config.useAOE then
            aoeSlider("Windmill targets", "Windmill")
            aoeSlider("Bladeshower targets", "Bladeshower")
            aoeSlider("Rising Windmill targets", "RisingWindmill")
            aoeSlider("Bloodshower targets", "Bloodshower")
            aoeSlider("Fan Dance II targets", "FanDanceII")
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
        checkbox("Pre-pull Standard Step", "prepull")
        if config.prepull and config.requireCombat then
            GUI:SameLine()
            if GUI:Button(CielDancerEngine.PrepullArmed() and "Pre-pull armed##cieldnc-prepull"
                    or "Pre-pull now##cieldnc-prepull", 130, 22) then
                CielDancerEngine.ArmPrepull(14)
            end
            GUI:TextWrapped("Press this about fifteen seconds before the pull: the engine dances both steps and holds Standard Finish until combat starts. It never pulls for you, and the dance lapses after fifteen seconds.")
        end

        GUI:Separator()
        GUI:Text("Current decision: " .. tostring(state.lastDecision))
        GUI:Text("Last action: " .. tostring(state.lastActionName))
        GUI:Text("Esprit: " .. tostring(state.esprit or 0) .. "  Feathers: " .. tostring(state.feathers or 0) ..
            "  Dancing: " .. tostring(state.dancing or "no") ..
            "  Burst: " .. string.format("%.1fs", state.burstRemaining or 0))
        GUI:Text("Enemies within 5y: " .. tostring(state.enemyCount or 1) ..
            "  GCD remaining: " .. string.format("%.2f", state.gcdRemaining or 0) ..
            "  weaves: " .. tostring(state.weavesSinceGCD or 0))

        local ttk = state.ttk
        GUI:Text("Estimated TTK: " .. (ttk and string.format("%.1fs", ttk) or "learning/unknown"))
        GUI:Text("TTK confidence: " .. string.format("%.0f%%", (state.ttkConfidence or 0) * 100))
        GUI:Text("Kill-time policy: " .. tostring(state.ttkBand or "LEARNING"))
        checkbox("Automatic TTK estimate", "autoTTK")
        if not config.autoTTK then sliderInt("Manual TTK seconds", "manualTTK", 1, 300) end

        if GUI:CollapsingHeader("Rotation tuning") then
            sliderInt("Saber Dance at once from Esprit", "saberOvercapEsprit", 50, 100)
            sliderInt("Saber Dance outside burst from Esprit", "saberOffcycleEsprit", 50, 100)
            sliderInt("Tillana waits for Esprit at or below", "tillanaMaxEsprit", 0, 50)
            sliderInt("Fan Dance outside burst from feathers", "featherOffcycleCount", 1, 4)
            sliderInt("Keep Flourish when burst within (s)", "flourishHoldSeconds", 0, 30)
            sliderInt("Keep Fan Dance IV when burst within (s)", "fanDanceIVHoldSeconds", 0, 30)
            sliderFloat("No Standard Step when Technical within (s)", "standardBeforeTechnicalSeconds", 0, 10)
            sliderInt("Technical Step minimum TTK", "technicalMinimumTTK", 0, 40)
            sliderInt("Standard Step minimum TTK", "standardMinimumTTK", 0, 30)
            sliderInt("Press a proc first when this close to lapsing (s)", "procUrgentSeconds", 2, 10)
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
                presetButton("No party buffs", "NoPartyBuffs")
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
                customCheckbox("Warn when there is no dance partner", "warnNoPartner")

                if GUI:CollapsingHeader("Dances - Auto / Off") then
                    abilityCheckbox("Standard Step", "StandardStep")
                    abilityCheckbox("Technical Step", "TechnicalStep")
                    abilityCheckbox("Finishing Move", "FinishingMove")
                    abilityCheckbox("Last Dance", "LastDance")
                    abilityCheckbox("Tillana", "Tillana")
                end
                if GUI:CollapsingHeader("Burst and Esprit - Auto / Off") then
                    abilityCheckbox("Devilment", "Devilment")
                    abilityCheckbox("Starfall Dance", "StarfallDance")
                    abilityCheckbox("Saber Dance", "SaberDance")
                    abilityCheckbox("Dance of the Dawn", "DanceOfTheDawn")
                end
                if GUI:CollapsingHeader("Procs and feathers - Auto / Off") then
                    abilityCheckbox("Fountain", "Fountain")
                    abilityCheckbox("Reverse Cascade", "ReverseCascade")
                    abilityCheckbox("Fountainfall", "Fountainfall")
                    abilityCheckbox("Flourish", "Flourish")
                    abilityCheckbox("Fan Dance", "FanDance")
                    abilityCheckbox("Fan Dance III", "FanDanceIII")
                    abilityCheckbox("Fan Dance IV", "FanDanceIV")
                end
                if GUI:CollapsingHeader("AoE actions - Auto / Off") then
                    customCheckbox("Use AoE replacements", "useAOE")
                    abilityCheckbox("Windmill", "Windmill")
                    abilityCheckbox("Bladeshower", "Bladeshower")
                    abilityCheckbox("Rising Windmill", "RisingWindmill")
                    abilityCheckbox("Bloodshower", "Bloodshower")
                    abilityCheckbox("Fan Dance II", "FanDanceII")
                end
                if GUI:CollapsingHeader("Utility - opt in") then
                    abilityCheckbox("Second Wind", "SecondWind")
                    sliderInt("Second Wind below HP%", "secondWindHP", 10, 90)
                    abilityCheckbox("Curing Waltz", "CuringWaltz")
                    sliderInt("Curing Waltz below HP%", "curingWaltzHP", 10, 95)
                    abilityCheckbox("Shield Samba", "ShieldSamba")
                    sliderInt("Shield Samba below HP%", "shieldSambaHP", 10, 95)
                end
            end
        end

        local warnings = CielDancerEngine.GetConfigurationWarnings()
        if #warnings > 0 then
            GUI:Separator()
            GUI:Text("Configuration warnings")
            for _, warning in ipairs(warnings) do GUI:TextWrapped("- " .. warning) end
        end

        if GUI:CollapsingHeader("Better weaving (optional tools)") then
            GUI:TextWrapped(LOCK_TOOL_TEXT)
            if config.lockToolNoticeDismissed and GUI:Button("Show startup notice again##cieldnc-locktool2", 200, 22) then
                config.lockToolNoticeDismissed = false
                markDirty()
            end
        end

        if GUI:CollapsingHeader("Gauge diagnostics") then
            sliderInt("Feather gauge index", "featherGaugeIndex", 1, 10)
            sliderInt("Esprit gauge index", "espritGaugeIndex", 1, 10)
            sliderInt("First step gauge index", "stepGaugeIndex", 1, 10)
            sliderInt("Steps-done gauge index", "stepsDoneGaugeIndex", 1, 10)
            if Player and Player.gauge then
                for index = 1, 10 do
                    GUI:Text("Gauge[" .. index .. "] = " .. tostring(Player.gauge[index]))
                end
            end
            local dancing = CielDancerEngine.Dancing()
            if dancing then
                local _, stepName, completed, needed = CielDancerEngine.NextStep(dancing)
                GUI:Text("Dancing " .. dancing .. ": " .. tostring(completed) .. "/" .. tostring(needed) ..
                    "  next step: " .. tostring(stepName or "finish"))
            end
            GUI:Text("Combo: lastcomboid=" .. tostring(Player and Player.lastcomboid) ..
                "  remain=" .. tostring(Player and Player.combotimeremain) ..
                "  next step=" .. tostring(CielDancerEngine.NextComboStep()))
            GUI:TextWrapped("Feathers count 0-4 and Esprit 0-100. While dancing, four slots show the step sequence (1 Emboite, 2 Entrechat, 3 Jete, 4 Pirouette) and one counts the steps done. Press Standard Step by hand once and check that the indexes above match before enabling execution.")
            if GUI:Button("Rescan potion inventory", 170, 23) then
                CielDancerEngine.RefreshPotion(true)
            end
        end

        if GUI:Button("Reset combat state", 170, 25) then
            CielDancerEngine.ResetCombat("Manual reset")
        end
        GUI:SameLine()
        if not drivenByACR() and GUI:Button(config.enabled and "STOP" or "START", 100, 25) then
            config.enabled = not config.enabled
            markDirty()
        end
    end
    GUI:End()
end

function CielDancer.Draw()
    if not CielDancer.initialized then return end
    if drivenByACR() then return end -- ACR draws the window through the profile
    if not CielDancer.windowOpen then return end
    CielDancer.DrawWindow()
end

-- The module table itself is local so nothing can clobber it by accident.
-- This global is the read-only handle used by the offline test harnesses and
-- by anything that wants to drive the window or presets from outside.
CielDancerUI = CielDancer

RegisterEventHandler("Module.Initalize", CielDancer.Init, "CielDancer.Init")
RegisterEventHandler("Gameloop.Update", CielDancer.Update, "CielDancer.Update")
RegisterEventHandler("Gameloop.Draw", CielDancer.Draw, "CielDancer.Draw")
