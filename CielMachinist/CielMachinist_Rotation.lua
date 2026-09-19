CielMachinistEngine = CielMachinistEngine or {}

local E = CielMachinistEngine
local D = CielMachinistData
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
    overheatStacks = 0,
    comboStep = 0,
    comboAt = 0,
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
    heat = 0,
    battery = 0,
    overheated = false,
    charges = {},
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

-- Locally tracked procs ------------------------------------------------------
-- Overheated, Full Metal Machinist, Excavator Ready, Reassembled and Wildfire
-- are read from the live status list first. Builds that do not expose a status
-- (or expose it a few pulses late) fall back to a timer started by the
-- accepted or observed cast that grants it. The fallback is deliberately
-- narrow: once the live status has been seen for this proc it is authoritative,
-- so "no buff" then means consumed or expired rather than "not applied yet",
-- and the cast that consumes a proc clears the timer outright.

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

function E.Overheated()
    local active, remaining = procActive("Overheated", ST.Overheated, D.OverheatedWindowSeconds)
    -- Without a readable status the five-weaponskill budget ends the window.
    local proc = E.state.procs.Overheated
    if active and proc and not proc.seen and (E.state.overheatStacks or 0) <= 0 then
        clearProc("Overheated")
        return false, 0
    end
    return active, remaining
end

function E.FullMetalPending()
    return procActive("FullMetal", ST.FullMetalMachinist, 30)
end

function E.ExcavatorPending()
    return procActive("Excavator", ST.ExcavatorReady, 30)
end

function E.Reassembled()
    return procActive("Reassembled", ST.Reassembled, 5)
end

function E.WildfireActive()
    return procActive("Wildfire", ST.WildfireSelf, D.WildfireWindowSeconds)
end

-- Charges --------------------------------------------------------------------
-- The client exposes the game's charged-recast layout directly: cdmax is the
-- full stack (recast x max charges), cd is elapsed, and the charge count is
-- floor(cd / recast). Off cooldown means a full stack.
local function chargeState(actionID, fallbackMax)
    local ac = action(actionID)
    local cd, cdmax, recast = ac and tonumber(ac.cd), ac and tonumber(ac.cdmax), ac and tonumber(ac.recasttime)
    if not ac or ac.usable == false or not recast or recast <= 0 then
        return { info = false, charges = 0, max = fallbackMax, remaining = 0, recast = 0 }
    end
    local maxCharges = (cdmax and cdmax >= recast * 2) and math.floor(cdmax / recast + 0.5) or fallbackMax
    if ac.isoncd == false or not cd or not cdmax or cdmax <= 0 then
        return { info = true, charges = maxCharges, max = maxCharges, remaining = 0, recast = recast }
    end
    local charges = clamp(math.floor(cd / recast), 0, maxCharges)
    local remaining = charges >= maxCharges and 0 or (recast - (cd % recast))
    return { info = true, charges = charges, max = maxCharges, remaining = remaining, recast = recast }
end

-- True when a charge would be wasted soon: already full, or the last charge
-- completes within `lead` seconds.
local function chargeAboutToCap(state, lead)
    if not state.info then return true end -- no data: never hold
    if state.charges >= state.max then return true end
    return state.charges == state.max - 1 and state.remaining <= lead
end

-- Charges that would be banked `seconds` from now if one were spent at once.
local function chargesAfterSpending(state, seconds)
    if not state.info or state.recast <= 0 then return 0 end
    local charges = state.charges - 1
    local untilNext = state.charges >= state.max and state.recast or state.remaining
    if seconds >= untilNext then
        charges = charges + 1 + math.floor((seconds - untilNext) / state.recast)
    end
    return clamp(charges, 0, state.max)
end

function E.UpdateCharges()
    local s = E.state
    s.charges.Drill = chargeState(A.Drill, 2)
    s.charges.Reassemble = chargeState(A.Reassemble, 2)
    s.charges.DoubleCheck = chargeState(A.DoubleCheck, 3)
    s.charges.Checkmate = chargeState(A.Checkmate, 3)
    if not s.charges.DoubleCheck.info then s.charges.DoubleCheck = chargeState(A.GaussRound, 3) end
    if not s.charges.Checkmate.info then s.charges.Checkmate = chargeState(A.Ricochet, 3) end
end

-- Configuration warnings -------------------------------------------------------

function E.GetConfigurationWarnings()
    local warnings = {}
    local c = E.config or D.Defaults
    if c.usePotion and not E.PotionAvailable() then
        table.insert(warnings, "Potion use is On but no Gemdraught of Dexterity was found in inventory.")
    end
    if not c.advancedEnabled then return warnings end
    local enabled = E.AbilityEnabled
    if enabled("Hypercharge") and not enabled("BlazingShot") and not enabled("AutoCrossbow") then
        table.insert(warnings, "Hypercharge is skipped while Blazing Shot and Auto Crossbow are both Off.")
    end
    if enabled("Excavator") and not enabled("ChainSaw") then
        table.insert(warnings, "Excavator cannot normally be generated while Chain Saw is Off.")
    end
    if enabled("FullMetalField") and not enabled("BarrelStabilizer") then
        table.insert(warnings, "Full Metal Field cannot normally be generated while Barrel Stabilizer is Off.")
    end
    if enabled("QueenOverdrive") and not enabled("AutomatonQueen") then
        table.insert(warnings, "Queen Overdrive has nothing to act on while Automaton Queen is Off.")
    end
    if enabled("Wildfire") and not enabled("Hypercharge") then
        table.insert(warnings, "Wildfire is used on cooldown without Hypercharge and will catch fewer weaponskills.")
    end
    if c.executionMode == "OGCD_ONLY" then
        table.insert(warnings, "oGCD-only mode expects you or another system to keep the GCD rolling.")
    end
    return warnings
end

-- Burst ----------------------------------------------------------------------------

local function majorBurstEnabled()
    return E.AbilityEnabled("BarrelStabilizer") or E.AbilityEnabled("Wildfire")
end

local function noteBurst(ticks)
    local s = E.state
    if s.burstAt == 0 or ticks - s.burstAt > 20500 then s.burstAt = ticks end
end

-- Seconds until the next two-minute burst. Barrel Stabilizer is the anchor:
-- it is pressed on cooldown at the top of the burst, while Wildfire trails it
-- by the dozen seconds the tools take, in the opener and every burst after.
-- Wildfire only stands in when Barrel Stabilizer is Off.
local function nextBurstSeconds()
    if not majorBurstEnabled() then return 999, false end
    local anchor = E.AbilityEnabled("BarrelStabilizer") and A.BarrelStabilizer or A.Wildfire
    local remaining = cooldownSeconds(action(anchor))
    if remaining >= 999 then remaining = 0 end -- no cooldown data: treat as ready
    return remaining, true
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
    s.overheatStacks = 0
    s.comboStep = 0
    s.comboAt = 0
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
    s.charges = {}
    s.lastDecision = reason or "Reset"
end

function E.GetGauge(index)
    return gauge(index)
end

function E.GetHeat()
    return gauge(E.config.heatGaugeIndex)
end

-- Battery drives thresholds above 50, so a miscalibrated gauge index must not
-- silence the Queen: when the summon itself is ready the gauge is at least 50.
function E.GetBattery()
    local battery = gauge(E.config.batteryGaugeIndex)
    if battery < 50 and Player and (ready(A.AutomatonQueen, Player.id) or ready(A.RookAutoturret, Player.id)) then
        return 50
    end
    return battery
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

-- Combo ------------------------------------------------------------------------------

local function comboStepForAction(actionID)
    for index, step in ipairs(D.Combo) do
        for _, id in ipairs(step.ids) do
            if id == actionID then return index end
        end
    end
    return nil
end

-- Bookkeeping shared by an accepted request and an observed cast. `observed`
-- is false for the request path, which must not count weaponskills twice.
local function noteCast(actionID, ticks, observed)
    local s = E.state
    if actionID == A.BarrelStabilizer then
        noteBurst(ticks)
        noteProc("FullMetal", ticks)
    elseif actionID == A.Wildfire then
        noteBurst(ticks)
        noteProc("Wildfire", ticks)
    elseif actionID == A.Hypercharge then
        noteProc("Overheated", ticks)
        s.overheatStacks = 5
    elseif actionID == A.Reassemble then
        noteProc("Reassembled", ticks)
    elseif actionID == A.ChainSaw then
        noteProc("Excavator", ticks)
    elseif actionID == A.Excavator then
        clearProc("Excavator")
    elseif actionID == A.FullMetalField then
        clearProc("FullMetal")
    end
    if D.GCD[actionID] then s.lastGCDID = actionID end
    if not observed or not D.GCD[actionID] then return end

    -- Reassemble is spent by the next weaponskill, except Full Metal Field,
    -- which is already a guaranteed critical direct hit and leaves it alone.
    if actionID ~= A.FullMetalField then clearProc("Reassembled") end
    if actionID == A.BlazingShot or actionID == A.HeatBlast or actionID == A.AutoCrossbow then
        s.overheatStacks = math.max(0, (s.overheatStacks or 0) - 1)
    end
    local step = comboStepForAction(actionID)
    if step then
        local continues = step == 1 or (s.comboStep == step - 1 and
            (ticks - s.comboAt) / 1000 <= D.ComboWindowSeconds)
        s.comboStep = continues and (step % #D.Combo) or 0
        s.comboAt = ticks
    elseif actionID == A.Scattergun or actionID == A.SpreadShot then
        s.comboStep = 0
    end
end

-- Index of the next combo action to press (1 = Split, 2 = Slug, 3 = Clean).
function E.NextComboStep()
    -- A combo-ready action is outlined in game; that is the most direct signal.
    if highlighted(A.HeatedCleanShot) or highlighted(A.CleanShot) then return 3 end
    if highlighted(A.HeatedSlugShot) or highlighted(A.SlugShot) then return 2 end
    -- Player.lastcomboid / combotimeremain is what FFXIVMinion's SkillMgr reads.
    local last, remain = Player and tonumber(Player.lastcomboid), Player and tonumber(Player.combotimeremain)
    if last and last ~= 0 and remain and remain > 0.5 then
        local step = comboStepForAction(last)
        if step and step < #D.Combo then return step + 1 end
        return 1
    end
    local s = E.state
    if s.comboStep > 0 and (now() - s.comboAt) / 1000 <= D.ComboWindowSeconds then
        return s.comboStep + 1
    end
    return 1
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

-- Tools ------------------------------------------------------------------------------

-- Seconds until a cooldown weaponskill is off its own recast. Unavailable
-- (level-synced away) actions never come due.
local function toolCooldown(actionID)
    local ac = action(actionID)
    if not ac or ac.usable == false then return 999 end
    return cooldownSeconds(ac)
end

-- Air Anchor's recast, or Hot Shot's when level sync has taken Air Anchor
-- away. A replaced Hot Shot can report no cooldown at all at level 100, so it
-- is only consulted when Air Anchor itself is unavailable.
local function airAnchorCooldown()
    local ac = action(A.AirAnchor)
    if ac and ac.usable ~= false then return cooldownSeconds(ac) end
    return toolCooldown(A.HotShot)
end

local function drillState()
    return E.state.charges.Drill or chargeState(A.Drill, 2)
end

-- True when Bioblaster should take the Drill slot: enough targets and the
-- DoT on the primary target is missing or about to fall off.
local function bioblasterWanted(ctx)
    if not E.AoEAllowed("Bioblaster", ctx) then return false end
    return buffRemaining(ctx.target, ST.Bioblaster, Player.id) <= 3
end

-- The tool the GCD chain would press if the GCD came up within `within`
-- seconds, in the same order E.TryGCD uses. Full Metal Field is reported
-- separately because it is already a guaranteed critical direct hit.
function E.NextTool(ctx, within, heldWithin)
    local drill = drillState()
    -- Air Anchor and Chain Saw get the GCD held for them (toolHoldSeconds), so
    -- they may be counted on a little later than a Drill charge can.
    heldWithin = heldWithin or within
    if E.AbilityEnabled("AirAnchor") and
        airAnchorCooldown() <= heldWithin then return "AirAnchor" end
    if E.AbilityEnabled("Drill") and drill.info and drill.charges >= drill.max then return "Drill" end
    if E.AbilityEnabled("ChainSaw") and toolCooldown(A.ChainSaw) <= heldWithin then return "ChainSaw" end
    if E.AbilityEnabled("Excavator") and E.ExcavatorPending() then return "Excavator" end
    if E.AbilityEnabled("Drill") then
        if drill.info and (drill.charges >= 1 or drill.remaining <= within) then return "Drill" end
        if not drill.info and toolCooldown(A.Drill) <= within then return "Drill" end
    end
    return nil
end

-- Hypercharge would make one of these drift: a tool that comes off its recast
-- (or a Drill stack that caps) inside the Overheated window, or a granted
-- weaponskill that is still waiting to be pressed.
function E.ToolsBlockHypercharge(lead)
    if E.AbilityEnabled("FullMetalField") and E.FullMetalPending() then return true, "Full Metal Field" end
    if E.AbilityEnabled("Excavator") and E.ExcavatorPending() then return true, "Excavator" end
    if E.AbilityEnabled("AirAnchor") and airAnchorCooldown() <= lead then return true, "Air Anchor" end
    if E.AbilityEnabled("ChainSaw") and toolCooldown(A.ChainSaw) <= lead then return true, "Chain Saw" end
    if E.AbilityEnabled("Drill") then
        local drill = drillState()
        if drill.info and chargeAboutToCap(drill, lead) then return true, "Drill" end
        if not drill.info and toolCooldown(A.Drill) <= lead then return true, "Drill" end
    end
    return false, nil
end

-- Context ------------------------------------------------------------------

function E.BuildContext(target, gcdRemaining)
    local s, c = E.state, E.config
    local nextBurst, burstConfigured = nextBurstSeconds()
    local burstElapsed = s.burstAt > 0 and (now() - s.burstAt) / 1000 or 999
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

    local overheated = E.Overheated()
    s.overheated = overheated
    s.heat, s.battery = E.GetHeat(), E.GetBattery()

    return {
        target = target,
        ttk = ttk,
        terminal = c.terminalDumping and ttk <= c.terminalTTK,
        idealFinish = ttk > c.terminalTTK and ttk <= c.idealKillMax,
        enemies = s.enemyCount,
        aoe = c.useAOE and s.enemyCount >= E.MinAoETargets(),
        nextBurst = nextBurst,
        burstElapsed = burstElapsed,
        burstActive = burstActive,
        burstConfigured = burstConfigured,
        ttkBand = band,
        heat = s.heat,
        battery = s.battery,
        overheated = overheated,
        gcdRemaining = gcdRemaining or 0,
    }
end

-- Wildfire and Hypercharge ---------------------------------------------------------

local function overheatSpenderEnabled()
    return E.AbilityEnabled("BlazingShot") or E.AbilityEnabled("AutoCrossbow")
end

local function wildfirePairingWanted(ctx)
    return E.AbilityEnabled("Wildfire") and ctx.ttk >= (tonumber(E.config.wildfireMinimumTTK) or 0)
end

-- Hypercharged (from Barrel Stabilizer) must not be allowed to expire behind
-- a hold: when it is about to run out every gate below is bypassed.
local function hyperchargedExpiring()
    local remaining = buffRemaining(Player, ST.Hypercharged, Player.id)
    return remaining > 0 and remaining <= 4
end

-- The two-minute burst wants two Hypercharges: the free one Barrel Stabilizer
-- grants and a heat-funded one right behind it (The Balance's static burst).
-- Hardly any heat is generated inside the burst itself, so the second one has
-- to be paid for in advance: an off-cycle Hypercharge is refused when the heat
-- left over, plus what the combo regenerates before the burst, would not reach
-- `hyperchargeBurstHeat`. A gauge that reads under 50 while Hypercharge is
-- ready is a miscalibrated index, and a blind hold would never release, so
-- that case never pools; neither does a full gauge.
function E.HeatPooledForBurst(ctx)
    local c = E.config
    if not c.resourcePooling or not ctx.burstConfigured or ctx.terminal or ctx.burstActive then return false end
    local wanted = tonumber(c.hyperchargeBurstHeat) or 0
    if wanted <= 0 then return false end
    if buffRemaining(Player, ST.Hypercharged, Player.id) > 0 then return false end
    local heat = ctx.heat or 0
    if heat < 50 or heat >= 100 then return false end
    local projected = heat - 50 + (tonumber(c.heatPerSecond) or 1) * (ctx.nextBurst or 999)
    return projected < wanted
end

function E.HyperchargeAllowed(ctx)
    local c = E.config
    if not E.AbilityEnabled("Hypercharge") or not overheatSpenderEnabled() then return false end
    if ctx.overheated or not ready(A.Hypercharge, Player.id) then return false end
    if hyperchargedExpiring() then return true, "Hypercharge before Hypercharged expires" end

    if E.ToolsBlockHypercharge(tonumber(c.hyperchargeToolLeadSeconds) or 8) then return false end

    if wildfirePairingWanted(ctx) then
        -- Wildfire follows Hypercharge in the next weave slot. When it is
        -- nearly but not yet up, Hypercharge is kept for it.
        local wildfire = cooldownSeconds(action(A.Wildfire))
        if wildfire <= 0.7 then return true, "Hypercharge for Wildfire" end
        if not ctx.terminal and c.resourcePooling and
            wildfire <= (tonumber(c.hyperchargeHoldForBurstSeconds) or 12) then
            return false
        end
    end
    if E.HeatPooledForBurst(ctx) then return false end
    return true, "Hypercharge at " .. tostring(ctx.heat) .. " heat"
end

-- Wildfire counts weaponskills landed in its ten seconds, so it goes out right
-- behind Hypercharge: five Blazing Shots plus the weaponskill after them make
-- six with more than a second to spare, which is the placement The Balance
-- calls the most ping-friendly. A window that is already mostly spent is left
-- alone in favour of the next Hypercharge.
function E.WildfireAllowed(ctx)
    local c = E.config
    if not E.AbilityEnabled("Wildfire") then return false end
    if ctx.ttk < (tonumber(c.wildfireMinimumTTK) or 0) then return false end
    if E.WildfireActive() then return false end
    if not E.AbilityEnabled("Hypercharge") or not overheatSpenderEnabled() then return true end
    if not ctx.overheated then return false end
    return ctx.terminal or (E.state.overheatStacks or 0) >= (tonumber(c.wildfireMinimumStacks) or 3)
end

-- GCD --------------------------------------------------------------------------------

local function tryCombo(ctx)
    local target = ctx.target
    local step = E.NextComboStep()
    if step == 3 and (E.TryCast(A.HeatedCleanShot, target, "Heated Clean Shot combo") or
        E.TryCast(A.CleanShot, target, "Clean Shot level-sync combo")) then return true end
    if step == 2 and (E.TryCast(A.HeatedSlugShot, target, "Heated Slug Shot combo") or
        E.TryCast(A.SlugShot, target, "Slug Shot level-sync combo")) then return true end
    -- Non-configurable emergency filler: custom settings must never stall the
    -- GCD merely because every optional action was switched Off.
    if E.TryCast(A.HeatedSplitShot, target, "Heated Split Shot filler") then return true end
    return E.TryCast(A.SplitShot, target, "Split Shot level-sync fallback")
end

local function tryDrillSlot(ctx, decision)
    if not E.AbilityEnabled("Drill") and not E.AbilityEnabled("Bioblaster") then return false end
    if bioblasterWanted(ctx) and E.TryCast(A.Bioblaster, ctx.target, "Bioblaster on the pack") then return true end
    return E.AbilityEnabled("Drill") and E.TryCast(A.Drill, ctx.target, decision)
end

function E.TryGCD(ctx)
    local target = ctx.target

    -- Hold the whole GCD tier while the client has not confirmed the last
    -- accepted weaponskill, instead of letting the priority chain substitute a
    -- different one into the same queue window.
    if E.PendingGCD(now()) then
        E.state.lastDecision = "Waiting for client to confirm last GCD"
        return true
    end

    -- Overheated: nothing but the 1.5 s weaponskills. They are only ready
    -- while Overheated, so a misread status falls straight through.
    if E.AoEAllowed("AutoCrossbow", ctx) and
        E.TryCast(A.AutoCrossbow, target, "Auto Crossbow while Overheated") then return true end
    if E.AbilityEnabled("BlazingShot") and
        (E.TryCast(A.BlazingShot, target, "Blazing Shot while Overheated") or
         E.TryCast(A.HeatBlast, target, "Heat Blast level-sync fallback")) then return true end

    -- Tools, in drift order. A capped Drill stack outranks everything except
    -- Air Anchor, whose battery the opener wants first.
    if E.AbilityEnabled("AirAnchor") and
        (E.TryCast(A.AirAnchor, target, "Air Anchor") or
         E.TryCast(A.HotShot, target, "Hot Shot level-sync fallback")) then return true end
    local drill = drillState()
    if drill.info and drill.charges >= drill.max and tryDrillSlot(ctx, "Drill at full charges") then return true end
    if E.AbilityEnabled("ChainSaw") and E.TryCast(A.ChainSaw, target, "Chain Saw") then return true end
    if E.AbilityEnabled("Excavator") and E.TryCast(A.Excavator, target, "Excavator") then return true end
    if tryDrillSlot(ctx, "Drill") then return true end
    if E.AbilityEnabled("FullMetalField") and
        E.TryCast(A.FullMetalField, target, "Full Metal Field") then return true end

    -- A filler pressed a few tenths before Air Anchor or Chain Saw comes back
    -- would drift that tool by a whole GCD, every time; a brief hold is cheaper.
    local hold = tonumber(E.config.toolHoldSeconds) or 0
    if hold > 0 then
        local soonest, name = 999, nil
        if E.AbilityEnabled("AirAnchor") then soonest, name = airAnchorCooldown(), "Air Anchor" end
        if E.AbilityEnabled("ChainSaw") and toolCooldown(A.ChainSaw) < soonest then
            soonest, name = toolCooldown(A.ChainSaw), "Chain Saw"
        end
        if soonest > 0 and soonest <= hold then
            E.state.lastDecision = "Holding the GCD " .. string.format("%.2f", soonest) .. "s for " .. name
            return true
        end
    end

    if E.AoEAllowed("Scattergun", ctx) and
        (E.TryCast(A.Scattergun, target, "Scattergun on the pack") or
         E.TryCast(A.SpreadShot, target, "Spread Shot level-sync fallback")) then return true end
    return tryCombo(ctx)
end

-- oGCD -------------------------------------------------------------------------------

function E.TryUtility(ctx)
    local hp = Player and Player.hp and tonumber(Player.hp.percent) or 100
    if E.AbilityEnabled("SecondWind") and hp <= E.config.secondWindHP and
        E.TryCast(A.SecondWind, ctx.target, "Second Wind emergency heal") then return true end
    if E.AbilityEnabled("Tactician") and hp <= E.config.tacticianHP and
        E.TryCast(A.Tactician, ctx.target, "Tactician defensive") then return true end
    return false
end

local function potionWanted(ctx)
    local c = E.config
    if not c.usePotion then return false end
    if ctx.ttk < (tonumber(c.potionMinimumTTK) or 0) then return false end
    return true
end

local function pooling(ctx, seconds)
    local c = E.config
    return c.resourcePooling and ctx.burstConfigured and not ctx.terminal and not ctx.burstActive and
        ctx.nextBurst <= (tonumber(seconds) or 0)
end

function E.ReassembleAllowed(ctx)
    local c, s = E.config, E.state
    if not E.AbilityEnabled("Reassemble") or ctx.overheated or E.Reassembled() then return false end
    -- The tool has to be off its recast comfortably before the GCD is, or the
    -- guaranteed critical direct hit lands on whatever filler goes out instead.
    local gcdRemaining = ctx.gcdRemaining or 0
    local tool = E.NextTool(ctx, math.max(0, gcdRemaining - 0.2),
        gcdRemaining + math.max(0, (tonumber(c.toolHoldSeconds) or 0) - 0.1))
    if not tool then return false end
    -- Bioblaster is a DoT; the guaranteed critical direct hit is wasted on it.
    if tool == "Drill" and bioblasterWanted(ctx) then return false end
    local charges = s.charges.Reassemble or chargeState(A.Reassemble, 2)
    if ctx.terminal or not charges.info then return true, tool end
    if chargeAboutToCap(charges, tonumber(c.chargeCapLeadSeconds) or 4) then return true, tool end
    if ctx.burstActive then
        -- Party buffs land a few seconds into the burst; an uncapped charge waits for them.
        return ctx.burstElapsed >= (tonumber(c.reassembleBurstDelaySeconds) or 0), tool
    end
    if c.resourcePooling and ctx.burstConfigured and
        chargesAfterSpending(charges, ctx.nextBurst) < (tonumber(c.reassembleBurstCharges) or 0) then
        return false
    end
    return true, tool
end

-- True when a +20 battery weaponskill is about to be pressed.
local function batteryToolDue(within)
    if E.AbilityEnabled("AirAnchor") and airAnchorCooldown() <= within then return true end
    if E.AbilityEnabled("ChainSaw") and toolCooldown(A.ChainSaw) <= within then return true end
    return E.AbilityEnabled("Excavator") and E.ExcavatorPending()
end

function E.QueenAllowed(ctx)
    local c = E.config
    if not E.AbilityEnabled("AutomatonQueen") then return false end
    if ctx.ttk < (tonumber(c.queenMinimumTTK) or 0) then return false end
    local battery = ctx.battery or 0
    if battery < 50 then return false end
    if ctx.terminal or ctx.idealFinish then return true, "Automaton Queen before the kill" end
    if ctx.burstActive then
        if battery < (tonumber(c.queenBatteryBurst) or 50) then return false end
        -- Air Anchor, Chain Saw and Excavator all come back with the burst; one
        -- that still fits under the cap tops her off first (The Balance summons
        -- the even-minute Queen at 100, right after Air Anchor).
        if battery <= 80 and batteryToolDue(tonumber(c.queenTopOffSeconds) or 0) then return false end
        return true, "Automaton Queen for the burst at " .. tostring(battery) .. " battery"
    end
    -- Too close to the burst to refill: keep the battery unless it is full.
    if c.resourcePooling and ctx.burstConfigured and
        ctx.nextBurst < (tonumber(c.queenRefillSeconds) or 0) then
        if battery >= 100 then return true, "Automaton Queen at full battery" end
        return false
    end
    -- Last call: the final moment she can go and still leave a refill for the burst.
    if c.resourcePooling and ctx.burstConfigured and
        ctx.nextBurst <= (tonumber(c.queenRefillSeconds) or 0) + (tonumber(c.queenLastCallSeconds) or 0) then
        return true, "Automaton Queen before the refill window at " .. tostring(battery) .. " battery"
    end
    if battery >= (tonumber(c.queenBatteryOffcycle) or 90) then
        return true, "Automaton Queen at " .. tostring(battery) .. " battery"
    end
    return false
end

-- Double Check and Checkmate have separate charges; the fuller stack goes first
-- so neither caps while the other is drained.
local function tryGauss(ctx, decision)
    local s = E.state
    local order = {
        { key = "DoubleCheck", id = A.DoubleCheck, fallback = A.GaussRound },
        { key = "Checkmate", id = A.Checkmate, fallback = A.Ricochet },
    }
    local dc, cm = s.charges.DoubleCheck, s.charges.Checkmate
    if dc and cm and dc.info and cm.info and
        (cm.charges > dc.charges or (cm.charges == dc.charges and cm.remaining < dc.remaining)) then
        order[1], order[2] = order[2], order[1]
    end
    for _, entry in ipairs(order) do
        if E.AbilityEnabled(entry.key) and
            (E.TryCast(entry.id, ctx.target, decision) or E.TryCast(entry.fallback, ctx.target, decision)) then
            return true
        end
    end
    return false
end

local function gaussAboutToCap()
    local s, lead = E.state, tonumber(E.config.chargeCapLeadSeconds) or 4
    for _, key in ipairs({ "DoubleCheck", "Checkmate" }) do
        if E.AbilityEnabled(key) and chargeAboutToCap(s.charges[key] or { info = false }, lead) then return true end
    end
    return false
end

function E.TryOGCD(ctx)
    local s, c, target = E.state, E.config, ctx.target
    -- A 1.5 s weaponskill leaves room for one weave. The limit follows the last
    -- weaponskill rather than the Overheated status so Hypercharge and Wildfire
    -- can still share the 2.5 s window Hypercharge was pressed in.
    local shortGCD = s.lastGCDID == A.BlazingShot or s.lastGCDID == A.HeatBlast or s.lastGCDID == A.AutoCrossbow
    local limit = shortGCD and (tonumber(c.maxWeavesOverheated) or 1) or c.maxWeaves
    if s.weavesSinceGCD >= limit then return false end
    if E.PendingOGCD(now()) then
        s.lastDecision = "Waiting for client to confirm last oGCD"
        return true
    end

    if E.TryUtility(ctx) then return true end

    -- Barrel Stabilizer anchors the two-minute burst and is pressed on
    -- cooldown. The potion goes into the same weave window just before it.
    if E.AbilityEnabled("BarrelStabilizer") and ready(A.BarrelStabilizer, Player.id) then
        if potionWanted(ctx) and s.weavesSinceGCD + 1 < limit and
            E.TryPotion(ctx, "Potion before burst: " .. tostring(s.potionName)) then return true end
        if E.TryCast(A.BarrelStabilizer, target, "Begin burst with Barrel Stabilizer") then return true end
    end
    if potionWanted(ctx) and ctx.burstActive and ctx.burstElapsed <= 5 and
        E.TryPotion(ctx, "Potion in burst window: " .. tostring(s.potionName)) then return true end
    if potionWanted(ctx) and not c.potionOnlyWithBurst and not ctx.burstActive and
        E.TryPotion(ctx, "Potion on cooldown: " .. tostring(s.potionName)) then return true end

    if E.WildfireAllowed(ctx) and
        E.TryCast(A.Wildfire, target, "Wildfire behind Hypercharge") then return true end

    local hypercharge, reason = E.HyperchargeAllowed(ctx)
    if hypercharge and E.TryCast(A.Hypercharge, target, reason) then return true end

    local reassemble, tool = E.ReassembleAllowed(ctx)
    if reassemble and E.TryCast(A.Reassemble, target, "Reassemble for " .. tostring(tool)) then return true end

    if E.AbilityEnabled("QueenOverdrive") and ctx.terminal and
        ctx.ttk <= (tonumber(c.queenOverdriveTTK) or 0) and
        (E.TryCast(A.QueenOverdrive, target, "Queen Overdrive before the kill") or
         E.TryCast(A.RookOverdrive, target, "Rook Overdrive before the kill")) then return true end
    local queen, queenReason = E.QueenAllowed(ctx)
    if queen and (E.TryCast(A.AutomatonQueen, target, queenReason) or
        E.TryCast(A.RookAutoturret, target, "Rook Autoturret level-sync fallback")) then return true end

    -- Double Check / Checkmate: on cooldown, except in the run-up to the burst
    -- where only a stack that is about to cap is spent.
    if pooling(ctx, c.chargePoolSeconds) and not ctx.overheated then
        if gaussAboutToCap() and tryGauss(ctx, "Double Check / Checkmate before the stack caps") then return true end
        return false
    end
    return tryGauss(ctx, ctx.overheated and "Double Check / Checkmate while Overheated"
        or "Double Check / Checkmate on cooldown")
end

-- Pre-pull ------------------------------------------------------------------------
-- The Balance opens with Reassemble at -5 s and the potion at -2 s. The engine
-- has no countdown to read, so the pre-pull runs in two situations only:
--   * `requireCombat` is off, so the engine itself pulls: Reassemble and the
--     potion go out immediately before its first weaponskill;
--   * the user arms it (the window's "Pre-pull now" button) while waiting for
--     someone else's pull, and has five seconds to land the first weaponskill.
-- Reassemble is only spent from a full stack, so an aborted pull costs the
-- recharge and nothing else.

function E.ArmPrepull(seconds)
    E.state.prepullArmedUntil = now() + (tonumber(seconds) or 10) * 1000
end

function E.PrepullArmed()
    return (E.state.prepullArmedUntil or 0) > now()
end

function E.TryPrepull(target)
    local c, s = E.config, E.state
    if E.PendingOGCD(now()) then
        s.lastDecision = "Waiting for client to confirm last oGCD"
        return true
    end
    if E.AbilityEnabled("Reassemble") and not E.Reassembled() then
        local charges = s.charges.Reassemble or chargeState(A.Reassemble, 2)
        if (not charges.info or charges.charges >= charges.max) and
            E.TryCast(A.Reassemble, target, "Pre-pull Reassemble") then return true end
    end
    if c.usePotion and c.potionPrepull and
        E.TryPotion(nil, "Pre-pull potion: " .. tostring(s.potionName)) then return true end
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

    if not Player or not Player.alive or Player.job ~= D.MachinistJobID then s.lastDecision = "Requires Machinist" return false end
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
    E.UpdateCharges()
    if prepull then
        if E.TryPrepull(target) then return true end
        if c.requireCombat then
            s.lastDecision = "Pre-pull done: waiting for the pull"
            return false
        end
    end
    E.UpdateTTK(target, ticks)
    s.enemyCount = E.CountEnemiesNear(target)

    -- IsReady does not reflect the recast on live clients, so the GCD timer is
    -- read from cd/cdmax the same way the bot's SkillManager does.
    local gcdRemaining = E.GCDRemaining(target)
    s.gcdRemaining = gcdRemaining
    local ctx = E.BuildContext(target, gcdRemaining)

    if c.debug and ticks - (s.lastDebugAt or 0) >= 1000 and type(d) == "function" then
        s.lastDebugAt = ticks
        local function f(ac) if not ac then return "nil" end
            return string.format("cd=%s cdmax=%s isoncd=%s IsReady=%s recast=%s",
                tostring(ac.cd), tostring(ac.cdmax), tostring(ac.isoncd),
                tostring(select(2, pcall(function() return ac:IsReady(target.id) end))), tostring(ac.recasttime)) end
        d(string.format("[CielMachinist] heat=%s battery=%s overheated=%s gcdRem=%.2f weaves=%d | Split %s | Drill %s | DoubleCheck %s | lastcast=%s since=%s combo=%s/%s",
            tostring(ctx.heat), tostring(ctx.battery), tostring(ctx.overheated), gcdRemaining, s.weavesSinceGCD,
            f(action(A.HeatedSplitShot)), f(action(A.Drill)), f(action(A.DoubleCheck)),
            tostring(Player.castinginfo and Player.castinginfo.lastcastid), tostring(Player.castinginfo and Player.castinginfo.timesincecast),
            tostring(Player.lastcomboid), tostring(Player.combotimeremain)))
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

-- Seconds until the GCD is available, taken from the combo filler's cooldown.
-- Blazing Shot shortens the shared recast group to 1.5 s, so the filler
-- reports the Overheated GCD as well.
function E.GCDRemaining(target)
    local best = nil
    for _, id in ipairs({ A.HeatedSplitShot, A.SplitShot }) do
        local ac = action(id)
        if ac and tonumber(ac.cdmax) and tonumber(ac.cd) then
            local remaining = math.max(0, ac.cdmax - ac.cd)
            best = best and math.min(best, remaining) or remaining
        end
    end
    if best ~= nil then return best end
    -- No cooldown fields: fall back to readiness only.
    if ready(A.HeatedSplitShot, target and target.id) or ready(A.SplitShot, target and target.id) then return 0 end
    return 999
end

function E.OnUpdate()
    return E.Step(false)
end
