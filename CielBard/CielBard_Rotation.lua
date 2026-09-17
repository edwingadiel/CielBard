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
    ttk = nil,
    ttkConfidence = 0,
    ttkBand = "LEARNING",
    hpSamples = {},
    sampleTargetID = 0,
    lastSampleAt = 0,
    enemyCount = 1,
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

function E.GetConfigurationWarnings()
    local warnings = {}
    local c = E.config or D.Defaults
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
    end
end

local function nextBurstSeconds()
    if not majorBurstEnabled() then return 999, false end
    local best = 999
    local candidates = {
        { "RagingStrikes", A.RagingStrikes },
        { "BattleVoice", A.BattleVoice },
        { "RadiantFinale", A.RadiantFinale },
    }
    for _, candidate in ipairs(candidates) do
        if E.AbilityEnabled(candidate[1]) then
            if ready(candidate[2], Player.id) then return 0, true end
            best = math.min(best, cooldownSeconds(action(candidate[2])))
        end
    end
    return best, true
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
    s.ttk = nil
    s.ttkConfidence = 0
    s.ttkBand = "LEARNING"
    s.hpSamples = {}
    s.sampleTargetID = 0
    s.lastSampleAt = 0
    s.enemyCount = 1
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
    if songKey then
        s.currentSong = songKey
        s.songStartedAt = now()
    end
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
        if songKey then
            s.currentSong = songKey
            s.songStartedAt = ticks
        end
        if actionID == A.RagingStrikes or actionID == A.BattleVoice or actionID == A.RadiantFinale then
            startOrUpdateBurst(actionID, ticks)
        end
        return true
    end
    return false
end

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
    return {
        target = target,
        ttk = ttk,
        terminal = c.terminalDumping and ttk <= c.terminalTTK,
        idealFinish = ttk > c.terminalTTK and ttk <= c.idealKillMax,
        enemies = s.enemyCount,
        aoe = c.useAOE and s.enemyCount >= c.minAOETargets,
        storm = storm,
        caustic = caustic,
        song = song,
        songRemaining = songRemaining,
        nextBurst = nextBurst,
        burstElapsed = burstElapsed,
        burstActive = burstActive,
        burstConfigured = burstConfigured,
        dotsReady = (not E.AbilityEnabled("Stormbite") or storm > 5) and
            (not E.AbilityEnabled("CausticBite") or caustic > 5),
        ttkBand = band,
        soulVoice = E.GetSoulVoice(),
        repertoire = E.GetRepertoire(),
    }
end

function E.TrySong(ctx)
    if not E.config.automaticSongCycle then return false end
    local nextKey = nextEnabledSong(ctx.song)
    if not nextKey then return false end
    if ctx.song == "NONE" then
        return E.TryCast(D.Songs[nextKey].id, ctx.target, "Start " .. D.Songs[nextKey].name)
    end
    local thresholds = {
        WM = E.config.wmSwapRemaining,
        MB = E.config.mbSwapRemaining,
        AP = E.config.apSwapRemaining,
    }
    local shouldSwap = not songEnabled(ctx.song) or ctx.songRemaining <= (thresholds[ctx.song] or 1)
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
    local ironJawsEnabled = E.AbilityEnabled("IronJaws") and
        E.AbilityEnabled("Stormbite") and E.AbilityEnabled("CausticBite")
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
    if E.AbilityEnabled("RefulgentArrow") and ready(A.RefulgentArrow, target.id) and
        E.TryCast(A.RefulgentArrow, target, "Consume Refulgent Arrow") then return true end

    if ctx.aoe then
        if E.AbilityEnabled("Shadowbite") and ready(A.Shadowbite, target.id) and
            E.TryCast(A.Shadowbite, target, "Shadowbite cleave") then return true end
        if E.AbilityEnabled("Ladonsbite") and
            (E.TryCast(A.Ladonsbite, target, "Ladonsbite cleave") or
             E.TryCast(A.QuickNock, target, "Quick Nock fallback")) then return true end
    end
    -- Non-configurable emergency filler: custom settings must never stall the
    -- GCD merely because every optional action was switched Off.
    if E.TryCast(A.BurstShot, target, "Burst Shot emergency filler") then return true end
    return E.TryCast(A.HeavyShot, target, "Heavy Shot level-sync fallback")
end

local function chargeActions(ctx)
    local result = {}
    if ctx.aoe and E.AbilityEnabled("RainOfDeath") then table.insert(result, A.RainOfDeath) end
    if E.AbilityEnabled("HeartbreakShot") then table.insert(result, A.HeartbreakShot) end
    if E.AbilityEnabled("Bloodletter") then table.insert(result, A.Bloodletter) end
    return result
end

local function tryCharge(ctx, decision)
    for _, actionID in ipairs(chargeActions(ctx)) do
        if E.TryCast(actionID, ctx.target, decision) then return true end
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

local function tryStartBurst(ctx)
    if E.AbilityEnabled("RagingStrikes") and
        E.TryCast(A.RagingStrikes, ctx.target, "Begin burst with Raging Strikes") then return true end
    if E.AbilityEnabled("BattleVoice") and
        E.TryCast(A.BattleVoice, ctx.target, "Begin burst with Battle Voice") then return true end
    if E.AbilityEnabled("RadiantFinale") and
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
    if ctx.burstConfigured and ctx.nextBurst <= 0.1 and songReady and
        (ctx.terminal or ctx.dotsReady) and tryStartBurst(ctx) then return true end

    if ctx.burstActive then
        -- Preserve the optimized filler weave after Raging when an enabled
        -- charge spender exists; otherwise continue directly to party buffs.
        if s.gcdsSinceRaging == 0 and E.AbilityEnabled("RagingStrikes") and
            tryCharge(ctx, "Pre-party-buff charge weave") then return true end

        if E.AbilityEnabled("BattleVoice") and
            E.TryCast(A.BattleVoice, target, "Battle Voice") then return true end
        if E.AbilityEnabled("RadiantFinale") and
            E.TryCast(A.RadiantFinale, target, "Radiant Finale") then return true end

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
        if E.AbilityEnabled("PitchPerfect") and ctx.song == "WM" and
            (ctx.repertoire >= 3 or ctx.songRemaining <= 3) and
            E.TryCast(A.PitchPerfect, target, "Pitch Perfect before overcap/song end") then return true end

        local holdEmpyreal = c.resourcePooling and ctx.burstConfigured and ctx.nextBurst <= 5 and not ctx.terminal
        if E.AbilityEnabled("EmpyrealArrow") and not holdEmpyreal and
            E.TryCast(A.EmpyrealArrow, target, "Empyreal Arrow on cooldown") then return true end

        local holdCharge = c.resourcePooling and ctx.burstConfigured and ctx.nextBurst <= 15 and not ctx.terminal
        if not holdCharge and chargeCooldown(ctx) <= 1.5 and
            tryCharge(ctx, ctx.aoe and "AoE charge near cap" or "Single-target charge near cap") then return true end
    end
    return false
end

function E.OnUpdate()
    local c, s = E.config, E.state
    if not c or not c.enabled then s.lastDecision = "Disabled" return end
    local ticks = now()
    if ticks - s.lastPulse < c.pulseMs then return end
    s.lastPulse = ticks

    if not Player or not Player.alive or Player.job ~= D.BardJobID then s.lastDecision = "Requires Bard" return end
    if type(MIsLoading) == "function" and MIsLoading() then return end
    if type(MIsLocked) == "function" and MIsLocked() then return end
    if type(MIsCasting) == "function" and MIsCasting() then return end
    if c.requireCombat and not Player.incombat then
        if s.sampleTargetID ~= 0 then E.ResetCombat("Waiting for combat") end
        return
    end
    local target = E.GetTarget()
    if not target then s.lastDecision = "No valid target" return end
    if tonumber(target.distance2d) and target.distance2d > 25 then s.lastDecision = "Target out of range" return end
    if c.requireLOS and target.los == false then s.lastDecision = "Target not in line of sight" return end
    if ActionList and type(ActionList.IsCasting) == "function" and ActionList:IsCasting() then return end

    E.ObserveLastCast()
    E.UpdateTTK(target, ticks)
    s.enemyCount = E.CountEnemiesNear(target)
    local ctx = E.BuildContext(target)

    -- When the GCD is available, it always wins. This encodes the strongest
    -- empirical finding: top players gained GCDs, not extra total button presses.
    local gcdReady = ready(A.BurstShot, target.id) or ready(A.Stormbite, target.id) or
        ready(A.HeavyShot, target.id)
    local mode = c.advancedEnabled and c.executionMode or "FULL"
    if gcdReady then
        if mode == "OGCD_ONLY" then E.TryOGCD(ctx) else E.TryGCD(ctx) end
    elseif mode ~= "GCD_ONLY" then
        E.TryOGCD(ctx)
    end
end
