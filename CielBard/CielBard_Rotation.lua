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
    if castID == A.RagingStrikes then
        s.ragingAt = now()
        s.gcdsSinceRaging = 0
        s.battleVoiceAt = 0
        s.radiantFinaleAt = 0
    elseif castID == A.BattleVoice then
        s.battleVoiceAt = now()
    elseif castID == A.RadiantFinale then
        s.radiantFinaleAt = now()
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
        return true
    end
    return false
end

function E.BuildContext(target)
    local s, c = E.state, E.config
    local song, songRemaining = E.GetSong()
    s.currentSong, s.songRemaining = song, songRemaining
    local storm, caustic = E.GetDotState(target)
    local raging = action(A.RagingStrikes)
    local nextBurst = ready(A.RagingStrikes, Player.id) and 0 or cooldownSeconds(raging)
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
        terminal = ttk <= c.terminalTTK,
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
        ttkBand = band,
        soulVoice = E.GetSoulVoice(),
        repertoire = E.GetRepertoire(),
    }
end

function E.TrySong(ctx)
    if ctx.song == "NONE" then
        return E.TryCast(A.WanderersMinuet, ctx.target, "Start Wanderer's Minuet")
    elseif ctx.song == "WM" and ctx.songRemaining <= E.config.wmSwapRemaining then
        return E.TryCast(A.MagesBallad, ctx.target, "WM -> MB at empirical timing")
    elseif ctx.song == "MB" and ctx.songRemaining <= E.config.mbSwapRemaining then
        return E.TryCast(A.ArmysPaeon, ctx.target, "MB -> AP at empirical timing")
    elseif ctx.song == "AP" and ctx.songRemaining <= E.config.apSwapRemaining then
        return E.TryCast(A.WanderersMinuet, ctx.target, "Clip AP -> WM for 2m alignment")
    end
    return false
end

function E.TryGCD(ctx)
    local target, c = ctx.target, E.config

    -- Always establish both DoTs on the primary target when it will live.
    if ctx.ttk > c.dotMinimumTTK then
        if ctx.storm <= 0.2 and E.TryCast(A.Stormbite, target, "Apply Stormbite") then return true end
        if ctx.caustic <= 0.2 and E.TryCast(A.CausticBite, target, "Apply Caustic Bite") then return true end
    end

    -- Transformed/proc actions are identified by MMOMinion's IsReady state.
    if ready(A.BlastArrow, target.id) and E.TryCast(A.BlastArrow, target, "Consume Blast Arrow") then return true end
    if ready(A.ResonantArrow, target.id) and E.TryCast(A.ResonantArrow, target, "Consume Resonant Arrow") then return true end
    if ready(A.RadiantEncore, target.id) and (ctx.burstActive or ctx.terminal) and
        E.TryCast(A.RadiantEncore, target, "Radiant Encore in buffs") then return true end

    local apexThreshold = c.apexOffcycleGauge
    if ctx.burstActive then apexThreshold = c.apexBurstGauge end
    if ctx.terminal then apexThreshold = 20 end
    local shouldApex = ctx.soulVoice >= apexThreshold
    if not ctx.burstActive and not ctx.terminal and ctx.nextBurst <= c.apexHoldForBurstSeconds and ctx.soulVoice < 95 then
        shouldApex = false
    end
    if shouldApex and E.TryCast(A.ApexArrow, target, "Apex Arrow at " .. tostring(ctx.soulVoice) .. " gauge") then return true end

    -- Snapshot late in buffs only when enough lifetime remains; otherwise use
    -- the ordinary near-expiration refresh.
    if c.snapshotIronJaws and ctx.burstActive and ctx.burstElapsed >= 15 and ctx.ttk > c.dotMinimumTTK and
        math.min(ctx.storm, ctx.caustic) < 22 and
        E.TryCast(A.IronJaws, target, "Late-buff Iron Jaws snapshot") then return true end
    if ctx.ttk > c.dotMinimumTTK and math.min(ctx.storm, ctx.caustic) <= c.dotRefreshSeconds and
        E.TryCast(A.IronJaws, target, "Refresh both DoTs") then return true end

    if ready(A.RadiantEncore, target.id) and E.TryCast(A.RadiantEncore, target, "Consume Radiant Encore") then return true end
    if ready(A.RefulgentArrow, target.id) and E.TryCast(A.RefulgentArrow, target, "Consume Refulgent Arrow") then return true end

    if ctx.aoe then
        if ready(A.Shadowbite, target.id) and E.TryCast(A.Shadowbite, target, "Shadowbite cleave") then return true end
        if E.TryCast(A.Ladonsbite, target, "Ladonsbite cleave") then return true end
    end
    return E.TryCast(A.BurstShot, target, "Burst Shot filler")
end

function E.TryOGCD(ctx)
    local s, c, target = E.state, E.config, ctx.target
    if s.weavesSinceGCD >= c.maxWeaves then return false end

    if E.TrySong(ctx) then return true end

    -- Start two-minute burst only after both DoTs exist and Wanderer's is active.
    if ctx.nextBurst <= 0.1 and (ctx.song == "WM" or ctx.terminal or ctx.idealFinish) and
        (ctx.terminal or math.min(ctx.storm, ctx.caustic) > 5) and
        E.TryCast(A.RagingStrikes, target, "Begin two-minute burst") then return true end

    if ctx.burstActive then
        -- The standard opener uses one filler weave after Raging, then places
        -- Battle Voice + Radiant Finale after the following GCD.
        if s.gcdsSinceRaging == 0 then
            local chargeAction = ctx.aoe and A.RainOfDeath or A.HeartbreakShot
            if E.TryCast(chargeAction, target, "Pre-party-buff charge weave") then return true end
            return false
        end
        if E.TryCast(A.BattleVoice, target, "Battle Voice") then return true end
        if E.TryCast(A.RadiantFinale, target, "Radiant Finale") then return true end

        -- Consume an existing Refulgent before Barrage; the GCD priority does
        -- that naturally, so Barrage waits while Refulgent is currently ready.
        if not highlighted(A.RefulgentArrow) and E.TryCast(A.Barrage, target, "Barrage after clearing proc") then return true end

        local repertoire = ctx.repertoire
        if (repertoire >= 3 or (ctx.song == "WM" and ctx.songRemaining <= 3) or ctx.terminal) and
            E.TryCast(A.PitchPerfect, target, "Pitch Perfect stack dump") then return true end
        if E.TryCast(A.EmpyrealArrow, target, "Empyreal Arrow inside buffs") then return true end
        if E.TryCast(A.Sidewinder, target, "Sidewinder inside buffs") then return true end
        local chargeAction = ctx.aoe and A.RainOfDeath or A.HeartbreakShot
        if E.TryCast(chargeAction, target, ctx.aoe and "Rain of Death cleave" or "Heartbreak Shot in buffs") then return true end
    else
        if (ctx.song == "WM" and (ctx.repertoire >= 3 or ctx.songRemaining <= 3)) and
            E.TryCast(A.PitchPerfect, target, "Pitch Perfect before overcap/song end") then return true end

        -- Hold a ready Empyreal Arrow only for the last few seconds before the
        -- burst, allowing two uses inside the upcoming 20-second window.
        if (ctx.nextBurst > 5 or ctx.terminal) and E.TryCast(A.EmpyrealArrow, target, "Empyreal Arrow on cooldown") then return true end

        local chargeAction = ctx.aoe and A.RainOfDeath or A.HeartbreakShot
        local charge = action(chargeAction)
        if (ctx.nextBurst > 15 or ctx.terminal) and cooldownSeconds(charge) <= 1.5 and
            E.TryCast(chargeAction, target, ctx.aoe and "Rain of Death near charge cap" or "Heartbreak near charge cap") then return true end
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
    if ActionList and type(ActionList.IsCasting) == "function" and ActionList:IsCasting() then return end

    E.ObserveLastCast()
    E.UpdateTTK(target, ticks)
    s.enemyCount = E.CountEnemiesNear(target)
    local ctx = E.BuildContext(target)

    -- When the GCD is available, it always wins. This encodes the strongest
    -- empirical finding: top players gained GCDs, not extra total button presses.
    if ready(A.BurstShot, target.id) or ready(A.Stormbite, target.id) then
        E.TryGCD(ctx)
    else
        E.TryOGCD(ctx)
    end
end
