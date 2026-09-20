CielDancerEngine = CielDancerEngine or {}

local E = CielDancerEngine
local D = CielDancerData
local A = D.Actions
local ST = D.Statuses

E.config = nil
E.state = {
    lastPulse = 0,
    lastRequestAt = 0,
    lastRequestID = 0,
    lastObservedCastID = 0,
    lastObservedTimeSince = 999999,
    weavesSinceGCD = 0,
    burstAt = 0,
    lastGCDID = 0,
    lastComboID = 0,
    lastComboAt = 0,
    procs = {},
    pendingActionID = 0,
    pendingTargetID = 0,
    pendingAt = 0,
    pendingWasOnCd = false,
    pendingCd = nil,
    lastActionName = "Idle",
    lastDecision = "Disabled",
    ttk = nil,
    ttkConfidence = 0,
    ttkBand = "LEARNING",
    hpSamples = {},
    sampleTargetID = 0,
    lastSampleAt = 0,
    enemyCount = 1,
    potionActionID = 0,
    potionName = "None",
    potionScanAt = 0,
    potionItem = nil,
    potionAction = nil,
    potionUsedAt = 0,
    prepullArmedUntil = 0,
    esprit = 0,
    feathers = 0,
    dancing = nil,
    burstRemaining = 0,
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
-- has its own nearby-target count so shape differences can be tuned.
function E.AoETargetsFor(key)
    local c = E.config or D.Defaults
    local thresholds = c.aoeTargets or {}
    return tonumber(thresholds[key]) or tonumber(D.AoEDefaults[key]) or 3
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

-- Locally tracked statuses -------------------------------------------------------
-- The dancing statuses, Technical Finish and Devilment are read from the live
-- status list first. Builds that expose a status a few pulses late (or not at
-- all) fall back to a timer started by the accepted or observed cast that
-- grants it. Once the live status has been seen it is authoritative, and the
-- cast that ends it clears the timer outright.

local function noteProc(key, ticks)
    E.state.procs[key] = { at = ticks or now(), seen = false }
end

local function clearProc(key)
    E.state.procs[key] = nil
end

local function procActive(key, statusID, windowSeconds)
    local s = E.state
    local proc = s.procs[key]
    local remaining = Player and buffRemaining(Player, statusID, Player.id) or 0
    if remaining > 0 then
        if proc then proc.seen = true end
        return true, remaining
    end
    if not proc then return false, 0 end
    if proc.seen then
        s.procs[key] = nil
        return false, 0
    end
    local left = windowSeconds - ((now() - proc.at) / 1000)
    if left > 0 then return true, left end
    s.procs[key] = nil
    return false, 0
end

-- Dancing ----------------------------------------------------------------------------
-- MMOMinion exposes the Dancer gauge as a numeric array. The layout below is
-- the one FFXIVMinion's bundled Dancer profile reads: slot 1 Fourfold Feathers,
-- slot 2 Esprit, slots 3-6 the step sequence (1 Emboite, 2 Entrechat, 3 Jete,
-- 4 Pirouette; 0 when not dancing) and slot 7 the number of steps completed.
-- Every index is editable in the window.

function E.GetFeathers()
    return gauge(E.config.featherGaugeIndex)
end

-- Esprit drives thresholds above 50, so a miscalibrated index must not silence
-- Saber Dance: when it is ready the gauge holds at least 50.
local function espritAtLeast50(targetID)
    return ready(A.SaberDance, targetID) or ready(A.DanceOfTheDawn, targetID)
end

function E.GetEsprit(targetID)
    local esprit = gauge(E.config.espritGaugeIndex)
    if esprit < 50 and targetID and espritAtLeast50(targetID) then return 50 end
    return esprit
end

-- "STANDARD", "TECHNICAL" or nil. The status is the live signal; a step cast the
-- engine has just had accepted covers the pulses before the status shows.
function E.Dancing()
    if not Player then return nil end
    if buffRemaining(Player, ST.TechnicalStep, Player.id) > 0 then return "TECHNICAL" end
    if buffRemaining(Player, ST.StandardStep, Player.id) > 0 then return "STANDARD" end
    if procActive("TechnicalStep", ST.TechnicalStep, 15) then return "TECHNICAL" end
    if procActive("StandardStep", ST.StandardStep, 15) then return "STANDARD" end
    return nil
end

local STEP_ACTIONS = { "Emboite", "Entrechat", "Jete", "Pirouette" }

-- The next step to press, its name, and how many steps are already done.
-- Source order: the gauge's step sequence, then the hotbar highlight the game
-- puts on the correct step.
function E.NextStep(kind)
    local c = E.config
    local completed = gauge(c.stepsDoneGaugeIndex)
    local needed = kind == "TECHNICAL" and 4 or 2
    if completed >= needed then return nil, nil, completed, needed end
    local value = gauge((tonumber(c.stepGaugeIndex) or 3) + completed)
    if value >= 1 and value <= 4 then return A[STEP_ACTIONS[value]], STEP_ACTIONS[value], completed, needed end
    for _, name in ipairs(STEP_ACTIONS) do
        if highlighted(A[name]) then return A[name], name, completed, needed end
    end
    return nil, nil, completed, needed
end

local FINISHES = {
    STANDARD = { "DoubleStandardFinish", "SingleStandardFinish", "StandardFinish" },
    TECHNICAL = { "QuadrupleTechnicalFinish", "TripleTechnicalFinish", "DoubleTechnicalFinish",
        "SingleTechnicalFinish", "TechnicalFinish" },
}

local function withinSelfRadius(target, radius)
    local distance = target and tonumber(target.distance2d)
    return not distance or distance <= radius
end

-- One pulse of a dance. Always returns true while dancing: nothing else may be
-- pressed, and the finish is a 15 yalm circle around the player, so it is held
-- for a target that is too far away until the dance is about to lapse.
function E.TryDance(ctx, kind)
    local s, target = E.state, ctx.target
    local stepID, stepName, completed, needed = E.NextStep(kind)
    if stepID then
        if not E.TryCast(stepID, target, stepName .. " (" .. tostring(completed + 1) .. "/" .. tostring(needed) .. ")") then
            s.lastDecision = "Dancing: waiting to press " .. stepName
        end
        return true
    end
    local statusID = kind == "TECHNICAL" and ST.TechnicalStep or ST.StandardStep
    local remaining = buffRemaining(Player, statusID, Player.id)
    if completed < needed and (remaining <= 0 or remaining > 2) then
        s.lastDecision = "Dancing: step sequence unreadable (check the gauge indexes)"
        return true
    end
    -- Out of combat the finish is the pull, so it waits for the pull signal.
    if not Player.incombat and not ctx.pullNow then
        s.lastDecision = "Dance ready: holding the finish for the pull"
        return true
    end
    if not withinSelfRadius(target, D.FinishRadius) and remaining > 2 then
        s.lastDecision = "Dance ready: move within " .. tostring(D.FinishRadius) .. " yalms to finish"
        return true
    end
    for _, key in ipairs(FINISHES[kind]) do
        if E.TryCast(A[key], target, (kind == "TECHNICAL" and "Technical Finish" or "Standard Finish")) then return true end
    end
    s.lastDecision = "Dancing: waiting for the finish"
    return true
end

-- Dance partner ---------------------------------------------------------------------
-- Closed Position and Dance Partner are permanent statuses, which clients may
-- report with a zero duration, so they are tested for presence only.

local function hasBuff(entity, statusID, ownerID)
    if not entity or not valid(entity.buffs) then return false end
    for _, buff in pairs(entity.buffs) do
        if buff.id == statusID and (not ownerID or buff.ownerid == ownerID) then return true end
    end
    return false
end

-- The best eligible party member and the dancer's current partner, if any.
function E.FindPartners()
    if not EntityList or not Player then return nil, nil end
    local list = EntityList("myparty,alive,maxdistance2d=" .. tostring(D.PartnerRange))
    if not valid(list) then return nil, nil end
    local best, current = nil, nil
    for _, entity in pairs(list) do
        local rank = entity and entity.id ~= Player.id and entity.job and D.PartnerRank[tonumber(entity.job)]
        if rank and entity.alive ~= false then
            if hasBuff(entity, ST.DancePartner, Player.id) then current = entity end
            local bestRank = best and D.PartnerRank[tonumber(best.job)]
            if not best or rank < bestRank or (rank == bestRank and entity.id < best.id) then best = entity end
        end
    end
    return best, current
end

function E.HasPartner()
    if hasBuff(Player, ST.ClosedPosition, Player.id) or hasBuff(Player, ST.ClosedPosition) then return true end
    local _, current = E.FindPartners()
    return current ~= nil
end

-- Returns true when a request went out.
function E.TryPartner()
    local c, s = E.config, E.state
    if not c.autoPartner or E.Dancing() then return false end
    local ticks = now()
    if ticks - (s.partnerCheckedAt or 0) < 1000 then return false end
    s.partnerCheckedAt = ticks
    local best, current = E.FindPartners()
    s.partySize = 1
    s.partnerName = current and (current.name or tostring(current.id)) or "None"
    if not best then return false end
    s.partySize = 2
    local partnered = current ~= nil or hasBuff(Player, ST.ClosedPosition)
    if not partnered then
        if ticks - (s.partnerRequestedAt or 0) < 5000 then return false end
        if E.TryCast(A.ClosedPosition, best, "Closed Position on " .. tostring(best.name or best.id)) then
            s.partnerRequestedAt = ticks
            return true
        end
        return false
    end
    -- A better partner has come into range: swap, but never mid-fight.
    if current and c.partnerUpgradeOutOfCombat and not Player.incombat and
        D.PartnerRank[tonumber(best.job)] < D.PartnerRank[tonumber(current.job)] and
        ticks - (s.partnerRequestedAt or 0) >= 5000 and
        E.TryCast(A.Ending, Player, "Ending to take a better dance partner") then
        s.partnerRequestedAt = 0
        return true
    end
    return false
end

-- Configuration warnings -------------------------------------------------------

function E.GetConfigurationWarnings()
    local warnings = {}
    local c = E.config or D.Defaults
    if c.usePotion and not E.PotionAvailable() then
        table.insert(warnings, "Potion use is On but no Gemdraught of Dexterity was found in inventory.")
    end
    if Player and c.warnNoPartner and (E.state.partySize or 1) > 1 and not E.HasPartner() then
        table.insert(warnings, c.autoPartner and "No dance partner yet: waiting for Closed Position to be ready and a party member in range."
            or "No dance partner: use Closed Position on a party member, or switch automatic partner on.")
    end
    if not c.advancedEnabled then return warnings end
    local enabled = E.AbilityEnabled
    if enabled("Devilment") and not enabled("TechnicalStep") then
        table.insert(warnings, "Devilment is used on cooldown while Technical Step is Off.")
    end
    if enabled("Tillana") and not enabled("TechnicalStep") then
        table.insert(warnings, "Tillana cannot normally be generated while Technical Step is Off.")
    end
    if enabled("FinishingMove") and not enabled("Flourish") then
        table.insert(warnings, "Finishing Move cannot normally be generated while Flourish is Off.")
    end
    if enabled("LastDance") and not enabled("StandardStep") and not enabled("FinishingMove") then
        table.insert(warnings, "Last Dance cannot normally be generated while Standard Step and Finishing Move are Off.")
    end
    if enabled("StarfallDance") and not enabled("Devilment") then
        table.insert(warnings, "Starfall Dance cannot normally be generated while Devilment is Off.")
    end
    if c.executionMode == "OGCD_ONLY" then
        table.insert(warnings, "oGCD-only mode expects you or another system to keep the GCD rolling.")
    end
    return warnings
end

-- Burst ----------------------------------------------------------------------------

local function burstAnchorEnabled()
    return E.AbilityEnabled("TechnicalStep") or E.AbilityEnabled("Devilment")
end

local function noteBurst(ticks)
    local s = E.state
    if s.burstAt == 0 or ticks - s.burstAt > 20500 then s.burstAt = ticks end
end

-- Seconds until the next two-minute burst: Technical Step's cooldown, or
-- Devilment's when Technical Step is Off.
local function nextBurstSeconds()
    if not burstAnchorEnabled() then return 999, false end
    local anchor = E.AbilityEnabled("TechnicalStep") and A.TechnicalStep or A.Devilment
    local remaining = cooldownSeconds(action(anchor))
    if remaining >= 999 then remaining = 0 end -- no cooldown data: treat as ready
    return remaining, true
end

-- Smart hold --------------------------------------------------------------------------
-- One switch shared by all Ciel modules (CielShared.hold). Fights often need
-- the burst delayed: the boss is about to leave, the party is waiting on a
-- mechanic. Holding stops the two-minute burst from *starting* and keeps the
-- potion; it never stops the GCD, never lets a cooldown weaponskill, a DoT or a
-- proc go to waste, and spends pooled resources only to stay under their caps.
-- A burst whose buffs are already running is finished, not abandoned.

function E.HoldActive()
    local shared = CielShared
    if not shared or not shared.hold then return false end
    local limit = tonumber((E.config or D.Defaults).holdAutoReleaseSeconds) or 0
    if limit > 0 and (now() - (shared.holdAt or 0)) / 1000 >= limit then
        shared.hold = false
        return false
    end
    return true
end

function E.SetHold(value)
    CielShared.hold = value == true
    CielShared.holdAt = now()
end

function E.ToggleHold()
    E.SetHold(not E.HoldActive())
end

-- Seconds the hold has been on, for the window.
function E.HoldSeconds()
    if not E.HoldActive() then return 0 end
    return (now() - (CielShared.holdAt or 0)) / 1000
end

-- A wipe or a kill ends the reason for holding.
local function trackCombatForHold()
    local s, c = E.state, E.config
    if Player.incombat then
        s.wasInCombat = true
    elseif s.wasInCombat then
        s.wasInCombat = false
        if c.holdClearsOnCombatEnd ~= false and CielShared then CielShared.hold = false end
    end
end

function E.Init(config)
    E.config = config
    E.ResetCombat("Initialized")
end

function E.ResetCombat(reason)
    local s = E.state
    s.weavesSinceGCD = 0
    s.burstAt = 0
    s.lastGCDID = 0
    s.procs = {}
    s.pendingActionID = 0
    s.pendingTargetID = 0
    s.pendingAt = 0
    s.pendingWasOnCd = false
    s.pendingCd = nil
    s.ttk = nil
    s.ttkConfidence = 0
    s.ttkBand = "LEARNING"
    s.hpSamples = {}
    s.sampleTargetID = 0
    s.lastSampleAt = 0
    s.enemyCount = 1
    s.partnerCheckedAt = 0
    s.partnerRequestedAt = 0
    s.lastDecision = reason or "Reset"
end

function E.GetGauge(index)
    return gauge(index)
end
function E.GetTarget()
    if not Player or type(Player.GetTarget) ~= "function" then return nil end
    local target = Player:GetTarget()
    if not target or not target.id or target.id == 0 then return nil end
    if target.alive == false or target.targetable == false then return nil end
    if target.hp and tonumber(target.hp.current) and target.hp.current <= 0 then return nil end
    return target
end

-- Enemies inside the five-yalm circle around the dancer.
function E.CountEnemiesNear(target)
    if not E.config.useAOE or not target or not target.pos or not EntityList then return 1 end
    local list = EntityList("alive,attackable,maxdistance=30")
    if not valid(list) then return 1 end
    local count = 0
    for _, entity in pairs(list) do
        if entity and entity.targetable ~= false and (tonumber(entity.distance2d) or 99) <= D.CircleRadius then
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

-- Cast bookkeeping -----------------------------------------------------------------

-- Shared by an accepted request and an observed cast.
local function noteCast(actionID, ticks, observed)
    local s = E.state
    if actionID == A.StandardStep then
        noteProc("StandardStep", ticks)
    elseif actionID == A.TechnicalStep then
        noteProc("TechnicalStep", ticks)
    elseif D.StandardFinishIDs[actionID] or actionID == A.FinishingMove then
        clearProc("StandardStep")
        noteProc("StandardFinish", ticks)
    elseif D.TechnicalFinishIDs[actionID] then
        clearProc("TechnicalStep")
        noteBurst(ticks)
        noteProc("TechnicalFinish", ticks)
    elseif actionID == A.Devilment then
        noteBurst(ticks)
        noteProc("Devilment", ticks)
    end
    if D.GCD[actionID] then s.lastGCDID = actionID end
    -- Local combo tracker: only the combo starters and finishers move it; every
    -- other Dancer weaponskill preserves the combo.
    if observed and (actionID == A.Cascade or actionID == A.Windmill or actionID == A.Fountain or
        actionID == A.Bladeshower) then
        s.lastComboID, s.lastComboAt = actionID, ticks
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
    -- A confirmed cast clears the pending-request guard: whatever the client
    -- just executed, it is no longer waiting on the last request.
    s.pendingActionID, s.pendingTargetID, s.pendingAt = 0, 0, 0
    s.pendingWasOnCd, s.pendingCd = false, nil
    -- The potion request already counted itself as a weave.
    if s.potionActionID ~= 0 and castID == s.potionActionID then return end
    local ac = action(castID)
    s.lastActionName = (ac and ac.name) or tostring(castID)

    if D.GCD[castID] then
        s.weavesSinceGCD = 0
    else
        s.weavesSinceGCD = s.weavesSinceGCD + 1
    end
    noteCast(castID, now(), true)
end
-- Pending-request guard ------------------------------------------------------------
-- An accepted request stays "pending" briefly. Live clients can keep
-- reporting an action ready for longer than the request throttle after Cast()
-- returned true, which would let the engine send the same cast several times.
-- Execution is confirmed by the cooldown moving, not by isoncd alone: for a
-- charged action (Double Check, Checkmate, Drill, Reassemble) isoncd is
-- already true at any partial stack, so spending a charge is detected by `cd`
-- rewinding one recast instead.
local function pendingExecuted(actionID)
    local s = E.state
    local ac = action(actionID)
    if not ac then return false end
    if ac.isoncd == true and not s.pendingWasOnCd then return true end
    local cd = tonumber(ac.cd)
    if cd and s.pendingCd and cd < s.pendingCd - 0.05 then return true end
    return false
end

local function pendingUnconfirmed(ticks)
    local s, c = E.state, E.config or D.Defaults
    local window = tonumber(c.requestDedupeMs) or 0
    if window <= 0 or s.pendingActionID == 0 then return false end
    if ticks - s.pendingAt >= window then return false end
    if pendingExecuted(s.pendingActionID) then return false end
    return true
end

-- The hold is tier-wide, not per-action: FFXIV's action queue takes the most
-- recent command inside its window, so falling through the priority chain
-- could replace a 600-potency tool with a combo filler sent 60 ms later.
function E.PendingGCD(ticks)
    return pendingUnconfirmed(ticks) and D.GCD[E.state.pendingActionID] == true
end

function E.PendingOGCD(ticks)
    return pendingUnconfirmed(ticks) and D.GCD[E.state.pendingActionID] ~= true
end

local function pendingSuppressed(actionID, targetID, ticks)
    local s = E.state
    if s.pendingActionID ~= actionID or s.pendingTargetID ~= targetID then return false end
    return pendingUnconfirmed(ticks)
end

function E.TryCast(actionID, target, decision)
    local ticks, s = now(), E.state
    if ticks - s.lastRequestAt < E.config.requestThrottleMs then return false end
    local targetID = D.SelfTarget[actionID] and Player.id or (target and target.id)
    if not targetID or pendingSuppressed(actionID, targetID, ticks) then return false end
    if not ready(actionID, targetID) then return false end
    local ac = action(actionID)
    local ok, result = pcall(function() return ac:Cast(targetID) end)
    if ok and result then
        s.lastRequestAt = ticks
        s.lastRequestID = actionID
        s.pendingActionID, s.pendingTargetID, s.pendingAt = actionID, targetID, ticks
        s.pendingWasOnCd, s.pendingCd = (ac.isoncd == true), tonumber(ac.cd)
        s.lastDecision = decision or (ac.name or tostring(actionID))
        noteCast(actionID, ticks, false)
        return true
    end
    -- Explicit rejection: drop the guard at once so the next pulse may retry.
    if s.pendingActionID == actionID and s.pendingTargetID == targetID then
        s.pendingActionID, s.pendingTargetID, s.pendingAt = 0, 0, 0
        s.pendingWasOnCd, s.pendingCd = false, nil
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

-- Context ------------------------------------------------------------------

function E.BuildContext(target, gcdRemaining)
    local s, c = E.state, E.config
    local nextBurst, burstConfigured = nextBurstSeconds()
    local technical = select(2, procActive("TechnicalFinish", ST.TechnicalFinish, 20)) or 0
    local devilment = select(2, procActive("Devilment", ST.Devilment, 20)) or 0
    local burstActive = technical > 0 or devilment > 0
    local burstElapsed = s.burstAt > 0 and (now() - s.burstAt) / 1000 or 999
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

    local esprit = E.GetEsprit(target and target.id)
    s.esprit, s.feathers = esprit, E.GetFeathers()
    s.dancing = E.Dancing()
    s.burstRemaining = math.max(technical, devilment)

    return {
        target = target,
        ttk = ttk,
        terminal = c.terminalDumping and ttk <= c.terminalTTK,
        idealFinish = ttk > c.terminalTTK and ttk <= c.idealKillMax,
        enemies = s.enemyCount,
        aoe = c.useAOE and s.enemyCount >= E.MinAoETargets(),
        nextBurst = nextBurst,
        burstConfigured = burstConfigured,
        burstActive = burstActive,
        burstRemaining = s.burstRemaining,
        burstElapsed = burstElapsed,
        ttkBand = band,
        esprit = esprit,
        feathers = s.feathers,
        dancing = s.dancing,
        hold = E.HoldActive() and not burstActive,
        gcdRemaining = gcdRemaining or 0,
        pullNow = Player.incombat or not c.requireCombat,
    }
end

-- Dances ---------------------------------------------------------------------------

local function pooling(ctx, seconds)
    local c = E.config
    return c.resourcePooling and ctx.burstConfigured and not ctx.terminal and not ctx.burstActive and
        ctx.nextBurst <= (tonumber(seconds) or 0)
end

function E.TechnicalStepAllowed(ctx)
    local c = E.config
    if not E.AbilityEnabled("TechnicalStep") or ctx.hold then return false end
    -- The dance is seven seconds of steps; it has to pay for itself.
    if ctx.ttk < (tonumber(c.technicalMinimumTTK) or 0) then return false end
    -- Without a pre-pull the Standard Finish buff is missing at the start of
    -- the fight. Standard Step goes first then: The Balance advises against a
    -- Technical-first opener, and the burst would otherwise run without the
    -- dancer's own 5%.
    if E.AbilityEnabled("StandardStep") and ctx.ttk >= (tonumber(c.standardMinimumTTK) or 0) and
        buffRemaining(Player, ST.StandardFinish, Player.id) <= 0 and not procActive("StandardFinish", ST.StandardFinish, 60) and
        ready(A.StandardStep, Player.id) then
        return false
    end
    return true
end

-- Standard Step and Finishing Move share a 30 s recast. Inside the burst only
-- Finishing Move (one weaponskill) is worth the time. A five-second Standard
-- dance that would still be running when Technical Step comes up is held:
-- Technical alignment matters more (The Balance). One that fits goes out, and
-- top parses routinely finish it right before Technical Step, which is what
-- banks a Last Dance for the burst.
function E.StandardStepAllowed(ctx)
    local c = E.config
    if not E.AbilityEnabled("StandardStep") then return false end
    if ctx.ttk < (tonumber(c.standardMinimumTTK) or 0) then return false end
    if ctx.burstActive then return false end
    if ctx.burstConfigured and not ctx.terminal and E.AbilityEnabled("TechnicalStep") and
        E.TechnicalStepAllowed(ctx) and ctx.nextBurst < (tonumber(c.standardBeforeTechnicalSeconds) or 5) then
        return false
    end
    return true
end

local function expiring(statusID, seconds)
    local remaining = buffRemaining(Player, statusID, Player.id)
    return remaining > 0 and remaining <= seconds
end

-- Last Dance Ready lasts thirty seconds. Outside the burst it is kept when the
-- burst will arrive while it is still up, and spent otherwise.
function E.LastDanceAllowed(ctx)
    if not E.AbilityEnabled("LastDance") then return false end
    if ctx.burstActive or ctx.terminal or not E.config.resourcePooling or not ctx.burstConfigured then return true end
    local remaining = buffRemaining(Player, ST.LastDanceReady, Player.id)
    if remaining <= 0 then return true end -- status unreadable: never hold blind
    -- It has to outlast the wait, the seven-second Technical dance and the two
    -- weaponskills that open the burst ahead of it.
    return remaining < ctx.nextBurst + (tonumber(E.config.lastDanceBurstLeadSeconds) or 15)
end

-- GCD --------------------------------------------------------------------------------

local function espritSpender(ctx, decision)
    local target = ctx.target
    if E.AbilityEnabled("DanceOfTheDawn") and E.TryCast(A.DanceOfTheDawn, target, "Dance of the Dawn") then return true end
    return E.AbilityEnabled("SaberDance") and E.TryCast(A.SaberDance, target, decision)
end

local function tryProcsAndCombo(ctx)
    local target = ctx.target
    if E.AoEAllowed("Bloodshower", ctx) and E.TryCast(A.Bloodshower, target, "Bloodshower proc") then return true end
    if E.AoEAllowed("RisingWindmill", ctx) and E.TryCast(A.RisingWindmill, target, "Rising Windmill proc") then return true end
    if E.AbilityEnabled("Fountainfall") and E.TryCast(A.Fountainfall, target, "Fountainfall proc") then return true end
    if E.AbilityEnabled("ReverseCascade") and E.TryCast(A.ReverseCascade, target, "Reverse Cascade proc") then return true end
    -- The two combos break each other. An open Windmill combo is finished with
    -- Bladeshower; an open Cascade combo is finished with Fountain unless three
    -- or more targets make dropping it for Windmill worthwhile.
    local open = ctx.comboStep == 2 and ctx.comboFrom
    if open == "aoe" and E.AoEAllowed("Bladeshower", ctx) and
        E.TryCast(A.Bladeshower, target, "Bladeshower combo") then return true end
    local windmill = E.AoEAllowed("Windmill", ctx)
    if open == "single" and E.AbilityEnabled("Fountain") and not (windmill and (ctx.enemies or 1) >= 3) and
        E.TryCast(A.Fountain, target, "Fountain combo") then return true end
    if windmill and E.TryCast(A.Windmill, target, "Windmill") then return true end
    -- Non-configurable emergency filler: custom settings must never stall the
    -- GCD merely because every optional action was switched Off.
    return E.TryCast(A.Cascade, target, "Cascade filler")
end

function E.TryGCD(ctx)
    local target, c = ctx.target, E.config

    if E.PendingGCD(now()) then
        E.state.lastDecision = "Waiting for client to confirm last GCD"
        return true
    end

    if ctx.dancing then return E.TryDance(ctx, ctx.dancing) end
    ctx.comboStep, ctx.comboFrom = E.NextComboStep()

    if E.TechnicalStepAllowed(ctx) and E.TryCast(A.TechnicalStep, target, "Technical Step") then return true end

    if ctx.burstActive or ctx.terminal then
        -- Flourishing Starfall and Flourishing Finish must not be allowed to lapse.
        local starfallLeft = buffRemaining(Player, ST.FlourishingStarfall, Player.id)
        if E.AbilityEnabled("StarfallDance") and starfallLeft > 0 and starfallLeft <= (tonumber(c.starfallUrgentSeconds) or 5) and
            E.TryCast(A.StarfallDance, target, "Starfall Dance before it lapses") then return true end
        local lastDanceLeft = buffRemaining(Player, ST.LastDanceReady, Player.id)
        if E.AbilityEnabled("LastDance") and lastDanceLeft > 0 and lastDanceLeft <= (tonumber(c.procUrgentSeconds) or 5) and
            E.TryCast(A.LastDance, target, "Last Dance before it lapses") then return true end
        -- Thirty-second procs gained before the dance run out inside the burst.
        local urgentProc = tonumber(c.procUrgentSeconds) or 5
        if (expiring(ST.SilkenFlow, urgentProc) or expiring(ST.FlourishingFlow, urgentProc)) and
            E.AbilityEnabled("Fountainfall") and E.TryCast(A.Fountainfall, target, "Fountainfall before it lapses") then return true end
        if (expiring(ST.SilkenSymmetry, urgentProc) or expiring(ST.FlourishingSymmetry, urgentProc)) and
            E.AbilityEnabled("ReverseCascade") and E.TryCast(A.ReverseCascade, target, "Reverse Cascade before it lapses") then return true end
        -- The party pours Esprit in during Technical Finish: close to the cap a
        -- spender outranks everything that does not lapse.
        if ctx.esprit >= (tonumber(c.burstSaberOvercapEsprit) or 80) and
            espritSpender(ctx, "Saber Dance at " .. tostring(ctx.esprit) .. " Esprit in the burst") then return true end
        -- Tillana gives 50 Esprit; it goes first while that fits, and after an
        -- Esprit spender when it would overcap.
        -- When the party keeps the gauge full it never drops that low, so once the
        -- buffs are about to end Tillana goes out anyway: 600 potency under them is
        -- worth more than the few points of Esprit that spill over.
        local tillanaDeadline = (ctx.burstRemaining or 0) > 0 and
            ctx.burstRemaining <= (tonumber(c.tillanaBurstDeadlineSeconds) or 6)
        if E.AbilityEnabled("Tillana") and (ctx.esprit <= (tonumber(c.tillanaMaxEsprit) or 30) or tillanaDeadline or
            expiring(ST.FlourishingFinish, (tonumber(c.starfallUrgentSeconds) or 5) + 2.5)) and
            E.TryCast(A.Tillana, target, "Tillana") then return true end
        if ctx.esprit >= 50 and E.AbilityEnabled("DanceOfTheDawn") and
            E.TryCast(A.DanceOfTheDawn, target, "Dance of the Dawn") then return true end
        if E.AbilityEnabled("LastDance") and E.TryCast(A.LastDance, target, "Last Dance in the burst") then return true end
        if E.AbilityEnabled("FinishingMove") and E.TryCast(A.FinishingMove, target, "Finishing Move") then return true end
        if ctx.esprit >= 50 and espritSpender(ctx, "Saber Dance in the burst") then return true end
        if E.AbilityEnabled("StarfallDance") and E.TryCast(A.StarfallDance, target, "Starfall Dance") then return true end
        if E.AbilityEnabled("Tillana") and E.TryCast(A.Tillana, target, "Tillana") then return true end
        return tryProcsAndCombo(ctx)
    end

    -- Outside the burst (The Balance's priority list). Procs last thirty
    -- seconds and must never lapse.
    local urgent = tonumber(c.procUrgentSeconds) or 5
    if E.AbilityEnabled("LastDance") and expiring(ST.LastDanceReady, urgent) and
        E.TryCast(A.LastDance, target, "Last Dance before it lapses") then return true end
    if (expiring(ST.SilkenFlow, urgent) or expiring(ST.FlourishingFlow, urgent)) and
        E.AbilityEnabled("Fountainfall") and E.TryCast(A.Fountainfall, target, "Fountainfall before it lapses") then return true end
    if (expiring(ST.SilkenSymmetry, urgent) or expiring(ST.FlourishingSymmetry, urgent)) and
        E.AbilityEnabled("ReverseCascade") and E.TryCast(A.ReverseCascade, target, "Reverse Cascade before it lapses") then return true end
    -- Leftovers from a burst that has just ended.
    if E.AbilityEnabled("StarfallDance") and E.TryCast(A.StarfallDance, target, "Starfall Dance") then return true end
    if E.AbilityEnabled("Tillana") and (ctx.esprit <= (tonumber(c.tillanaMaxEsprit) or 30) or
        expiring(ST.FlourishingFinish, urgent + 2.5)) and E.TryCast(A.Tillana, target, "Tillana") then return true end

    if ctx.esprit >= (tonumber(c.saberOvercapEsprit) or 85) and
        espritSpender(ctx, "Saber Dance at " .. tostring(ctx.esprit) .. " Esprit") then return true end

    -- A new Standard Finish or Finishing Move overwrites an unused Last Dance.
    local danceDue = ctx.ttk >= (tonumber(c.standardMinimumTTK) or 0) and
        ((E.AbilityEnabled("FinishingMove") and ready(A.FinishingMove, Player.id)) or
         (E.StandardStepAllowed(ctx) and ready(A.StandardStep, Player.id)))
    if danceDue and E.AbilityEnabled("LastDance") and
        E.TryCast(A.LastDance, target, "Last Dance before the next dance overwrites it") then return true end
    if E.AbilityEnabled("FinishingMove") and ctx.ttk >= (tonumber(c.standardMinimumTTK) or 0) and
        E.TryCast(A.FinishingMove, target, "Finishing Move") then return true end
    if E.StandardStepAllowed(ctx) and E.TryCast(A.StandardStep, target, "Standard Step") then return true end

    -- Esprit is pooled for the burst and otherwise spent from the threshold.
    local threshold = tonumber(c.saberOffcycleEsprit) or 80
    if not c.resourcePooling or not ctx.burstConfigured then threshold = 50 end
    if ctx.esprit >= threshold and espritSpender(ctx, "Saber Dance at " .. tostring(ctx.esprit) .. " Esprit") then return true end
    if E.LastDanceAllowed(ctx) and E.TryCast(A.LastDance, target, "Last Dance") then return true end

    return tryProcsAndCombo(ctx)
end

-- Combo: Cascade -> Fountain and Windmill -> Bladeshower. Returns the step
-- (1 or 2) and, at step 2, which combo is open ("single" or "aoe").
function E.NextComboStep()
    if highlighted(A.Fountain) then return 2, "single" end
    if highlighted(A.Bladeshower) then return 2, "aoe" end
    local function from(id)
        if id == A.Cascade then return 2, "single" end
        if id == A.Windmill then return 2, "aoe" end
        return 1, nil
    end
    local last, remain = Player and tonumber(Player.lastcomboid), Player and tonumber(Player.combotimeremain)
    if last and last ~= 0 and remain and remain > 0.5 then return from(last) end
    local s = E.state
    if s.lastComboID and (now() - (s.lastComboAt or 0)) / 1000 <= D.ComboWindowSeconds then return from(s.lastComboID) end
    return 1, nil
end

-- oGCD -------------------------------------------------------------------------------

function E.TryUtility(ctx)
    local hp = Player and Player.hp and tonumber(Player.hp.percent) or 100
    if E.AbilityEnabled("SecondWind") and hp <= E.config.secondWindHP and
        E.TryCast(A.SecondWind, ctx.target, "Second Wind emergency heal") then return true end
    if E.AbilityEnabled("CuringWaltz") and hp <= E.config.curingWaltzHP and
        E.TryCast(A.CuringWaltz, ctx.target, "Curing Waltz") then return true end
    if E.AbilityEnabled("ShieldSamba") and hp <= E.config.shieldSambaHP and
        E.TryCast(A.ShieldSamba, ctx.target, "Shield Samba defensive") then return true end
    return false
end

local function potionWanted(ctx)
    local c = E.config
    if not c.usePotion then return false end
    if ctx.ttk < (tonumber(c.potionMinimumTTK) or 0) then return false end
    return true
end

function E.FlourishAllowed(ctx)
    local c = E.config
    if not E.AbilityEnabled("Flourish") then return false end
    -- Its Threefold and Fourfold procs would overwrite ones still waiting.
    if buffRemaining(Player, ST.ThreefoldFanDance, Player.id) > 0 or
        buffRemaining(Player, ST.FourfoldFanDance, Player.id) > 0 then return false end
    if ctx.hold then
        -- Holding: the Flourish that belongs to the held burst waits with it; the
        -- off-minute one is used as usual.
        return ctx.nextBurst > (tonumber(c.holdFlourishSeconds) or 15)
    end
    if ctx.burstActive or ctx.terminal then return true end
    -- Sixty-second recast: every other use belongs to the burst.
    return not pooling(ctx, c.flourishHoldSeconds)
end

function E.FanDanceAllowed(ctx)
    local c = E.config
    if ctx.burstActive or ctx.terminal then return true end
    if not c.resourcePooling or not ctx.burstConfigured then return true end
    -- Outside the burst feathers are only spent to stay under the cap. A
    -- feather count of zero while Fan Dance is ready is a miscalibrated index.
    local feathers = ctx.feathers or 0
    if feathers <= 0 then return true end
    return feathers >= (tonumber(c.featherOffcycleCount) or 4)
end

function E.TryOGCD(ctx)
    local s, c, target = E.state, E.config, ctx.target
    if ctx.dancing then return false end
    -- A finish or a Step recasts in 1.5 s: exactly one weave fits behind it.
    local shortGCD = D.StandardFinishIDs[s.lastGCDID] or D.TechnicalFinishIDs[s.lastGCDID] or
        s.lastGCDID == A.StandardStep or s.lastGCDID == A.TechnicalStep
    local limit = shortGCD and 1 or c.maxWeaves
    if s.weavesSinceGCD >= limit then return false end
    if E.PendingOGCD(now()) then
        s.lastDecision = "Waiting for client to confirm last oGCD"
        return true
    end

    if E.TryUtility(ctx) then return true end
    if E.TryPartner() then return true end

    -- Devilment goes out right behind Technical Finish (on cooldown when
    -- Technical Step is Off). The potion shares that window.
    local technicalUp = buffRemaining(Player, ST.TechnicalFinish, Player.id) > 0 or
        procActive("TechnicalFinish", ST.TechnicalFinish, 20)
    local devilmentNow = E.AbilityEnabled("Devilment") and (technicalUp or not ctx.hold) and
        (technicalUp or not E.AbilityEnabled("TechnicalStep") or ctx.terminal) and ready(A.Devilment, Player.id)
    if devilmentNow and E.TryCast(A.Devilment, target, "Devilment behind Technical Finish") then return true end
    if potionWanted(ctx) and not ctx.burstActive and E.TechnicalStepAllowed(ctx) and
        cooldownSeconds(action(A.TechnicalStep)) <= (ctx.gcdRemaining or 0) + 0.1 and
        E.TryPotion(ctx, "Potion before Technical Step: " .. tostring(s.potionName)) then return true end
    if potionWanted(ctx) and ctx.burstActive and ctx.burstElapsed <= 6 and
        E.TryPotion(ctx, "Potion in burst window: " .. tostring(s.potionName)) then return true end
    if potionWanted(ctx) and not c.potionOnlyWithBurst and not ctx.burstActive and not ctx.hold and
        E.TryPotion(ctx, "Potion on cooldown: " .. tostring(s.potionName)) then return true end

    if E.AbilityEnabled("FanDanceIII") and E.TryCast(A.FanDanceIII, target, "Fan Dance III") then return true end
    local fourfold = buffRemaining(Player, ST.FourfoldFanDance, Player.id)
    local holdFourfold = pooling(ctx, c.fanDanceIVHoldSeconds) and fourfold > ctx.nextBurst + 9
    if E.AbilityEnabled("FanDanceIV") and not holdFourfold and
        E.TryCast(A.FanDanceIV, target, "Fan Dance IV") then return true end
    if E.FlourishAllowed(ctx) and E.TryCast(A.Flourish, target, "Flourish") then return true end

    if E.FanDanceAllowed(ctx) then
        local reason = ctx.burstActive and "Fan Dance in the burst" or
            ("Fan Dance at " .. tostring(ctx.feathers) .. " feathers")
        if E.AoEAllowed("FanDanceII", ctx) and E.TryCast(A.FanDanceII, target, reason) then return true end
        if E.AbilityEnabled("FanDance") and E.TryCast(A.FanDance, target, reason) then return true end
    end
    return false
end
-- Pre-pull ------------------------------------------------------------------------
-- The Balance opens with Standard Step at -15 s and lands Standard Finish on
-- the pull. There is no countdown to read, so the pre-pull runs in two
-- situations only:
--   * `requireCombat` is off, so the engine itself pulls: Standard Step, both
--     steps, the potion, then Standard Finish as the pull;
--   * the user arms it (the window's "Pre-pull now" button) while waiting for
--     someone else's pull: Standard Step and both steps, then the finish is
--     held until combat starts. The dance lasts fifteen seconds; the engine
--     never pulls in this mode and lets the dance lapse rather than do so.

function E.ArmPrepull(seconds)
    E.state.prepullArmedUntil = now() + (tonumber(seconds) or 14) * 1000
end

function E.PrepullArmed()
    return (E.state.prepullArmedUntil or 0) > now()
end

function E.TryPrepull(ctx)
    local c, s, target = E.config, E.state, ctx.target
    if E.PendingGCD(now()) or E.PendingOGCD(now()) then return true end
    local kind = E.Dancing()
    if kind then
        local _, _, completed, needed = E.NextStep(kind)
        if completed >= needed and ctx.pullNow and c.usePotion and c.potionPrepull and
            E.TryPotion(ctx, "Pre-pull potion: " .. tostring(s.potionName)) then return true end
        return E.TryDance(ctx, kind)
    end
    if E.AbilityEnabled("StandardStep") and buffRemaining(Player, ST.StandardFinish, Player.id) <= 30 and
        E.TryCast(A.StandardStep, target, "Pre-pull Standard Step") then return true end
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

    if not Player or not Player.alive or Player.job ~= D.DancerJobID then s.lastDecision = "Requires Dancer" return false end
    trackCombatForHold()
    if not Player.incombat and not (type(MIsLocked) == "function" and MIsLocked()) and
        not (type(MIsLoading) == "function" and MIsLoading()) and E.TryPartner() then return true end
    if type(MIsLoading) == "function" and MIsLoading() then return false end
    if type(MIsLocked) == "function" and MIsLocked() then return false end
    if type(MIsCasting) == "function" and MIsCasting() then return false end
    local prepull = not Player.incombat and c.prepull and (not c.requireCombat or E.PrepullArmed())
    if c.requireCombat and not Player.incombat and not prepull then
        if s.sampleTargetID ~= 0 then E.ResetCombat("Waiting for combat") end
        return false
    end
    if Player.incombat then s.prepullArmedUntil = 0 end
    local target = E.GetTarget()
    if not target then s.lastDecision = "No valid target" return false end
    if tonumber(target.distance2d) and target.distance2d > 25 then s.lastDecision = "Target out of range" return false end
    -- Live clients report target.los == false on a striking dummy in plain
    -- view, so this check is opt-in and also accepts the los2 field.
    if c.requireLOS and target.los == false and target.los2 ~= true then s.lastDecision = "Target not in line of sight" return false end
    if ActionList and type(ActionList.IsCasting) == "function" and ActionList:IsCasting() then return false end

    E.ObserveLastCast()
    E.UpdateTTK(target, ticks)
    s.enemyCount = E.CountEnemiesNear(target)

    -- IsReady does not reflect the recast on live clients, so the GCD timer is
    -- read from cd/cdmax the same way the bot's SkillManager does.
    local gcdRemaining = E.GCDRemaining(target)
    s.gcdRemaining = gcdRemaining
    local ctx = E.BuildContext(target, gcdRemaining)
    if prepull then
        if gcdRemaining <= (tonumber(c.gcdLeadSeconds) or 0.05) and E.TryPrepull(ctx) then return true end
        if c.requireCombat or E.Dancing() then return false end
    end

    if c.debug and ticks - (s.lastDebugAt or 0) >= 1000 and type(d) == "function" then
        s.lastDebugAt = ticks
        local g = {}
        for index = 1, 8 do g[index] = tostring(Player.gauge and Player.gauge[index]) end
        d(string.format("[CielDancer] gauge=%s dancing=%s esprit=%s feathers=%s burst=%.1f gcdRem=%.2f weaves=%d lastcast=%s since=%s combo=%s/%s",
            table.concat(g, ","), tostring(ctx.dancing), tostring(ctx.esprit), tostring(ctx.feathers), ctx.burstRemaining or 0,
            gcdRemaining, s.weavesSinceGCD, tostring(Player.castinginfo and Player.castinginfo.lastcastid),
            tostring(Player.castinginfo and Player.castinginfo.timesincecast), tostring(Player.lastcomboid), tostring(Player.combotimeremain)))
    end

    -- When the GCD is available, it always wins.
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

-- Seconds until the GCD is available, taken from Cascade's cooldown. Steps
-- (1.0 s) and finishes (1.5 s) shorten the shared recast group, so the filler
-- reports those too.
function E.GCDRemaining(target)
    local ac = action(A.Cascade)
    if ac and tonumber(ac.cdmax) and tonumber(ac.cd) then return math.max(0, ac.cdmax - ac.cd) end
    if ready(A.Cascade, target and target.id) then return 0 end
    return 999
end

function E.OnUpdate()
    return E.Step(false)
end
