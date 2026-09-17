local CielBard = {
    windowOpen = true,
    initialized = false,
}

local function copyDefaults(destination, defaults)
    for key, value in pairs(defaults) do
        if destination[key] == nil then destination[key] = value end
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
