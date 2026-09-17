local CielBard = {
    windowOpen = true,
    initialized = false,
}

local function deepCopy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, child in pairs(value) do result[key] = deepCopy(child) end
    return result
end

local function copyDefaults(destination, defaults)
    for key, value in pairs(defaults) do
        if destination[key] == nil then
            destination[key] = deepCopy(value)
        elseif type(value) == "table" and type(destination[key]) == "table" then
            copyDefaults(destination[key], value)
        end
    end
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

local function settings()
    Settings = Settings or {}
    Settings.CielBard = Settings.CielBard or {}
    copyDefaults(Settings.CielBard, CielBardData.Defaults)
    return Settings.CielBard
end

function CielBard.Init()
    local config = settings()
    CielBard.windowOpen = config.showWindow ~= false
    CielBardEngine.Init(config)
    CielBard.initialized = true
    if type(d) == "function" then d("[CielBard] Loaded v" .. CielBardData.Version) end
end

function CielBard.Update()
    if not CielBard.initialized then CielBard.Init() end
    CielBardEngine.OnUpdate()
end

local function checkbox(label, key)
    local config = settings()
    local value, changed = GUI:Checkbox(label, config[key])
    if changed then config[key] = value end
end

local function customCheckbox(label, key)
    local config = settings()
    local value, changed = GUI:Checkbox(label, config[key])
    if changed then
        config[key] = value
        config.preset = "Custom"
    end
end

local function abilityCheckbox(label, key)
    local config = settings()
    config.abilities = config.abilities or {}
    local value, changed = GUI:Checkbox("Auto: " .. label .. "##cielbard-" .. key, config.abilities[key] ~= false)
    if changed then
        config.abilities[key] = value
        config.preset = "Custom"
    end
end

local function applyPreset(name)
    local config = settings()
    config.abilities = deepCopy(CielBardData.AbilityDefaults)
    config.useAOE = CielBardData.Defaults.useAOE
    config.maxWeaves = CielBardData.Defaults.maxWeaves
    config.executionMode = CielBardData.Defaults.executionMode
    config.snapshotIronJaws = CielBardData.Defaults.snapshotIronJaws
    config.terminalDumping = CielBardData.Defaults.terminalDumping
    config.resourcePooling = CielBardData.Defaults.resourcePooling
    config.automaticSongCycle = CielBardData.Defaults.automaticSongCycle
    merge(config, CielBardData.Presets[name] or {})
    config.preset = name
end

local function presetButton(label, name)
    if GUI:Button(label, 118, 23) then applyPreset(name) end
end

local function executionButton(label, mode)
    local config = settings()
    local prefix = config.executionMode == mode and "[x] " or "[ ] "
    if GUI:Button(prefix .. label, 118, 23) then
        config.executionMode = mode
        config.preset = "Custom"
    end
end

local function sliderInt(label, key, low, high)
    local config = settings()
    local value = GUI:SliderInt(label, tonumber(config[key]) or low, low, high)
    if value ~= nil then config[key] = value end
end

local function sliderFloat(label, key, low, high)
    local config = settings()
    local value = GUI:SliderFloat(label, tonumber(config[key]) or low, low, high)
    if value ~= nil then config[key] = value end
end

function CielBard.Draw()
    if not CielBard.initialized then return end
    local config = settings()
    if not CielBard.windowOpen then return end

    GUI:SetNextWindowSize(420, 560, GUI.SetCond_FirstUseEver)
    local visible
    visible, CielBard.windowOpen = GUI:Begin("Ciel Bard", CielBard.windowOpen)
    config.showWindow = CielBard.windowOpen
    if visible then
        checkbox("Execute rotation", "enabled")
        GUI:SameLine()
        checkbox("Require combat", "requireCombat")
        checkbox("Use AoE replacements", "useAOE")
        sliderInt("AoE target threshold", "minAOETargets", 2, 5)

        GUI:Separator()
        GUI:Text("Current decision: " .. tostring(CielBardEngine.state.lastDecision))
        GUI:Text("Last action: " .. tostring(CielBardEngine.state.lastActionName))
        GUI:Text("Song: " .. tostring(CielBardEngine.state.currentSong) ..
            "  remaining: " .. string.format("%.1f", CielBardEngine.state.songRemaining or 0))
        GUI:Text("Enemies near target: " .. tostring(CielBardEngine.state.enemyCount or 1))

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

                local warnings = CielBardEngine.GetConfigurationWarnings()
                if #warnings > 0 then
                    GUI:Separator()
                    GUI:Text("Configuration warnings")
                    for _, warning in ipairs(warnings) do GUI:TextWrapped("- " .. warning) end
                end
            end
        end

        if GUI:CollapsingHeader("Gauge diagnostics") then
            sliderInt("Soul Voice gauge index", "soulVoiceGaugeIndex", 1, 8)
            sliderInt("Repertoire gauge index", "repertoireGaugeIndex", 1, 8)
            sliderInt("Song timer gauge index", "songTimerGaugeIndex", 1, 8)
            GUI:Text("Selected Soul Voice: " .. tostring(CielBardEngine.GetSoulVoice()))
            GUI:Text("Selected Repertoire: " .. tostring(CielBardEngine.GetRepertoire()))
            if Player and Player.gauge then
                for index = 1, 8 do
                    GUI:Text("Gauge[" .. index .. "] = " .. tostring(Player.gauge[index]))
                end
            end
            GUI:TextWrapped("Verify the index that moves from 0 to 100 as Soul Voice and the 0-3 index as Repertoire, then set them above.")
        end

        if GUI:Button("Reset combat state", 170, 25) then
            CielBardEngine.ResetCombat("Manual reset")
        end
        GUI:SameLine()
        if GUI:Button(config.enabled and "STOP" or "START", 100, 25) then
            config.enabled = not config.enabled
        end
    end
    GUI:End()
end

RegisterEventHandler("Module.Initalize", CielBard.Init, "CielBard.Init")
RegisterEventHandler("Gameloop.Update", CielBard.Update, "CielBard.Update")
RegisterEventHandler("Gameloop.Draw", CielBard.Draw, "CielBard.Draw")
