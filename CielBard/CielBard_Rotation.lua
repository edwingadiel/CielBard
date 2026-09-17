CielBardEngine = CielBardEngine or {}

local E = CielBardEngine
local D = CielBardData
local A = D.Actions

E.config = nil
E.state = {
    lastPulse = 0,
    lastRequestAt = 0,
    lastRequestID = 0,
    lastObservedCastID = 0,
    lastObservedTimeSince = 999999,
    weavesSinceGCD = 0,
    gcdsSinceRaging = 99,
    ragingAt = 0,
    battleVoiceAt = 0,
    radiantFinaleAt = 0,
    lastBurstActionID = 0,
    lastBurstActionAt = 0,
    lastActionName = "Idle",
    lastDecision = "Disabled",
    currentSong = "NONE",
    songRemaining = 0,
    songStartedAt = 0,
    codas = { WM = false, MB = false, AP = false },
    ttk = nil,
    ttkConfidence = 0,
    ttkBand = "LEARNING",
    hpSamples = {},
    sampleTargetID = 0,
    lastSampleAt = 0,
    enemyCount = 1,
    multiDotTargetID = 0,
    multiDotTargetName = "None",
    multiDotScanAt = 0,
    multiDotCandidates = {},
    potionActionID = 0,
    potionName = "None",
    potionScanAt = 0,
    potionItem = nil,
    potionAction = nil,
    potionUsedAt = 0,
    charges = 3,
    chargeRemaining = 0,
    maxCharges = 3,
    chargeInfo = false,
}

local function now()
    if type(Now) == "function" then return Now() end
    return math.floor(os.clock() * 1000)
end

local function valid(value)
    if type(table.valid) == "function" then return table.valid(value) end
    return type(value) == "table" and next(value) ~= nil
end

local function clamp(value, low, high)
    if value < low then return low end
    if value > high then return high end
    return value
end

local function action(id)
    if not ActionList or not id then return nil end
    return ActionList:Get(1, id)
end

local function cooldownSeconds(ac)
    if not ac then return 999 end
    -- FFXIVMinion exposes cd as elapsed cooldown and cdmax as its length.
    -- The reference SkillMgr uses cdmax - cd for time remaining.
    local cd, cdmax = tonumber(ac.cd), tonumber(ac.cdmax)
    if cd and cdmax then return math.max(0, cdmax - cd) end
    if ac.isoncd == false then return 0 end
    return tonumber(ac.recasttime) or 999
end

local function gauge(index)
    if not Player or not valid(Player.gauge) then return 0 end
    return tonumber(Player.gauge[tonumber(index) or 0]) or 0
end

local function buffRemaining(entity, statusID, ownerID)
    if not entity or not statusID or statusID == 0 or not valid(entity.buffs) then return 0 end
    local best = 0
    for _, buff in pairs(entity.buffs) do
        if buff.id == statusID and (not ownerID or ownerID == 0 or buff.ownerid == ownerID) then
            best = math.max(best, tonumber(buff.duration) or 0)
        end
    end
    return best
end

local function actionStatusID(actionID)
    local ac = action(actionID)
    return ac and tonumber(ac.statusgainedid) or 0
end

local function ready(actionID, targetID)
    local ac = action(actionID)
    if not ac or ac.usable == false then return false end
    local ok, result = pcall(function() return ac:IsReady(targetID) end)
    return ok and result == true
end

local function highlighted(actionID)
    local ac = action(actionID)
    return ac and (ac.highlighted == true or tonumber(ac.highlighted) == 1)
end

local function songKeyForAction(actionID)
    for key, song in pairs(D.Songs) do
        if song.id == actionID then return key end
    end
    return nil
end

local function distance3(a, b)
    if not a or not b then return 999 end
    local dx = (a.x or 0) - (b.x or 0)
    local dy = (a.y or 0) - (b.y or 0)
    local dz = (a.z or 0) - (b.z or 0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)
end

local function abilityDefault(key)
    return D.AbilityDefaults[key] ~= false
end

function E.AbilityEnabled(key)
    local c = E.config or D.Defaults
    if not c.advancedEnabled then return abilityDefault(key) end
    local abilities = c.abilities or {}
    if abilities[key] == nil then return abilityDefault(key) end
    return abilities[key] ~= false
end

-- Per-action AoE thresholds. `useAOE` is the master switch; each replacement
-- has its own nearby-target count so radius differences can be tuned.
function E.AoETargetsFor(key)
    local c = E.config or D.Defaults
    local thresholds = c.aoeTargets or {}
    return tonumber(thresholds[key]) or tonumber(D.AoEDefaults[key]) or 2
end

function E.AoEAllowed(key, ctx)
    local c = E.config or D.Defaults
    if not c.useAOE or not E.AbilityEnabled(key) then return false end
    return (ctx.enemies or 1) >= E.AoETargetsFor(key)
end

function E.MinAoETargets()
    local best = 99
    for key in pairs(D.AoEDefaults) do best = math.min(best, E.AoETargetsFor(key)) end
    return best
end

function E.GetConfigurationWarnings()
    local warnings = {}
    local c = E.config or D.Defaults
    if c.usePotion and not E.PotionAvailable() then
        table.insert(warnings, "Potion use is On but no Gemdraught of Dexterity was found in inventory.")
    end
    if not c.advancedEnabled then return warnings end
    local enabled = E.AbilityEnabled
    if not enabled("WanderersMinuet") and not enabled("MagesBallad") and not enabled("ArmysPaeon") then
        table.insert(warnings, "All songs are Off; song automation will safely do nothing.")
    end
    if enabled("BlastArrow") and not enabled("ApexArrow") then
        table.insert(warnings, "Blast Arrow cannot normally be generated while Apex Arrow is Off.")
    end
    if enabled("ResonantArrow") and not enabled("Barrage") then
        table.insert(warnings, "Resonant Arrow cannot normally be generated while Barrage is Off.")
    end
    if enabled("RadiantEncore") and not enabled("RadiantFinale") then
        table.insert(warnings, "Radiant Encore cannot normally be generated while Radiant Finale is Off.")
    end
    if enabled("IronJaws") and (not enabled("Stormbite") or not enabled("CausticBite")) then
        table.insert(warnings, "Iron Jaws requires both DoTs; it will be skipped until both are active.")
    end
    if c.multiDot and not enabled("Stormbite") and not enabled("CausticBite") then
        table.insert(warnings, "Multi-dot is On but both DoTs are Off; no secondary DoTs will be applied.")
    end
    if enabled("RadiantFinale") and (tonumber(c.radiantFinaleMinCodas) or 1) > 1 then
        table.insert(warnings, "Radiant Finale minimum codas above 1 can delay or lose a use; the opener normally fires at one coda.")
    end
    if c.executionMode == "OGCD_ONLY" then
        table.insert(warnings, "oGCD-only mode expects you or another system to keep the GCD rolling.")
    end
    return warnings
end

local function majorBurstEnabled()
    return E.AbilityEnabled("RagingStrikes") or E.AbilityEnabled("BattleVoice") or E.AbilityEnabled("RadiantFinale")
end

local function startOrUpdateBurst(actionID, ticks)
    local s = E.state
    if s.lastBurstActionID == actionID and ticks - s.lastBurstActionAt < 1000 then return end
    s.lastBurstActionID, s.lastBurstActionAt = actionID, ticks
    local expired = s.ragingAt == 0 or ticks - s.ragingAt > 20500
    if actionID == A.RagingStrikes then
        s.ragingAt = ticks
        s.gcdsSinceRaging = 0
        s.battleVoiceAt = 0
        s.radiantFinaleAt = 0
    elseif actionID == A.BattleVoice then
        if expired then s.ragingAt, s.gcdsSinceRaging = ticks, 1 end
        s.battleVoiceAt = ticks
    elseif actionID == A.RadiantFinale then
        if expired then s.ragingAt, s.gcdsSinceRaging = ticks, 1 end
        s.radiantFinaleAt = ticks
        -- Radiant Finale consumes every coda.
        s.codas = { WM = false, MB = false, AP = false }
    end
end

local function noteSongCast(songKey, ticks)
    local s = E.state
    s.currentSong = songKey
    s.songStartedAt = ticks
    s.codas[songKey] = true
end

function E.CodaCount()
    local count = 0
    for _, has in pairs(E.state.codas) do
        if has then count = count + 1 end
    end
    return count
end

-- Seconds until the whole enabled burst package is ready: the MAXIMUM remaining
-- cooldown over the enabled buffs. Radiant Finale (110 s) comes up ~7.5 s before
-- Raging Strikes and Battle Voice (120 s); taking the minimum made every
-- pre-burst hold (Empyreal, charges, Apex) start that much too early. Measured
-- in the simulator: one lost Empyreal Arrow per burst window.
local function nextBurstSeconds()
    if not majorBurstEnabled() then return 999, false end
    local worst = 0
    local candidates = {
        { "RagingStrikes", A.RagingStrikes },
        { "BattleVoice", A.BattleVoice },
        { "RadiantFinale", A.RadiantFinale },
    }
    for _, candidate in ipairs(candidates) do
        if E.AbilityEnabled(candidate[1]) then
            local remaining = ready(candidate[2], Player.id) and 0 or cooldownSeconds(action(candidate[2]))
            if remaining >= 999 then remaining = 0 end -- no cooldown data: treat as ready
            worst = math.max(worst, remaining)
        end
    end
    return worst, true
end

local function songEnabled(key)
    local names = { WM = "WanderersMinuet", MB = "MagesBallad", AP = "ArmysPaeon" }
    return names[key] and E.AbilityEnabled(names[key])
end

local function nextEnabledSong(current)
    local key = current == "NONE" and "WM" or D.Songs[current].next
    for _ = 1, 3 do
        if songEnabled(key) then return key end
        key = D.Songs[key].next
    end
    return nil
end

local function songSwapThreshold(key)
    local c = E.config
    local thresholds = { WM = c.wmSwapRemaining, MB = c.mbSwapRemaining, AP = c.apSwapRemaining }
    return tonumber(thresholds[key]) or 1
end

function E.Init(config)
    E.config = config
    E.ResetCombat("Initialized")
end

function E.ResetCombat(reason)
    local s = E.state
    s.weavesSinceGCD = 0
    s.gcdsSinceRaging = 99
    s.ragingAt = 0
    s.battleVoiceAt = 0
    s.radiantFinaleAt = 0
    s.lastBurstActionID = 0
    s.lastBurstActionAt = 0
    s.currentSong = "NONE"
    s.songRemaining = 0
    s.songStartedAt = 0
    s.codas = { WM = false, MB = false, AP = false }
    s.ttk = nil
    s.ttkConfidence = 0
    s.ttkBand = "LEARNING"
    s.hpSamples = {}
    s.sampleTargetID = 0
    s.lastSampleAt = 0
    s.enemyCount = 1
    s.multiDotTargetID = 0
    s.multiDotTargetName = "None"
    s.multiDotScanAt = 0
    s.multiDotCandidates = {}
    s.charges = 3
    s.chargeRemaining = 0
    s.lastDecision = reason or "Reset"
end

function E.GetGauge(index)
    return gauge(index)
end

function E.GetSoulVoice()
    return gauge(E.config.soulVoiceGaugeIndex)
end

function E.GetRepertoire()
    return gauge(E.config.repertoireGaugeIndex)
end

function E.GetTarget()
    if not Player or type(Player.GetTarget) ~= "function" then return nil end
    local target = Player:GetTarget()
    if not target or not target.id or target.id == 0 then return nil end
    if target.alive == false or target.targetable == false then return nil end
    if target.hp and tonumber(target.hp.current) and target.hp.current <= 0 then return nil end
    return target
end

function E.CountEnemiesNear(target)
    if not E.config.useAOE or not target or not target.pos or not EntityList then return 1 end
    local list = EntityList("alive,attackable,maxdistance=30")
    if not valid(list) then return 1 end
    local count = 0
    for _, entity in pairs(list) do
        if entity and entity.targetable ~= false and entity.pos and distance3(entity.pos, target.pos) <= 5 then
            count = count + 1
        end
    end
    return math.max(1, count)
end

function E.UpdateTTK(target, ticks)
    local s, c = E.state, E.config
    if not c.autoTTK then
        s.ttk = tonumber(c.manualTTK) or 999
        s.ttkConfidence = 1
        return
    end
    if not target or not target.hp or not target.hp.percent then
        s.ttk, s.ttkConfidence = nil, 0
        return
    end
    if s.sampleTargetID ~= target.id then
        s.hpSamples = {}
        s.sampleTargetID = target.id
        s.lastSampleAt = 0
        s.ttk = nil
    end
    if ticks - s.lastSampleAt >= 400 then
        s.lastSampleAt = ticks
        table.insert(s.hpSamples, { t = ticks / 1000, hp = tonumber(target.hp.percent) or 0 })
    end
    local cutoff = ticks / 1000 - (tonumber(c.ttkSampleWindow) or 8)
    while #s.hpSamples > 0 and s.hpSamples[1].t < cutoff do table.remove(s.hpSamples, 1) end
    if #s.hpSamples < 5 then s.ttkConfidence = #s.hpSamples / 5 return end

    local n, sumT, sumH = #s.hpSamples, 0, 0
    for _, sample in ipairs(s.hpSamples) do sumT = sumT + sample.t; sumH = sumH + sample.hp end
    local meanT, meanH = sumT / n, sumH / n
    local numerator, denominator = 0, 0
    for _, sample in ipairs(s.hpSamples) do
        numerator = numerator + (sample.t - meanT) * (sample.hp - meanH)
        denominator = denominator + (sample.t - meanT) * (sample.t - meanT)
    end
    local slope = denominator > 0 and numerator / denominator or 0
    if slope < -0.01 then
        local estimate = clamp((tonumber(target.hp.percent) or 0) / -slope, 0, 999)
        s.ttk = s.ttk and (s.ttk * 0.7 + estimate * 0.3) or estimate
        s.ttkConfidence = clamp((s.hpSamples[#s.hpSamples].t - s.hpSamples[1].t) / c.ttkSampleWindow, 0, 1)
    else
        s.ttk, s.ttkConfidence = nil, 0
    end
end

function E.ObserveLastCast()
    if not Player or not Player.castinginfo then return end
    local info = Player.castinginfo
    local castID = tonumber(info.lastcastid) or 0
    local since = tonumber(info.timesincecast) or 999999
    local s = E.state
    local isNew = castID ~= 0 and (castID ~= s.lastObservedCastID or since + 50 < s.lastObservedTimeSince)
    s.lastObservedTimeSince = since
    if not isNew then return end
    s.lastObservedCastID = castID
    -- The potion request already counted itself as a weave.
    if s.potionActionID ~= 0 and castID == s.potionActionID then return end
    local ac = action(castID)
    s.lastActionName = (ac and ac.name) or tostring(castID)

    if D.GCD[castID] then
        s.weavesSinceGCD = 0
        if s.ragingAt > 0 then s.gcdsSinceRaging = s.gcdsSinceRaging + 1 end
    else
        s.weavesSinceGCD = s.weavesSinceGCD + 1
    end
    if castID == A.RagingStrikes or castID == A.BattleVoice or castID == A.RadiantFinale then
        startOrUpdateBurst(castID, now())
    end
    local songKey = songKeyForAction(castID)
    if songKey then noteSongCast(songKey, now()) end
end

function E.GetSong()
    if not Player then return "NONE", 0 end
    for key, song in pairs(D.Songs) do
        local status = actionStatusID(song.id)
        local remaining = buffRemaining(Player, status, Player.id)
        if remaining > 0 then return key, remaining end
    end
    -- Some MMOMinion builds do not expose the song's statusgainedid. Retain a
    -- local 45-second timer after a successful/observed song cast as fallback.
    if E.state.currentSong ~= "NONE" and E.state.songStartedAt > 0 then
        local remaining = 45 - ((now() - E.state.songStartedAt) / 1000)
        if remaining > 0 then return E.state.currentSong, remaining end
    end
    return "NONE", 0
end

function E.GetDotState(target)
    local storm = math.max(
        buffRemaining(target, D.Statuses.Stormbite, Player.id),
        buffRemaining(target, D.Statuses.Windbite, Player.id)
    )
    local caustic = math.max(
        buffRemaining(target, D.Statuses.CausticBite, Player.id),
        buffRemaining(target, D.Statuses.VenomousBite, Player.id)
    )
    return storm, caustic
end

function E.TryCast(actionID, target, decision)
    local ticks, s = now(), E.state
    if ticks - s.lastRequestAt < E.config.requestThrottleMs then return false end
    local targetID = D.SelfTarget[actionID] and Player.id or (target and target.id)
    if not targetID or not ready(actionID, targetID) then return false end
    local ac = action(actionID)
    local ok, result = pcall(function() return ac:Cast(targetID) end)
    if ok and result then
        s.lastRequestAt = ticks
        s.lastRequestID = actionID
        s.lastDecision = decision or (ac.name or tostring(actionID))
        local songKey = songKeyForAction(actionID)
        if songKey then noteSongCast(songKey, ticks) end
        if actionID == A.RagingStrikes or actionID == A.BattleVoice or actionID == A.RadiantFinale then
            startOrUpdateBurst(actionID, ticks)
        end
        return true
    end
    return false
end

-- Potions -----------------------------------------------------------------

local function findInventoryItem(hqid)
    -- Prefer FFXIVMinion's helper when loaded; otherwise scan the four
    -- standard inventory bags the same way the reference bot does.
    if type(GetItem) == "function" then
        local ok, item, itemAction = pcall(GetItem, hqid, { 0, 1, 2, 3 })
        if ok and item then return item, itemAction end
        return nil, nil
    end
    if not Inventory or type(Inventory.Get) ~= "function" then return nil, nil end
    for _, bagID in ipairs({ 0, 1, 2, 3 }) do
        local bag = Inventory:Get(bagID)
        if valid(bag) and tonumber(bag.size) then
            for slot = 0, bag.size - 1 do
                local item = bag:GetItem(slot)
                if item and item.hqid == hqid then
                    local itemAction = type(item.GetAction) == "function" and item:GetAction() or nil
                    return item, itemAction
                end
            end
        end
    end
    return nil, nil
end

function E.RefreshPotion(force)
    local s, c = E.state, E.config or D.Defaults
    local ticks = now()
    -- Inventory scans are slow in MMOMinion; refresh at most every 5 seconds.
    if not force and ticks - s.potionScanAt < 5000 then return end
    s.potionScanAt = ticks
    s.potionItem, s.potionAction, s.potionName = nil, nil, "None"
    for _, potion in ipairs(D.Potions) do
        local candidates = { potion.id + D.HQOffset }
        if not c.potionHQOnly then table.insert(candidates, potion.id) end
        for _, hqid in ipairs(candidates) do
            local item, itemAction = findInventoryItem(hqid)
            if item then
                s.potionItem, s.potionAction = item, itemAction
                s.potionName = potion.name .. (hqid > D.HQOffset and " (HQ)" or "")
                if itemAction and tonumber(itemAction.id) then s.potionActionID = tonumber(itemAction.id) end
                return
            end
        end
    end
end

function E.PotionAvailable()
    E.RefreshPotion(false)
    return E.state.potionItem ~= nil
end

function E.PotionReady()
    local s = E.state
    if not E.PotionAvailable() then return false end
    local item, itemAction = s.potionItem, s.potionAction
    if itemAction and itemAction.isoncd == true then return false end
    if itemAction and cooldownSeconds(itemAction) > 0.5 then return false end
    if type(item.IsReady) == "function" then
        local ok, result = pcall(function() return item:IsReady(Player.id) end)
        if not ok or result ~= true then return false end
    end
    return true
end

function E.TryPotion(ctx, decision)
    local s, c = E.state, E.config
    local ticks = now()
    if ticks - s.lastRequestAt < c.requestThrottleMs then return false end
    if ticks - s.potionUsedAt < 3000 then return false end
    if not E.PotionReady() then return false end
    local item = s.potionItem
    local ok, result = pcall(function() return item:Cast(Player.id) end)
    if ok and result then
        s.lastRequestAt = ticks
        s.potionUsedAt = ticks
        s.lastDecision = decision or ("Potion: " .. s.potionName)
        s.lastActionName = s.potionName
        -- Items are not seen by ObserveLastCast on every build; count the
        -- animation lock as a weave here and ignore the later echo.
        s.weavesSinceGCD = s.weavesSinceGCD + 1
        return true
    end
    return false
end

-- Multi-dot ----------------------------------------------------------------

function E.FindMultiDotTarget(ctx)
    local s, c = E.state, E.config
    s.multiDotTargetID, s.multiDotTargetName = 0, "None"
    if not c.multiDot or not ctx.target or not EntityList then return nil end
    if ctx.terminal or ctx.idealFinish then return nil end
    if ctx.ttk <= c.dotMinimumTTK then return nil end
    local wantStorm, wantCaustic = E.AbilityEnabled("Stormbite"), E.AbilityEnabled("CausticBite")
    if not wantStorm and not wantCaustic then return nil end

    local ticks = now()
    if ticks - s.multiDotScanAt >= 500 then
        s.multiDotScanAt = ticks
        local candidates = {}
        -- Only enemies already in combat are considered so the engine never
        -- pulls an idle pack by applying a DoT to it.
        local list = EntityList("alive,attackable,incombat,maxdistance=25")
        if valid(list) then
            for _, entity in pairs(list) do
                if entity and entity.id and entity.id ~= ctx.target.id and entity.targetable ~= false and
                    entity.incombat ~= false and entity.los ~= false and entity.hp and
                    (tonumber(entity.hp.percent) or 0) >= (tonumber(c.multiDotMinHPPercent) or 0) then
                    table.insert(candidates, entity)
                end
            end
        end
        -- Highest HP first: those targets live longest and pay back the DoT.
        table.sort(candidates, function(a, b)
            return (tonumber(a.hp.current) or 0) > (tonumber(b.hp.current) or 0)
        end)
        s.multiDotCandidates = {}
        for index = 1, math.min(#candidates, tonumber(c.multiDotMaxTargets) or 3) do
            s.multiDotCandidates[index] = candidates[index]
        end
    end

    local refresh = tonumber(c.dotRefreshSeconds) or 3
    for _, entity in ipairs(s.multiDotCandidates) do
        local storm, caustic = E.GetDotState(entity)
        local needStorm = wantStorm and storm <= refresh
        local needCaustic = wantCaustic and caustic <= refresh
        if needStorm or needCaustic then
            s.multiDotTargetID = entity.id
            s.multiDotTargetName = entity.name or tostring(entity.id)
            return entity, storm, caustic
        end
    end
    return nil
end

function E.TryMultiDot(ctx)
    local c = E.config
    local extra, storm, caustic = E.FindMultiDotTarget(ctx)
    if not extra then return false end
    local refresh = tonumber(c.dotRefreshSeconds) or 3
    local ironJawsEnabled = E.AbilityEnabled("IronJaws") and
        E.AbilityEnabled("Stormbite") and E.AbilityEnabled("CausticBite")
    if ironJawsEnabled and storm > 0.2 and caustic > 0.2 and
        E.TryCast(A.IronJaws, extra, "Multi-dot Iron Jaws refresh") then return true end
    if E.AbilityEnabled("Stormbite") and storm <= refresh and
        (E.TryCast(A.Stormbite, extra, "Multi-dot Stormbite") or
         E.TryCast(A.Windbite, extra, "Multi-dot Windbite fallback")) then return true end
    if E.AbilityEnabled("CausticBite") and caustic <= refresh and
        (E.TryCast(A.CausticBite, extra, "Multi-dot Caustic Bite") or
         E.TryCast(A.VenomousBite, extra, "Multi-dot Venomous Bite fallback")) then return true end
    return false
end

-- Context ------------------------------------------------------------------

function E.BuildContext(target)
    local s, c = E.state, E.config
    local song, songRemaining = E.GetSong()
    s.currentSong, s.songRemaining = song, songRemaining
    local storm, caustic = E.GetDotState(target)
    local nextBurst, burstConfigured = nextBurstSeconds()
    local burstElapsed = s.ragingAt > 0 and (now() - s.ragingAt) / 1000 or 999
    local burstActive = burstElapsed <= 20.5
    local learnedTTK = s.ttk
    local trustedTTK = learnedTTK and s.ttkConfidence >= (tonumber(c.minimumTTKConfidence) or 0.5)
    local ttk = (not c.autoTTK and tonumber(c.manualTTK)) or (trustedTTK and learnedTTK) or 999
    local band = "SUSTAIN"
    if not trustedTTK and c.autoTTK then
        band = "LEARNING"
    elseif ttk <= c.terminalTTK then
        band = "TERMINAL"
    elseif ttk <= c.idealKillMax then
        band = "IDEAL_FINISH"
    elseif ttk <= 60 then
        band = "EXTENDED_TAIL"
    end
    s.ttkBand = band

    local stormOn = not E.AbilityEnabled("Stormbite") or storm > 5
    local causticOn = not E.AbilityEnabled("CausticBite") or caustic > 5
    local anyDotEnabled = E.AbilityEnabled("Stormbite") or E.AbilityEnabled("CausticBite")
    local anyDotOn = (E.AbilityEnabled("Stormbite") and storm > 0) or (E.AbilityEnabled("CausticBite") and caustic > 0)

    local nextSongKey = nextEnabledSong(song)
    local songSwapIn = 999
    if song ~= "NONE" then
        songSwapIn = math.max(0, songRemaining - songSwapThreshold(song))
    elseif nextSongKey then
        songSwapIn = 0
    end

    return {
        target = target,
        ttk = ttk,
        terminal = c.terminalDumping and ttk <= c.terminalTTK,
        idealFinish = ttk > c.terminalTTK and ttk <= c.idealKillMax,
        enemies = s.enemyCount,
        aoe = c.useAOE and s.enemyCount >= E.MinAoETargets(),
        storm = storm,
        caustic = caustic,
        song = song,
        songRemaining = songRemaining,
        nextSongKey = nextSongKey,
        songSwapIn = songSwapIn,
        codas = E.CodaCount(),
        nextBurst = nextBurst,
        burstElapsed = burstElapsed,
        burstActive = burstActive,
        burstConfigured = burstConfigured,
        dotsReady = stormOn and causticOn,
        oneDotReady = not anyDotEnabled or anyDotOn,
        ttkBand = band,
        soulVoice = E.GetSoulVoice(),
        repertoire = E.GetRepertoire(),
    }
end

-- Radiant Finale is only worth requesting with at least one coda, and a song
-- that is due within a couple of seconds should land first when it would add
-- a coda. The hold is skipped when the fight is ending.
function E.RadiantFinaleAllowed(ctx)
    local c = E.config
    if not E.AbilityEnabled("RadiantFinale") then return false end
    local codas = ctx.codas or 0
    if codas <= 0 then return false end
    if ctx.terminal or ctx.idealFinish then return true end
    if codas < (tonumber(c.radiantFinaleMinCodas) or 1) then return false end
    if codas < 3 and ctx.nextSongKey and not E.state.codas[ctx.nextSongKey] and
        c.automaticSongCycle and (ctx.songSwapIn or 999) <= (tonumber(c.radiantFinaleCodaHold) or 0) then
        return false
    end
    return true
end

function E.BurstDotGateSatisfied(ctx)
    local mode = E.config.burstDotGate or "ONE"
    if ctx.terminal then return true end
    if ctx.ttk <= E.config.dotMinimumTTK then return true end
    if mode == "NONE" then return true end
    if mode == "BOTH" then return ctx.dotsReady end
    return ctx.oneDotReady
end

function E.TrySong(ctx)
    if not E.config.automaticSongCycle then return false end
    local nextKey = ctx.nextSongKey or nextEnabledSong(ctx.song)
    if not nextKey then return false end
    if ctx.song == "NONE" then
        return E.TryCast(D.Songs[nextKey].id, ctx.target, "Start " .. D.Songs[nextKey].name)
    end
    local shouldSwap = not songEnabled(ctx.song) or ctx.songRemaining <= songSwapThreshold(ctx.song)
    if shouldSwap and (nextKey ~= ctx.song or ctx.songRemaining <= 0.2) then
        return E.TryCast(D.Songs[nextKey].id, ctx.target,
            ctx.song .. " -> " .. nextKey .. " using enabled-song cycle")
    end
    return false
end

function E.TryGCD(ctx)
    local target, c = ctx.target, E.config

    -- Establish only the enabled DoTs. If Iron Jaws is Off (or one DoT is
    -- disabled), each enabled DoT is refreshed manually instead.
    if ctx.ttk > c.dotMinimumTTK then
        if E.AbilityEnabled("Stormbite") and ctx.storm <= 0.2 and
            (E.TryCast(A.Stormbite, target, "Apply Stormbite") or
             E.TryCast(A.Windbite, target, "Apply Windbite fallback")) then return true end
        if E.AbilityEnabled("CausticBite") and ctx.caustic <= 0.2 and
            (E.TryCast(A.CausticBite, target, "Apply Caustic Bite") or
             E.TryCast(A.VenomousBite, target, "Apply Venomous Bite fallback")) then return true end
    end

    -- A DoT about to fall off outranks the proc consumers: Blast, Resonant,
    -- Encore and Apex can chain two GCDs deep (~5 s) and let both DoTs expire,
    -- costing two hard re-applications. Only fires when a DoT is actually
    -- present (> 0.2) so it never wastes Iron Jaws on a clean target.
    local ironJawsEnabled = E.AbilityEnabled("IronJaws") and
        E.AbilityEnabled("Stormbite") and E.AbilityEnabled("CausticBite")
    if ironJawsEnabled and ctx.ttk > c.dotMinimumTTK then
        local soonest = math.min(ctx.storm, ctx.caustic)
        if soonest > 0.2 and soonest <= (tonumber(c.dotUrgentSeconds) or 1.5) and
            E.TryCast(A.IronJaws, target, "Urgent Iron Jaws before DoT falls off") then return true end
    end

    -- Transformed/proc actions are identified by MMOMinion's IsReady state.
    if E.AbilityEnabled("BlastArrow") and ready(A.BlastArrow, target.id) and
        E.TryCast(A.BlastArrow, target, "Consume Blast Arrow") then return true end
    if E.AbilityEnabled("ResonantArrow") and ready(A.ResonantArrow, target.id) and
        E.TryCast(A.ResonantArrow, target, "Consume Resonant Arrow") then return true end
    if E.AbilityEnabled("RadiantEncore") and ready(A.RadiantEncore, target.id) and
        (ctx.burstActive or ctx.terminal) and
        E.TryCast(A.RadiantEncore, target, "Radiant Encore in buffs") then return true end

    if E.AbilityEnabled("ApexArrow") then
        local apexThreshold = c.apexOffcycleGauge
        if ctx.burstActive then apexThreshold = c.apexBurstGauge end
        if ctx.terminal then apexThreshold = 20 end
        local shouldApex = ctx.soulVoice >= apexThreshold
        if c.resourcePooling and ctx.burstConfigured and not ctx.burstActive and not ctx.terminal and
            ctx.nextBurst <= c.apexHoldForBurstSeconds and ctx.soulVoice < 95 then
            shouldApex = false
        end
        if shouldApex and E.TryCast(A.ApexArrow, target,
            "Apex Arrow at " .. tostring(ctx.soulVoice) .. " gauge") then return true end
    end

    -- Snapshot late in buffs only when enough lifetime remains; otherwise use
    -- the ordinary near-expiration refresh.
    if ironJawsEnabled and c.snapshotIronJaws and ctx.burstActive and ctx.burstElapsed >= 15 and
        ctx.ttk > c.dotMinimumTTK and
        math.min(ctx.storm, ctx.caustic) < 22 and
        E.TryCast(A.IronJaws, target, "Late-buff Iron Jaws snapshot") then return true end
    if ironJawsEnabled and ctx.ttk > c.dotMinimumTTK and
        math.min(ctx.storm, ctx.caustic) <= c.dotRefreshSeconds and
        E.TryCast(A.IronJaws, target, "Refresh both DoTs") then return true end
    if not ironJawsEnabled and ctx.ttk > c.dotMinimumTTK then
        if E.AbilityEnabled("Stormbite") and ctx.storm <= c.dotRefreshSeconds and
            (E.TryCast(A.Stormbite, target, "Manual Stormbite refresh") or
             E.TryCast(A.Windbite, target, "Manual Windbite refresh")) then return true end
        if E.AbilityEnabled("CausticBite") and ctx.caustic <= c.dotRefreshSeconds and
            (E.TryCast(A.CausticBite, target, "Manual Caustic Bite refresh") or
             E.TryCast(A.VenomousBite, target, "Manual Venomous Bite refresh")) then return true end
    end

    if E.AbilityEnabled("RadiantEncore") and ready(A.RadiantEncore, target.id) and
        E.TryCast(A.RadiantEncore, target, "Consume Radiant Encore") then return true end
    if E.AoEAllowed("Shadowbite", ctx) and ready(A.Shadowbite, target.id) and
        E.TryCast(A.Shadowbite, target, "Shadowbite cleave") then return true end
    if E.AbilityEnabled("RefulgentArrow") and ready(A.RefulgentArrow, target.id) and
        E.TryCast(A.RefulgentArrow, target, "Consume Refulgent Arrow") then return true end

    -- Secondary DoT targets come after procs and ahead of plain filler.
    if E.TryMultiDot(ctx) then return true end

    if E.AoEAllowed("Ladonsbite", ctx) and
        (E.TryCast(A.Ladonsbite, target, "Ladonsbite cleave") or
         E.TryCast(A.QuickNock, target, "Quick Nock fallback")) then return true end
    -- Non-configurable emergency filler: custom settings must never stall the
    -- GCD merely because every optional action was switched Off.
    if E.TryCast(A.BurstShot, target, "Burst Shot emergency filler") then return true end
    return E.TryCast(A.HeavyShot, target, "Heavy Shot level-sync fallback")
end

-- Shared-charge model (Heartbreak Shot / Bloodletter / Rain of Death).
-- The client exposes the game's charged-recast layout directly: cdmax is the
-- full stack (recast x max charges, 45s for three), cd is elapsed, and the
-- charge count is floor(cd / recast). Off cooldown means a full stack.
function E.UpdateCharges()
    local s = E.state
    local ac = action(E.AbilityEnabled("HeartbreakShot") and A.HeartbreakShot or A.Bloodletter)
    local cd, cdmax, recast = ac and tonumber(ac.cd), ac and tonumber(ac.cdmax), ac and tonumber(ac.recasttime)
    if not ac or not recast or recast <= 0 then s.chargeInfo = false return end
    s.chargeInfo = true
    local maxCharges = (cdmax and cdmax >= recast * 2) and math.floor(cdmax / recast + 0.5) or 3
    s.maxCharges = maxCharges
    if ac.isoncd == false or not cd or not cdmax or cdmax <= 0 then
        s.charges, s.chargeRemaining = maxCharges, 0
        return
    end
    s.charges = clamp(math.floor(cd / recast), 0, maxCharges)
    s.chargeRemaining = s.charges >= maxCharges and 0 or (recast - (cd % recast))
end

local function noteChargeSpent()
    local s = E.state
    s.charges = math.max(0, (s.charges or 0) - 1)
end

-- True when a charge would be wasted soon: already full, or the last charge
-- completes within about one GCD.
local function chargeAboutToCap(ctx)
    local s = E.state
    if not s.chargeInfo then return true end -- no data: never hold
    local maxCharges = s.maxCharges or 3
    if s.charges >= maxCharges then return true end
    return s.charges == maxCharges - 1 and s.chargeRemaining <= (tonumber(E.config.chargeCapLeadSeconds) or 2.5)
end

local function chargeActions(ctx)
    local result = {}
    if E.AoEAllowed("RainOfDeath", ctx) then table.insert(result, A.RainOfDeath) end
    if E.AbilityEnabled("HeartbreakShot") then table.insert(result, A.HeartbreakShot) end
    if E.AbilityEnabled("Bloodletter") then table.insert(result, A.Bloodletter) end
    return result
end

local function tryCharge(ctx, decision)
    for _, actionID in ipairs(chargeActions(ctx)) do
        if E.TryCast(actionID, ctx.target, decision) then noteChargeSpent() return true end
    end
    return false
end

local function chargeCooldown(ctx)
    local best = 999
    for _, actionID in ipairs(chargeActions(ctx)) do
        best = math.min(best, cooldownSeconds(action(actionID)))
    end
    return best
end

local function hasDispellableDebuff(entity)
    if not entity or not valid(entity.buffs) then return false end
    for _, buff in pairs(entity.buffs) do
        if buff and (buff.dispellable == true or buff.canDispel == true or buff.candispel == true) then
            return true
        end
    end
    return false
end

function E.TryUtility(ctx)
    local hp = Player and Player.hp and tonumber(Player.hp.percent) or 100
    if E.AbilityEnabled("SecondWind") and hp <= E.config.secondWindHP and
        E.TryCast(A.SecondWind, ctx.target, "Second Wind emergency heal") then return true end
    if E.AbilityEnabled("WardensPaean") and hasDispellableDebuff(Player) and
        E.TryCast(A.WardensPaean, ctx.target, "Warden's Paean dispel") then return true end
    if E.AbilityEnabled("NaturesMinne") and hp <= E.config.minneHP and
        E.TryCast(A.NaturesMinne, ctx.target, "Nature's Minne self-support") then return true end
    if E.AbilityEnabled("Troubadour") and hp <= E.config.troubadourHP and
        E.TryCast(A.Troubadour, ctx.target, "Troubadour defensive") then return true end
    return false
end

local function potionWanted(ctx)
    local c = E.config
    if not c.usePotion then return false end
    if ctx.ttk < (tonumber(c.potionMinimumTTK) or 0) then return false end
    return true
end

local function tryStartBurst(ctx)
    if E.AbilityEnabled("RagingStrikes") and
        E.TryCast(A.RagingStrikes, ctx.target, "Begin burst with Raging Strikes") then return true end
    if E.AbilityEnabled("BattleVoice") and
        E.TryCast(A.BattleVoice, ctx.target, "Begin burst with Battle Voice") then return true end
    if E.RadiantFinaleAllowed(ctx) and
        E.TryCast(A.RadiantFinale, ctx.target, "Begin burst with Radiant Finale") then return true end
    return false
end

function E.TryOGCD(ctx)
    local s, c, target = E.state, E.config, ctx.target
    if s.weavesSinceGCD >= c.maxWeaves then return false end

    if E.TryUtility(ctx) then return true end
    if E.TrySong(ctx) then return true end

    local songReady = ctx.song == "WM" or ctx.terminal or ctx.idealFinish or
        not c.automaticSongCycle or not E.AbilityEnabled("WanderersMinuet")
    local burstStartable = ctx.burstConfigured and ctx.nextBurst <= 0.1 and songReady and
        E.BurstDotGateSatisfied(ctx)
    if burstStartable then
        -- The potion goes into the same weave window immediately before
        -- Raging Strikes so its 30 seconds cover the whole buff package.
        if potionWanted(ctx) and s.weavesSinceGCD + 1 < c.maxWeaves and
            E.TryPotion(ctx, "Potion before burst: " .. tostring(s.potionName)) then return true end
        if tryStartBurst(ctx) then return true end
    end
    -- Once Raging Strikes is out the burst timer jumps to 120 s, so the
    -- potion also gets the first weave slots of the active window.
    if potionWanted(ctx) and ctx.burstActive and ctx.burstElapsed <= 5 and
        E.TryPotion(ctx, "Potion in burst window: " .. tostring(s.potionName)) then return true end
    if potionWanted(ctx) and not c.potionOnlyWithBurst and not ctx.burstActive and
        E.TryPotion(ctx, "Potion on cooldown: " .. tostring(s.potionName)) then return true end

    if ctx.burstActive then
        -- Preserve the optimized filler weave after Raging when an enabled
        -- charge spender exists; otherwise continue directly to party buffs.
        if s.gcdsSinceRaging == 0 and E.AbilityEnabled("RagingStrikes") and
            tryCharge(ctx, "Pre-party-buff charge weave") then return true end

        if E.AbilityEnabled("BattleVoice") and
            E.TryCast(A.BattleVoice, target, "Battle Voice") then return true end
        if E.RadiantFinaleAllowed(ctx) and
            E.TryCast(A.RadiantFinale, target, "Radiant Finale at " .. tostring(ctx.codas) .. " coda") then return true end

        local mayBarrage = not E.AbilityEnabled("RefulgentArrow") or not highlighted(A.RefulgentArrow)
        if E.AbilityEnabled("Barrage") and mayBarrage and
            E.TryCast(A.Barrage, target, "Barrage after clearing enabled proc") then return true end

        if E.AbilityEnabled("PitchPerfect") and
            (ctx.repertoire >= 3 or (ctx.song == "WM" and ctx.songRemaining <= 3) or ctx.terminal) and
            E.TryCast(A.PitchPerfect, target, "Pitch Perfect stack dump") then return true end
        if E.AbilityEnabled("EmpyrealArrow") and
            E.TryCast(A.EmpyrealArrow, target, "Empyreal Arrow inside buffs") then return true end
        if E.AbilityEnabled("Sidewinder") and
            E.TryCast(A.Sidewinder, target, "Sidewinder inside buffs") then return true end
        if tryCharge(ctx, ctx.aoe and "Enabled charge spender in cleave" or "Enabled charge spender in buffs") then return true end
    else
        -- Shared charges are spent on cooldown. In the run-up to a two-minute
        -- burst (roughly the Army's Paeon tail) they are pooled so the burst
        -- opens with all three. While pooling, a full stack is only spent when
        -- the burst is still more than one recharge away, so the charge is
        -- back before it starts.
        local pooling = c.resourcePooling and ctx.burstConfigured and not ctx.terminal and
            ctx.nextBurst <= (tonumber(c.chargePoolSeconds) or 25)
        local spend = not pooling
        if pooling and E.state.chargeInfo and E.state.charges >= (E.state.maxCharges or 3) and
            ctx.nextBurst > (tonumber(c.chargeRechargeSeconds) or 15) then spend = true end
        if not E.state.chargeInfo then spend = true end -- no charge data: never hold
        if spend and tryCharge(ctx, pooling and "Heartbreak Shot at 3 (recharges before burst)"
                or (ctx.aoe and "Rain of Death on cooldown" or "Heartbreak Shot on cooldown")) then return true end

        if E.AbilityEnabled("PitchPerfect") and ctx.song == "WM" and
            (ctx.repertoire >= 3 or ctx.songRemaining <= 3) and
            E.TryCast(A.PitchPerfect, target, "Pitch Perfect before overcap/song end") then return true end

        -- Empyreal Arrow is 260 potency; a buff window adds ~52 to it, while a
        -- delayed use risks losing a whole 260. The pre-burst hold defaults to 0.
        local holdEmpyreal = c.resourcePooling and ctx.burstConfigured and not ctx.terminal and
            (tonumber(c.empyrealHoldForBurstSeconds) or 0) > 0 and
            ctx.nextBurst <= (tonumber(c.empyrealHoldForBurstSeconds) or 0)
        if E.AbilityEnabled("EmpyrealArrow") and not holdEmpyreal and
            E.TryCast(A.EmpyrealArrow, target, "Empyreal Arrow on cooldown") then return true end

        -- Shared charges (Heartbreak/Bloodletter/Rain of Death): spend freely
        -- outside burst. Holding is limited to a short window before burst and
        -- never applies under Mage's Ballad, whose Repertoire procs refill
        -- charges faster than they can be pooled. Cooldown fields on live
        -- clients do not describe charge counts, so no near-cap heuristic.
    end
    return false
end

-- One decision pulse. `viaACR` is true when ACR's Cast() callback drives the
-- engine; ACR's Enabled toggle is then the master switch instead of
-- config.enabled. Returns true when an action request was issued.
function E.Step(viaACR)
    local c, s = E.config, E.state
    if not c then return false end
    if not viaACR and not c.enabled then s.lastDecision = "Disabled" return false end
    local ticks = now()
    if ticks - s.lastPulse < c.pulseMs then return false end
    s.lastPulse = ticks

    if not Player or not Player.alive or Player.job ~= D.BardJobID then s.lastDecision = "Requires Bard" return false end
    if type(MIsLoading) == "function" and MIsLoading() then return false end
    if type(MIsLocked) == "function" and MIsLocked() then return false end
    if type(MIsCasting) == "function" and MIsCasting() then return false end
    if c.requireCombat and not Player.incombat then
        if s.sampleTargetID ~= 0 then E.ResetCombat("Waiting for combat") end
        return false
    end
    local target = E.GetTarget()
    if not target then s.lastDecision = "No valid target" return false end
    if tonumber(target.distance2d) and target.distance2d > 25 then s.lastDecision = "Target out of range" return false end
    -- Live clients report target.los == false on a striking dummy in plain
    -- view, so this check is opt-in and also accepts the los2 field.
    if c.requireLOS and target.los == false and target.los2 ~= true then s.lastDecision = "Target not in line of sight" return false end
    if ActionList and type(ActionList.IsCasting) == "function" and ActionList:IsCasting() then return false end

    E.ObserveLastCast()
    E.UpdateCharges()
    E.UpdateTTK(target, ticks)
    s.enemyCount = E.CountEnemiesNear(target)
    local ctx = E.BuildContext(target)

    -- When the GCD is available, it always wins. This encodes the strongest
    -- empirical finding: top players gained GCDs, not extra total button presses.
    -- IsReady does not reflect the recast on live clients, so the GCD timer is
    -- read from cd/cdmax the same way the bot's SkillManager does.
    local gcdRemaining = E.GCDRemaining(target)
    s.gcdRemaining = gcdRemaining
    if c.debug and ticks - (s.lastDebugAt or 0) >= 1000 and type(d) == "function" then
        s.lastDebugAt = ticks
        local bs, ea, wm = action(A.BurstShot), action(A.HeartbreakShot), action(A.WanderersMinuet)
        local function f(ac) if not ac then return "nil" end
            return string.format("cd=%s cdmax=%s isoncd=%s isready=%s IsReady=%s recast=%s",
                tostring(ac.cd), tostring(ac.cdmax), tostring(ac.isoncd), tostring(ac.isready),
                tostring(select(2, pcall(function() return ac:IsReady(target.id) end))), tostring(ac.recasttime)) end
        d(string.format("[CielBard] charges=" .. tostring(s.charges) .. " gcdRem=%.2f weaves=%d | BurstShot %s | Heartbreak %s | WM %s | lastcast=%s since=%s",
            gcdRemaining, s.weavesSinceGCD, f(bs), f(ea), f(wm),
            tostring(Player.castinginfo and Player.castinginfo.lastcastid), tostring(Player.castinginfo and Player.castinginfo.timesincecast)))
    end
    local gcdReady = gcdRemaining <= (tonumber(c.gcdLeadSeconds) or 0.05)
    local mode = c.advancedEnabled and c.executionMode or "FULL"
    if gcdReady then
        if mode == "OGCD_ONLY" then return E.TryOGCD(ctx) == true end
        if E.TryGCD(ctx) then return true end
        if mode ~= "GCD_ONLY" and gcdRemaining > (tonumber(c.gcdLeadSeconds) or 0.05) then return E.TryOGCD(ctx) == true end
        return false
    elseif mode ~= "GCD_ONLY" then
        -- Clip guard: only weave when the remaining GCD covers an animation lock.
        if gcdRemaining < (tonumber(c.weaveMinGcdRemaining) or 0.65) then
            s.lastDecision = "Waiting for GCD (" .. string.format("%.2f", gcdRemaining) .. "s)"
            return false
        end
        return E.TryOGCD(ctx) == true
    end
    return false
end

-- Seconds until the GCD is available, taken from the GCD filler's cooldown.
function E.GCDRemaining(target)
    local best = nil
    for _, id in ipairs({ A.BurstShot, A.HeavyShot }) do
        local ac = action(id)
        if ac and tonumber(ac.cdmax) and tonumber(ac.cd) then
            local remaining = math.max(0, ac.cdmax - ac.cd)
            best = best and math.min(best, remaining) or remaining
        end
    end
    if best ~= nil then return best end
    -- No cooldown fields: fall back to readiness only.
    if ready(A.BurstShot, target and target.id) or ready(A.HeavyShot, target and target.id) then return 0 end
    return 999
end

function E.OnUpdate()
    return E.Step(false)
end
