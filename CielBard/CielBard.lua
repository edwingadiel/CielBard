local CielBard = {
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
-- flat primitive keys such as "abilities.ApexArrow".

local function store()
    if type(Settings) ~= "table" then return nil end
    local ok, section = pcall(function() return Settings.CielBard end)
    if not ok then return nil end
    if section == nil then
        local okSet = pcall(function() Settings.CielBard = {} end)
        if not okSet then return nil end
        ok, section = pcall(function() return Settings.CielBard end)
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
    local config = deepCopy(CielBardData.Defaults)
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
    if not CielBard.config then CielBard.config = loadConfig() end
    return CielBard.config
end

local function markDirty()
    CielBard.dirty = true
end

local function flushIfDirty(force)
    if not CielBard.dirty and not force then return end
    local ticks = (type(Now) == "function" and Now()) or 0
    if not force and ticks - CielBard.lastSaveAt < 1000 then return end
    CielBard.lastSaveAt = ticks
    if saveConfig(settings()) then CielBard.dirty = false end
end

-- Timing migration ---------------------------------------------------------------

local TIMING_VERSION = 4

-- One-time migrations for defaults that changed after users had saved them.
-- v2: pulse/throttle tightened in 0.4.1. v3: requireLOS became opt-in in 0.5.0
-- because live clients report los=false on dummies in plain view. v4: the
-- 0.5.1 review (High #3) found multi-dotting too aggressive to ship on by
-- default, so a saved multiDot=true from an earlier version is turned off
-- once; the toggle and the presets still work normally afterwards.
local function migrateTiming(config)
    local version = tonumber(config.timingVersion) or 1
    if version >= TIMING_VERSION then return end
    if version < 2 then
        config.pulseMs = CielBardData.Defaults.pulseMs
        config.requestThrottleMs = CielBardData.Defaults.requestThrottleMs
    end
    if version < 3 then
        config.requireLOS = CielBardData.Defaults.requireLOS
    end
    if version < 4 then
        config.multiDot = CielBardData.Defaults.multiDot
    end
    config.timingVersion = TIMING_VERSION
    markDirty()
end

-- Lifecycle ----------------------------------------------------------------------

function CielBard.Init()
    local config = settings()
    migrateTiming(config)
    CielBard.windowOpen = config.showWindow ~= false
    CielBardEngine.Init(config)
    CielBard.initialized = true
    flushIfDirty(true)
    if type(d) == "function" then
        d("[CielBard] Loaded v" .. CielBardData.Version)
        if not config.lockToolNoticeDismissed then
            d("[CielBard] Tip: for better weaving, run XivAlexander (standalone) or NoClippy (Dalamud) alongside the bot. See the notice in the Ciel Bard window.")
        end
    end
end

-- True when ACR is enabled with the CielBard profile selected. In that case
-- ACR's own Cast() callback drives the engine and the standalone loop stays out.
local lastACRReport = ""
local acrProfileRequested = false
local function drivenByACR()
    -- Once ACR has loaded the CielBard profile stub, ACR owns execution: the
    -- standalone loop never runs, even while ACR is disabled.
    if acrProfileRequested then return true end
    if type(ACR) ~= "table" or type(ACR.IsActive) ~= "function" then return false end
    local ok, active, name = pcall(ACR.IsActive)
    local report = tostring(ok) .. "/" .. tostring(active) .. "/" .. tostring(name)
    if report ~= lastACRReport then
        lastACRReport = report
        if type(d) == "function" then d("[CielBard] ACR.IsActive -> ok=" .. tostring(ok) .. " active=" .. tostring(active) .. " name=" .. tostring(name)) end
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
    return tostring(label) == CielBardData.ACRProfileName
end
CielBard.drivenByACR = drivenByACR

local lastDecisionReport = ""
local function reportDecision()
    local decision = tostring(CielBardEngine.state.lastDecision)
    if decision ~= lastDecisionReport then
        lastDecisionReport = decision
        if type(d) == "function" then d("[CielBard] decision: " .. decision) end
    end
end

function CielBard.Update()
    if not CielBard.initialized then CielBard.Init() end
    if not drivenByACR() then CielBardEngine.OnUpdate() end
    reportDecision()
    flushIfDirty(false)
end

-- ACR profile ------------------------------------------------------------------------
-- A stub in LuaMods/ACR/CombatRoutines/CielBard.lua returns this table so the
-- profile shows up in the ACR dropdown. ACR's Enabled toggle is the master
-- switch in that mode; the window's "Execute rotation" applies to standalone use.

local acrProfile = nil

function CielBardACRProfile()
    acrProfileRequested = true
    if acrProfile then return acrProfile end
    local profile = {}
    profile.name = CielBardData.ACRProfileName
    profile.GUI = { open = false, visible = true, name = "Ciel Bard" }
    profile.region = { 1, 2, 3 }
    profile.classes = { [CielBardData.BardJobID] = true }
    profile.tags = "assistonly;grindmode;dungeons"

    function profile.Cast()
        if not CielBard.initialized then CielBard.Init() end
        local cast = CielBardEngine.Step(true) == true
        reportDecision()
        return cast
    end

    function profile.Draw()
        if profile.GUI.open then
            CielBard.windowOpen = true
            CielBard.DrawWindow()
            profile.GUI.open = CielBard.windowOpen
        end
    end

    function profile.DrawHeader() end
    function profile.DrawFooter() end
    function profile.OnOpen() profile.GUI.open = true end
    function profile.OnLoad() if not CielBard.initialized then CielBard.Init() end end
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
    local value, changed = GUI:Checkbox("Auto: " .. label .. "##cielbard-" .. key, config.abilities[key] ~= false)
    if changed then
        config.abilities[key] = value
        config.preset = "Custom"
        markDirty()
    end
end

-- Settings a preset must never touch. Everything else in
-- CielBardData.Defaults is restored before the preset's overrides are merged,
-- so "Optimized" really is a complete reset (0.5.1 review, medium finding):
--   enabled                 the master execution switch
--   showWindow              window visibility
--   lockToolNoticeDismissed a one-time notice the user already dismissed
--   timingVersion           migration bookkeeping, never user-facing
--   *GaugeIndex             per-client gauge layout the user calibrated
--   advancedEnabled         the switch that exposes presets in the first place
local PRESET_PRESERVED = {
    enabled = true,
    showWindow = true,
    lockToolNoticeDismissed = true,
    timingVersion = true,
    soulVoiceGaugeIndex = true,
    repertoireGaugeIndex = true,
    songTimerGaugeIndex = true,
    advancedEnabled = true,
}
CielBard.PresetPreserved = PRESET_PRESERVED

local function applyPreset(name)
    local config = settings()
    for key, value in pairs(CielBardData.Defaults) do
        if not PRESET_PRESERVED[key] then config[key] = deepCopy(value) end
    end
    merge(config, CielBardData.Presets[name] or {})
    config.preset = name
    markDirty()
end
CielBard.ApplyPreset = applyPreset

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

local function burstGateButton(label, mode)
    local config = settings()
    local prefix = config.burstDotGate == mode and "[x] " or "[ ] "
    if GUI:Button(prefix .. label .. "##cielbard-gate-" .. mode, 118, 23) then
        config.burstDotGate = mode
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
    local current = tonumber(config.aoeTargets[key]) or tonumber(CielBardData.AoEDefaults[key]) or 2
    local value = GUI:SliderInt(label .. "##cielbard-aoe-" .. key, current, 1, 6)
    if value ~= nil and value ~= current then
        config.aoeTargets[key] = value
        config.preset = "Custom"
        markDirty()
    end
end

local LOCK_TOOL_TEXT = "CielBard works on its own, but weaving gets noticeably better with an animation-lock tool. " ..
    "XivAlexander (standalone, github.com/Soreepeong/XivAlexander) or NoClippy (Dalamud, github.com/UnknownX7/NoClippy) " ..
    "remove your ping from the client's animation lock so double weaves fit cleanly inside the GCD. Run only one of them. " ..
    "CielBard's polling is fast enough to use the shorter lock automatically; no setting needs changing."

local function drawLockToolNotice(config)
    if config.lockToolNoticeDismissed then return end
    GUI:TextWrapped("For even better results: install XivAlexander or NoClippy.")
    GUI:TextWrapped(LOCK_TOOL_TEXT)
    if GUI:Button("Got it##cielbard-locktool", 90, 22) then config.lockToolNoticeDismissed = true markDirty() end
    GUI:SameLine()
    GUI:Text("(details stay under 'Better weaving' below)")
    GUI:Separator()
end

-- Window ---------------------------------------------------------------------------------

function CielBard.DrawWindow()
    local config = settings()
    GUI:SetNextWindowSize(420, 640, GUI.SetCond_FirstUseEver)
    local visible
    visible, CielBard.windowOpen = GUI:Begin("Ciel Bard", CielBard.windowOpen)
    if config.showWindow ~= CielBard.windowOpen then config.showWindow = CielBard.windowOpen markDirty() end
    if visible then
        drawLockToolNotice(config)
        if drivenByACR() then
            GUI:TextWrapped("Driven by ACR: the ACR Enabled toggle starts and stops the rotation. Remove LuaMods/ACR/CombatRoutines/CielBard.lua to run standalone.")
        else
            checkbox("Execute rotation", "enabled")
        end
        GUI:SameLine()
        checkbox("Require combat", "requireCombat")
        checkbox("Use AoE replacements", "useAOE")
        if config.useAOE then
            aoeSlider("Ladonsbite targets", "Ladonsbite")
            aoeSlider("Shadowbite targets", "Shadowbite")
            aoeSlider("Shadowbite targets while Barrage is up", "ShadowbiteBarrage")
            aoeSlider("Rain of Death targets", "RainOfDeath")
        end
        checkbox("Multi-dot nearby enemies", "multiDot")
        if config.multiDot then
            sliderInt("Multi-dot max extra targets", "multiDotMaxTargets", 1, 6)
            sliderInt("Multi-dot minimum target HP%", "multiDotMinHPPercent", 0, 90)
        end
        checkbox("Use Gemdraught of Dexterity", "usePotion")
        if config.usePotion then
            checkbox("Only with burst", "potionOnlyWithBurst")
            GUI:SameLine()
            checkbox("HQ only", "potionHQOnly")
            GUI:Text("Potion found: " .. tostring(CielBardEngine.state.potionName or "None"))
        end

        GUI:Separator()
        GUI:Text("Current decision: " .. tostring(CielBardEngine.state.lastDecision))
        GUI:Text("Last action: " .. tostring(CielBardEngine.state.lastActionName))
        GUI:Text("Song: " .. tostring(CielBardEngine.state.currentSong) ..
            "  remaining: " .. string.format("%.1f", CielBardEngine.state.songRemaining or 0) ..
            "  codas: " .. tostring(CielBardEngine.CodaCount()))
        GUI:Text("Enemies near target: " .. tostring(CielBardEngine.state.enemyCount or 1) ..
            "  GCD remaining: " .. string.format("%.2f", CielBardEngine.state.gcdRemaining or 0) ..
            "  weaves: " .. tostring(CielBardEngine.state.weavesSinceGCD or 0))
        GUI:Text("Heartbreak charges: " .. tostring(CielBardEngine.state.charges or "?") ..
            "  next in: " .. string.format("%.1fs", CielBardEngine.state.chargeRemaining or 0))
        if config.multiDot then
            GUI:Text("Multi-dot target: " .. tostring(CielBardEngine.state.multiDotTargetName or "None"))
        end

        local ttk = CielBardEngine.state.ttk
        GUI:Text("Estimated TTK: " .. (ttk and string.format("%.1fs", ttk) or "learning/unknown"))
        GUI:Text("TTK confidence: " .. string.format("%.0f%%", (CielBardEngine.state.ttkConfidence or 0) * 100))
        GUI:Text("Kill-time policy: " .. tostring(CielBardEngine.state.ttkBand or "LEARNING"))
        checkbox("Automatic TTK estimate", "autoTTK")
        if not config.autoTTK then sliderInt("Manual TTK seconds", "manualTTK", 1, 300) end

        if GUI:CollapsingHeader("Rotation tuning") then
            sliderFloat("WM remaining at swap", "wmSwapRemaining", 0.2, 5)
            sliderFloat("MB remaining at swap", "mbSwapRemaining", 0.2, 6)
            sliderFloat("AP remaining at swap", "apSwapRemaining", 5, 15)
            sliderFloat("DoT refresh seconds", "dotRefreshSeconds", 1, 6)
            sliderInt("Minimum TTK for DoTs", "dotMinimumTTK", 8, 30)
            sliderFloat("Minimum TTK confidence", "minimumTTKConfidence", 0.2, 1.0)
            sliderInt("Terminal TTK", "terminalTTK", 10, 30)
            sliderInt("Apex gauge in burst", "apexBurstGauge", 20, 100)
            sliderInt("Apex gauge off-cycle", "apexOffcycleGauge", 20, 100)
            sliderInt("Maximum weaves per GCD", "maxWeaves", 1, 2)
            sliderFloat("Weave only if GCD remaining >= (s)", "weaveMinGcdRemaining", 0.3, 1.2)
            sliderInt("Pool Heartbreak charges when burst within (s)", "chargePoolSeconds", 0, 45)
            GUI:Text("Burst waits for DoTs")
            burstGateButton("None", "NONE") GUI:SameLine()
            burstGateButton("At least one", "ONE") GUI:SameLine()
            burstGateButton("Both", "BOTH")
            sliderInt("Radiant Finale minimum codas", "radiantFinaleMinCodas", 1, 3)
            sliderFloat("Let an imminent song add a coda (s)", "radiantFinaleCodaHold", 0, 5)
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
                presetButton("No DoTs", "NoDots") GUI:SameLine()
                presetButton("Single target", "SingleTarget") GUI:SameLine()
                presetButton("GCD only", "GCDOnly")

                GUI:Separator()
                GUI:Text("Execution mode")
                executionButton("Full", "FULL") GUI:SameLine()
                executionButton("GCD only", "GCD_ONLY") GUI:SameLine()
                executionButton("oGCD only", "OGCD_ONLY")
                customCheckbox("Automatic song cycle", "automaticSongCycle")
                customCheckbox("Terminal resource dumping", "terminalDumping")
                customCheckbox("Pool resources for burst", "resourcePooling")
                customCheckbox("Require target line of sight", "requireLOS")

                if GUI:CollapsingHeader("Songs - Auto / Off") then
                    abilityCheckbox("The Wanderer's Minuet", "WanderersMinuet")
                    abilityCheckbox("Mage's Ballad", "MagesBallad")
                    abilityCheckbox("Army's Paeon", "ArmysPaeon")
                end
                if GUI:CollapsingHeader("DoTs - Auto / Off") then
                    abilityCheckbox("Stormbite", "Stormbite")
                    abilityCheckbox("Caustic Bite", "CausticBite")
                    abilityCheckbox("Iron Jaws", "IronJaws")
                    customCheckbox("Late-buff Iron Jaws snapshot", "snapshotIronJaws")
                    customCheckbox("Multi-dot nearby enemies", "multiDot")
                end
                if GUI:CollapsingHeader("Burst buffs - Auto / Off") then
                    abilityCheckbox("Raging Strikes", "RagingStrikes")
                    abilityCheckbox("Battle Voice", "BattleVoice")
                    abilityCheckbox("Radiant Finale", "RadiantFinale")
                    abilityCheckbox("Barrage", "Barrage")
                end
                if GUI:CollapsingHeader("Gauge and procs - Auto / Off") then
                    abilityCheckbox("Refulgent Arrow", "RefulgentArrow")
                    abilityCheckbox("Apex Arrow", "ApexArrow")
                    abilityCheckbox("Blast Arrow", "BlastArrow")
                    abilityCheckbox("Pitch Perfect", "PitchPerfect")
                    abilityCheckbox("Resonant Arrow", "ResonantArrow")
                    abilityCheckbox("Radiant Encore", "RadiantEncore")
                end
                if GUI:CollapsingHeader("Damage oGCDs - Auto / Off") then
                    abilityCheckbox("Empyreal Arrow", "EmpyrealArrow")
                    abilityCheckbox("Sidewinder", "Sidewinder")
                    abilityCheckbox("Heartbreak Shot", "HeartbreakShot")
                    abilityCheckbox("Bloodletter fallback", "Bloodletter")
                    abilityCheckbox("Rain of Death", "RainOfDeath")
                end
                if GUI:CollapsingHeader("AoE actions - Auto / Off") then
                    customCheckbox("Use AoE replacements", "useAOE")
                    abilityCheckbox("Ladonsbite", "Ladonsbite")
                    abilityCheckbox("Shadowbite", "Shadowbite")
                end
                if GUI:CollapsingHeader("Utility - opt in") then
                    abilityCheckbox("Second Wind", "SecondWind")
                    sliderInt("Second Wind below HP%", "secondWindHP", 10, 90)
                    abilityCheckbox("Nature's Minne on self", "NaturesMinne")
                    sliderInt("Nature's Minne below HP%", "minneHP", 10, 95)
                    abilityCheckbox("Troubadour", "Troubadour")
                    sliderInt("Troubadour below HP%", "troubadourHP", 10, 95)
                    abilityCheckbox("Warden's Paean for dispellable debuff", "WardensPaean")
                end
            end
        end

        local warnings = CielBardEngine.GetConfigurationWarnings()
        if #warnings > 0 then
            GUI:Separator()
            GUI:Text("Configuration warnings")
            for _, warning in ipairs(warnings) do GUI:TextWrapped("- " .. warning) end
        end

        if GUI:CollapsingHeader("Better weaving (optional tools)") then
            GUI:TextWrapped(LOCK_TOOL_TEXT)
            GUI:TextWrapped("Measured on a striking dummy, oGCD-to-oGCD gaps drop by roughly your round-trip time. Both tools stay above the real server lock.")
            if config.lockToolNoticeDismissed and GUI:Button("Show startup notice again##cielbard-locktool2", 200, 22) then
                config.lockToolNoticeDismissed = false
                markDirty()
            end
        end

        if GUI:CollapsingHeader("Gauge diagnostics") then
            sliderInt("Soul Voice gauge index", "soulVoiceGaugeIndex", 1, 8)
            sliderInt("Repertoire gauge index", "repertoireGaugeIndex", 1, 8)
            sliderInt("Song timer gauge index", "songTimerGaugeIndex", 1, 8)
            GUI:Text("Selected Soul Voice: " .. tostring(CielBardEngine.GetSoulVoice()))
            GUI:Text("Selected Repertoire: " .. tostring(CielBardEngine.GetRepertoire()))
            GUI:Text("Tracked codas: " .. tostring(CielBardEngine.CodaCount()) ..
                "  (WM=" .. tostring(CielBardEngine.state.codas.WM) ..
                " MB=" .. tostring(CielBardEngine.state.codas.MB) ..
                " AP=" .. tostring(CielBardEngine.state.codas.AP) .. ")")
            if Player and Player.gauge then
                for index = 1, 8 do
                    GUI:Text("Gauge[" .. index .. "] = " .. tostring(Player.gauge[index]))
                end
            end
            GUI:TextWrapped("Verify the index that moves from 0 to 100 as Soul Voice and the 0-3 index as Repertoire, then set them above. Codas are tracked locally from observed song casts and clear on Radiant Finale.")
            if GUI:Button("Rescan potion inventory", 170, 23) then
                CielBardEngine.RefreshPotion(true)
            end
        end

        if GUI:Button("Reset combat state", 170, 25) then
            CielBardEngine.ResetCombat("Manual reset")
        end
        GUI:SameLine()
        if not drivenByACR() and GUI:Button(config.enabled and "STOP" or "START", 100, 25) then
            config.enabled = not config.enabled
            markDirty()
        end
    end
    GUI:End()
end

function CielBard.Draw()
    if not CielBard.initialized then return end
    if drivenByACR() then return end -- ACR draws the window through the profile
    if not CielBard.windowOpen then return end
    CielBard.DrawWindow()
end

-- The module table itself is local so nothing can clobber it by accident.
-- This global is the read-only handle used by the offline test harnesses and
-- by anything that wants to drive the window or presets from outside.
CielBardUI = CielBard

RegisterEventHandler("Module.Initalize", CielBard.Init, "CielBard.Init")
RegisterEventHandler("Gameloop.Update", CielBard.Update, "CielBard.Update")
RegisterEventHandler("Gameloop.Draw", CielBard.Draw, "CielBard.Draw")
