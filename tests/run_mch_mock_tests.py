#!/usr/bin/env python3
"""Offline invariants for CielMachinist's priority engine.

Three layers, all against the shipped Lua loaded verbatim:
  1. every Lua file parses;
  2. direct priority cases against a static mocked MMOMinion runtime;
  3. a time-stepped fake client (GCD, animation lock, charges, Heat, Battery,
     statuses, Wildfire hit counting) that runs the engine through the opener
     and a six-minute dummy fight and checks the rotation's shape.

Install the two lightweight test dependencies with:
    python -m pip install lupa luaparser
"""

from pathlib import Path

from lupa import LuaRuntime
from luaparser import ast


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "CielMachinist"
LUA_FILES = [
    MODULE / "CielMachinist_Data.lua",
    MODULE / "CielMachinist_Rotation.lua",
    MODULE / "CielMachinist.lua",
    MODULE / "acr" / "CielMachinist.lua",
]


def parse_all() -> None:
    for path in LUA_FILES:
        ast.parse(path.read_text(encoding="utf-8"))


STATIC_ENV = r'''
ticks = 10000
castLog = {}
Now = function() ticks = ticks + 200; return ticks end

MIsLoading = function() return false end
MIsLocked = function() return false end
MIsCasting = function() return false end
entityList = {}
EntityList = function(filter) return entityList end

target = {
    id = 200, name = "Primary", alive = true, targetable = true, incombat = true,
    distance2d = 10, los = true,
    hp = { current = 100000, max = 100000, percent = 100 }, buffs = {}, pos = { x = 0, y = 0, z = 0 },
}
Player = {
    id = 100, alive = true, job = 31, incombat = true,
    hp = { current = 100000, percent = 100 }, buffs = {}, gauge = {},
    castinginfo = { lastcastid = 0, timesincecast = 999999 },
    GetTarget = function() return target end,
}

local actions = {}
local function makeAction(id)
    local item = {
        id = id, name = "Action " .. tostring(id), usable = true,
        ready = false, cd = 0, cdmax = 0, highlighted = false, accept = true,
    }
    item.IsReady = function(self, targetID) return self.ready end
    item.Cast = function(self, targetID)
        if not self.accept then return false end
        table.insert(castLog, { id = self.id, target = targetID })
        return true
    end
    return item
end
ActionList = {
    Get = function(self, actionType, id)
        if not actions[id] then actions[id] = makeAction(id) end
        return actions[id]
    end,
    IsCasting = function() return false end,
}

local function clone(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, child in pairs(value) do result[key] = clone(child) end
    return result
end

function resetHarness()
    castLog = {}
    entityList = {}
    for _, item in pairs(actions) do
        item.ready = false
        item.highlighted = false
        item.accept = true
        item.cd, item.cdmax, item.isoncd, item.recasttime = 0, 0, nil, nil
    end
    Player.gauge = {}
    Player.buffs = {}
    Player.lastcomboid, Player.combotimeremain = nil, nil
    Player.hp.percent = 100
    Player.castinginfo = { lastcastid = 0, timesincecast = 999999 }
    target.buffs = {}
    local config = clone(CielMachinistData.Defaults)
    config.requestThrottleMs = 0
    config.pulseMs = 0
    config.requestDedupeMs = 0
    config.requireCombat = false
    CielMachinistEngine.Init(config)
    return config
end

function setReady(id, value)
    ActionList:Get(1, id).ready = value ~= false
end

-- A charged action: `charges` banked of `max`, `into` seconds into the next one.
function setCharges(id, charges, max, recast, into)
    local ac = ActionList:Get(1, id)
    ac.recasttime = recast
    if charges >= max then
        ac.cd, ac.cdmax, ac.isoncd = 0, 0, false
    else
        ac.cd, ac.cdmax, ac.isoncd = charges * recast + (into or 0), max * recast, true
    end
end

-- A plain cooldown with `remaining` seconds left.
function setCooldown(id, remaining, recast)
    local ac = ActionList:Get(1, id)
    ac.recasttime = recast
    if remaining <= 0 then
        ac.cd, ac.cdmax, ac.isoncd = 0, 0, false
    else
        ac.cd, ac.cdmax, ac.isoncd = recast - remaining, recast, true
    end
end

function setStatus(id, remaining)
    table.insert(Player.buffs, { id = id, ownerid = 100, duration = remaining })
end

function lastCastID()
    return #castLog > 0 and castLog[#castLog].id or 0
end

function lastCastTarget()
    return #castLog > 0 and castLog[#castLog].target or 0
end

-- Everything on a long cooldown and nothing pending: the quiet mid-fight state.
function quietCooldowns()
    local A = CielMachinistData.Actions
    setCooldown(A.AirAnchor, 30, 40)
    setCooldown(A.ChainSaw, 40, 60)
    setCharges(A.Drill, 0, 2, 20, 2)
    setCooldown(A.Wildfire, 90, 120)
    setCooldown(A.BarrelStabilizer, 90, 120)
    setCharges(A.Reassemble, 1, 2, 55, 10)
    setCharges(A.DoubleCheck, 1, 3, 30, 5)
    setCharges(A.Checkmate, 1, 3, 30, 5)
    CielMachinistEngine.UpdateCharges()
end

function directContext()
    return {
        target = target, ttk = 999, terminal = false, idealFinish = false,
        enemies = 1, aoe = false, nextBurst = 90,
        burstElapsed = 999, burstActive = false, burstConfigured = true,
        ttkBand = "SUSTAIN", heat = 0, battery = 0, overheated = false, gcdRemaining = 1.5,
    }
end
'''

STATIC_SUITE = r'''
local A = CielMachinistData.Actions
local ST = CielMachinistData.Statuses
local E = CielMachinistEngine

local function expect(condition, message)
    if not condition then error(message, 2) end
end

-- Optimized damage defaults are on; utility and potion are opt-in.
local c = resetHarness()
expect(E.AbilityEnabled("Drill"), "optimized Drill default should be enabled")
expect(not E.AbilityEnabled("SecondWind"), "utility should remain disabled by default")
expect(not E.AbilityEnabled("Tactician"), "Tactician should remain disabled by default")
expect(not c.usePotion, "potion use must be opt-in")
expect(not c.enabled, "execution must be off by default")

----------------------------------------------------------------------------
-- GCD priority.
----------------------------------------------------------------------------

-- Blazing Shot outranks every tool: it is only ready while Overheated.
c = resetHarness()
quietCooldowns()
setReady(A.BlazingShot)
setReady(A.AirAnchor)
setReady(A.Drill)
expect(E.TryGCD(directContext()), "overheated GCD should cast")
expect(lastCastID() == A.BlazingShot, "Blazing Shot must outrank tools while Overheated")

-- Air Anchor, then a capped Drill, then Chain Saw, Excavator, Drill.
c = resetHarness()
quietCooldowns()
setCharges(A.Drill, 2, 2, 20)
E.UpdateCharges()
setReady(A.AirAnchor) setReady(A.Drill) setReady(A.ChainSaw) setReady(A.HeatedSplitShot)
expect(E.TryGCD(directContext()) and lastCastID() == A.AirAnchor, "Air Anchor goes first")
setReady(A.AirAnchor, false)
expect(E.TryGCD(directContext()) and lastCastID() == A.Drill, "a capped Drill outranks Chain Saw")
setCharges(A.Drill, 1, 2, 20, 1)
E.UpdateCharges()
expect(E.TryGCD(directContext()) and lastCastID() == A.ChainSaw, "Chain Saw outranks an uncapped Drill")
setReady(A.ChainSaw, false)
setReady(A.Excavator)
expect(E.TryGCD(directContext()) and lastCastID() == A.Excavator, "Excavator outranks an uncapped Drill")
setReady(A.Excavator, false)
expect(E.TryGCD(directContext()) and lastCastID() == A.Drill, "Drill outranks the combo")

-- Tool Off falls through without stalling.
c = resetHarness()
quietCooldowns()
c.advancedEnabled = true
c.abilities.Drill = false
setReady(A.Drill) setReady(A.HeatedSplitShot)
expect(E.TryGCD(directContext()) and lastCastID() == A.HeatedSplitShot, "Drill Off should fall through to the combo")

-- Level-sync fallback: Split Shot is the permanent final filler.
c = resetHarness()
quietCooldowns()
setReady(A.SplitShot)
expect(E.TryGCD(directContext()) and lastCastID() == A.SplitShot, "Split Shot should be the final GCD fallback")

-- Combo follows the client's combo state, then the highlight, then the local tracker.
c = resetHarness()
quietCooldowns()
setReady(A.HeatedSplitShot) setReady(A.HeatedSlugShot) setReady(A.HeatedCleanShot)
expect(E.NextComboStep() == 1, "no combo state starts at Split Shot")
Player.lastcomboid, Player.combotimeremain = A.HeatedSplitShot, 20
expect(E.TryGCD(directContext()) and lastCastID() == A.HeatedSlugShot, "lastcomboid Split -> Slug")
Player.lastcomboid = A.HeatedSlugShot
expect(E.TryGCD(directContext()) and lastCastID() == A.HeatedCleanShot, "lastcomboid Slug -> Clean")
Player.lastcomboid = A.HeatedCleanShot
expect(E.TryGCD(directContext()) and lastCastID() == A.HeatedSplitShot, "lastcomboid Clean -> Split")
Player.combotimeremain = 0.2
Player.lastcomboid = A.HeatedSplitShot
expect(E.NextComboStep() == 1, "an expiring combo restarts")
Player.lastcomboid, Player.combotimeremain = nil, nil
ActionList:Get(1, A.HeatedCleanShot).highlighted = true
expect(E.NextComboStep() == 3, "a highlighted Clean Shot wins")
ActionList:Get(1, A.HeatedCleanShot).highlighted = false
-- Local tracker from observed casts only.
Player.castinginfo = { lastcastid = A.HeatedSplitShot, timesincecast = 100 }
E.ObserveLastCast()
expect(E.NextComboStep() == 2, "tracker: Split observed -> Slug")
Player.castinginfo = { lastcastid = A.Drill, timesincecast = 100 }
E.ObserveLastCast()
expect(E.NextComboStep() == 2, "tracker: Drill does not break the combo")
Player.castinginfo = { lastcastid = A.HeatedSlugShot, timesincecast = 100 }
E.ObserveLastCast()
expect(E.NextComboStep() == 3, "tracker: Slug observed -> Clean")
Player.castinginfo = { lastcastid = A.HeatedCleanShot, timesincecast = 100 }
E.ObserveLastCast()
expect(E.NextComboStep() == 1, "tracker: Clean observed -> Split")

-- Full Metal Field is pressed as soon as it is granted; it never waits.
c = resetHarness()
quietCooldowns()
setCooldown(A.Wildfire, 0, 120)
setStatus(ST.FullMetalMachinist, 25)
setReady(A.FullMetalField) setReady(A.HeatedSplitShot)
expect(E.TryGCD(directContext()) and lastCastID() == A.FullMetalField, "Full Metal Field outranks the combo")

----------------------------------------------------------------------------
-- AoE thresholds.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setReady(A.Scattergun) setReady(A.HeatedSplitShot)
local ctx = directContext()
ctx.enemies = 2
expect(E.TryGCD(ctx) and lastCastID() == A.HeatedSplitShot, "Scattergun must wait for three targets")
ctx.enemies = 3
expect(E.TryGCD(ctx) and lastCastID() == A.Scattergun, "Scattergun fires at three targets")
c.useAOE = false
expect(E.TryGCD(ctx) and lastCastID() == A.HeatedSplitShot, "AoE master switch Off disables Scattergun")

-- Auto Crossbow gives no Double Check / Checkmate refund, so it needs six.
c = resetHarness()
quietCooldowns()
setReady(A.AutoCrossbow) setReady(A.BlazingShot)
ctx = directContext()
ctx.enemies = 5
expect(E.TryGCD(ctx) and lastCastID() == A.BlazingShot, "Blazing Shot below six targets")
ctx.enemies = 6
expect(E.TryGCD(ctx) and lastCastID() == A.AutoCrossbow, "Auto Crossbow at six targets")

-- Bioblaster takes the Drill slot at three targets only while its DoT is down.
c = resetHarness()
quietCooldowns()
setCharges(A.Drill, 1, 2, 20, 1)
E.UpdateCharges()
setReady(A.Bioblaster) setReady(A.Drill)
ctx = directContext()
ctx.enemies = 3
expect(E.TryGCD(ctx) and lastCastID() == A.Bioblaster, "Bioblaster at three targets")
target.buffs = { { id = ST.Bioblaster, ownerid = 100, duration = 12 } }
expect(E.TryGCD(ctx) and lastCastID() == A.Drill, "Drill while the Bioblaster DoT is running")
target.buffs = {}

----------------------------------------------------------------------------
-- Hypercharge.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setReady(A.Hypercharge)
E.state.weavesSinceGCD = 0
ctx = directContext()
ctx.heat = 50
expect(E.HyperchargeAllowed(ctx), "Hypercharge with quiet tools")

setCooldown(A.AirAnchor, 6, 40)
expect(not E.HyperchargeAllowed(ctx), "Air Anchor due inside Overheated blocks Hypercharge")
setCooldown(A.AirAnchor, 30, 40)
setCooldown(A.ChainSaw, 7.5, 60)
expect(not E.HyperchargeAllowed(ctx), "Chain Saw due inside Overheated blocks Hypercharge")
setCooldown(A.ChainSaw, 40, 60)

-- One Drill charge is fine; a Drill stack that would cap is not.
setCharges(A.Drill, 1, 2, 20, 5)
E.UpdateCharges()
expect(E.HyperchargeAllowed(ctx), "one banked Drill charge does not block Hypercharge")
setCharges(A.Drill, 1, 2, 20, 15)
E.UpdateCharges()
expect(not E.HyperchargeAllowed(ctx), "a Drill stack about to cap blocks Hypercharge")
setCharges(A.Drill, 0, 2, 20, 2)
E.UpdateCharges()

-- Pending granted weaponskills go first.
setStatus(ST.ExcavatorReady, 20)
expect(not E.HyperchargeAllowed(ctx), "Excavator Ready blocks Hypercharge")
Player.buffs = {}
setStatus(ST.FullMetalMachinist, 20)
expect(not E.HyperchargeAllowed(ctx), "Full Metal Machinist blocks Hypercharge")
Player.buffs = {}

-- Already Overheated, or nothing to spend it on.
ctx.overheated = true
expect(not E.HyperchargeAllowed(ctx), "no Hypercharge while Overheated")
ctx.overheated = false
c.advancedEnabled = true
c.abilities.BlazingShot = false
c.abilities.AutoCrossbow = false
expect(not E.HyperchargeAllowed(ctx), "no Hypercharge with both Overheated weaponskills Off")
expect(#E.GetConfigurationWarnings() >= 1, "that configuration should warn")
c.abilities.BlazingShot = true

-- Kept for a Wildfire that is nearly up, unless pooling is off or the fight is ending.
setCooldown(A.Wildfire, 8, 120)
expect(not E.HyperchargeAllowed(ctx), "Hypercharge is kept for an imminent Wildfire")
ctx.terminal = true
expect(E.HyperchargeAllowed(ctx), "terminal band ignores the Wildfire hold")
ctx.terminal = false
c.resourcePooling = false
expect(E.HyperchargeAllowed(ctx), "pooling Off ignores the Wildfire hold")
c.resourcePooling = true
setCooldown(A.Wildfire, 0, 120)
expect(E.HyperchargeAllowed(ctx), "a ready Wildfire releases Hypercharge")
setCooldown(A.Wildfire, 90, 120)

-- Hypercharged about to expire bypasses every hold.
setStatus(ST.Hypercharged, 3)
setCooldown(A.AirAnchor, 2, 40)
expect(E.HyperchargeAllowed(ctx), "an expiring Hypercharged is never wasted")
Player.buffs = {}

----------------------------------------------------------------------------
-- Wildfire pairing.
----------------------------------------------------------------------------

-- Wildfire goes out right behind Hypercharge, in the same 2.5 s window.
c = resetHarness()
quietCooldowns()
setCooldown(A.Wildfire, 0, 120)
setReady(A.Wildfire) setReady(A.Hypercharge)
E.state.weavesSinceGCD = 0
ctx = directContext()
expect(not E.WildfireAllowed(ctx), "Wildfire waits for Hypercharge")
expect(E.TryOGCD(ctx) and lastCastID() == A.Hypercharge, "Hypercharge goes out first")
setReady(A.Hypercharge, false)
E.state.weavesSinceGCD = 1
ctx = E.BuildContext(target, 1.5)
expect(ctx.overheated, "an accepted Hypercharge counts as Overheated before the status shows")
expect(E.TryOGCD(ctx) and lastCastID() == A.Wildfire, "Wildfire shares Hypercharge's weave window")

-- A mostly spent Overheated window is left for the next Hypercharge.
c = resetHarness()
quietCooldowns()
setCooldown(A.Wildfire, 0, 120)
setReady(A.Wildfire)
ctx = directContext()
ctx.overheated = true
E.state.overheatStacks = 2
expect(not E.WildfireAllowed(ctx), "two Blazing Shots left: Wildfire waits")
ctx.terminal = true
expect(E.WildfireAllowed(ctx), "unless the fight is ending")
ctx.terminal = false
E.state.overheatStacks = 5
expect(E.WildfireAllowed(ctx), "a fresh Overheated window takes Wildfire")
ctx.ttk = 5
expect(not E.WildfireAllowed(ctx), "Wildfire is skipped under its TTK floor")
-- Without Hypercharge it is simply used on cooldown.
ctx = directContext()
c.advancedEnabled = true
c.abilities.Hypercharge = false
expect(E.WildfireAllowed(ctx), "Wildfire on cooldown when Hypercharge is Off")

----------------------------------------------------------------------------
-- Reassemble.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setReady(A.Reassemble)
E.state.weavesSinceGCD = 0
ctx = directContext()
expect(not E.ReassembleAllowed(ctx), "no Reassemble when the next GCD is a combo filler")
setCooldown(A.AirAnchor, 1.0, 40)
ctx.gcdRemaining = 1.2
ctx.nextBurst = 90
expect(E.ReassembleAllowed(ctx), "Reassemble ahead of Air Anchor")
setStatus(ST.Reassembled, 4)
expect(not E.ReassembleAllowed(ctx), "never double Reassemble")
Player.buffs = {}
ctx.overheated = true
expect(not E.ReassembleAllowed(ctx), "never Reassemble a Blazing Shot")
ctx.overheated = false
-- Pooling: spending the only charge 20 s before burst would leave none.
ctx.nextBurst = 20
expect(not E.ReassembleAllowed(ctx), "Reassemble is kept for the burst")
setCharges(A.Reassemble, 2, 2, 55)
E.UpdateCharges()
expect(E.ReassembleAllowed(ctx), "a capped Reassemble is always spent")
-- Full Metal Field is already a guaranteed critical direct hit.
setCooldown(A.AirAnchor, 30, 40)
setStatus(ST.FullMetalMachinist, 20)
expect(not E.ReassembleAllowed(ctx), "Full Metal Field alone never takes Reassemble")
Player.buffs = {}

----------------------------------------------------------------------------
-- Automaton Queen.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
ctx = directContext()
ctx.battery = 40
expect(not E.QueenAllowed(ctx), "no Queen under 50 battery")
ctx.battery = 60
ctx.nextBurst = 90
expect(not E.QueenAllowed(ctx), "off-cycle Queen waits for a near-full battery")
ctx.battery = 90
expect(E.QueenAllowed(ctx), "off-cycle Queen near the cap")
ctx.battery = 60
ctx.nextBurst = 50
expect(E.QueenAllowed(ctx), "last call just ahead of the refill window")
ctx.nextBurst = 30
ctx.battery = 80
expect(not E.QueenAllowed(ctx), "battery is kept when the burst is inside the refill window")
ctx.battery = 100
expect(E.QueenAllowed(ctx), "a full battery is never sat on")
ctx.battery = 60
ctx.nextBurst = 110
ctx.burstActive = true
expect(E.QueenAllowed(ctx), "Queen inside the burst at any legal battery")
setCooldown(A.ChainSaw, 4, 60)
expect(not E.QueenAllowed(ctx), "but a Chain Saw that is about to land tops her off first")
ctx.battery = 100
expect(E.QueenAllowed(ctx), "unless the battery is already full")
setCooldown(A.ChainSaw, 40, 60)
ctx.battery = 60
ctx.burstActive = false
ctx.ttk = 6
expect(not E.QueenAllowed(ctx), "Queen is skipped under her TTK floor")
-- A miscalibrated gauge index must not silence her.
Player.gauge = {}
setReady(A.AutomatonQueen)
expect(E.GetBattery() == 50, "battery reads as 50 whenever the summon is ready")

----------------------------------------------------------------------------
-- Double Check / Checkmate.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setCharges(A.DoubleCheck, 1, 3, 30, 5)
setCharges(A.Checkmate, 2, 3, 30, 5)
E.UpdateCharges()
setReady(A.DoubleCheck) setReady(A.Checkmate)
E.state.weavesSinceGCD = 0
ctx = directContext()
expect(E.TryOGCD(ctx) and lastCastID() == A.Checkmate, "the fuller stack is spent first")
setCharges(A.DoubleCheck, 2, 3, 30, 5)
setCharges(A.Checkmate, 1, 3, 30, 5)
E.UpdateCharges()
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx) and lastCastID() == A.DoubleCheck, "and the other one next")
-- Pooled just before the burst unless a stack would cap.
ctx.nextBurst = 10
E.state.weavesSinceGCD = 0
local before = #castLog
expect(not E.TryOGCD(ctx) and #castLog == before, "charges are pooled just before the burst")
setCharges(A.DoubleCheck, 3, 3, 30)
E.UpdateCharges()
expect(E.TryOGCD(ctx) and lastCastID() == A.DoubleCheck, "a capped stack is spent even while pooling")

-- Overheated allows exactly one weave.
c = resetHarness()
quietCooldowns()
setReady(A.DoubleCheck) setReady(A.Checkmate)
ctx = directContext()
ctx.overheated = true
E.state.lastGCDID = A.BlazingShot
E.state.weavesSinceGCD = 1
expect(not E.TryOGCD(ctx), "single weave behind a Blazing Shot")
E.state.lastGCDID = A.FullMetalField
expect(E.TryOGCD(ctx), "double weave behind a 2.5 s weaponskill, even once Overheated")

----------------------------------------------------------------------------
-- Execution modes and the pending-request guard.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
c.enabled = true
c.advancedEnabled = true
c.executionMode = "GCD_ONLY"
setReady(A.DoubleCheck)
local split = ActionList:Get(1, A.HeatedSplitShot)
split.cd, split.cdmax = 0.5, 2.5
E.OnUpdate()
expect(#castLog == 0, "GCD-only mode emitted an oGCD")

c = resetHarness()
quietCooldowns()
c.requestDedupeMs = 350
setReady(A.HeatedSplitShot)
expect(E.TryGCD(directContext()) and #castLog == 1, "first request goes out")
expect(E.TryGCD(directContext()) and #castLog == 1, "the GCD tier is held while the request is unconfirmed")
Player.castinginfo = { lastcastid = A.HeatedSplitShot, timesincecast = 50 }
E.ObserveLastCast()
expect(E.TryGCD(directContext()) and #castLog == 2, "an observed cast lifts the hold")
-- An explicit rejection drops the guard at once.
c = resetHarness()
quietCooldowns()
c.requestDedupeMs = 350
setReady(A.HeatedSplitShot)
ActionList:Get(1, A.HeatedSplitShot).accept = false
expect(not E.TryGCD(directContext()) and #castLog == 0, "a rejected request is not logged")
ActionList:Get(1, A.HeatedSplitShot).accept = true
expect(E.TryGCD(directContext()) and #castLog == 1, "and the next pulse may retry immediately")

-- Self-targeted actions are requested on the player.
c = resetHarness()
quietCooldowns()
setReady(A.BarrelStabilizer)
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(directContext()) and lastCastID() == A.BarrelStabilizer, "Barrel Stabilizer on cooldown")
expect(lastCastTarget() == 100, "Barrel Stabilizer must be requested on the player")

-- Wrong job does nothing.
c = resetHarness()
c.enabled = true
Player.job = 23
setReady(A.HeatedSplitShot)
E.OnUpdate()
expect(#castLog == 0, "the engine must not act on another job")
Player.job = 31
'''


# A time-stepped imitation of the live client: the engine is driven pulse by
# pulse and every game rule that shapes the Machinist rotation is enforced
# here, so the assertions below are about what the engine actually pressed.
TIMELINE_ENV = r'''
local A = CielMachinistData.Actions
local ST = CielMachinistData.Statuses

clock = 0                -- milliseconds
Now = function() return clock end
MIsLoading = function() return false end
MIsLocked = function() return false end
MIsCasting = function() return false end
EntityList = function() return {} end

sim = {
    heat = 0, battery = 0, gcdReadyAt = 0, gcdTotal = 2500, lockUntil = 0,
    statuses = {}, overheatStacks = 0, lastCastAt = -999999, lastCastID = 0,
    comboID = 0, comboUntil = 0, queenBusyUntil = 0, wildfireHits = 0,
    log = {}, wildfires = {}, queens = {}, reassembled = {},
    wasted = { heat = 0, battery = 0 }, idle = { gcd = 0, drillCapped = 0, AirAnchor = 0, ChainSaw = 0 },
    capped = { DoubleCheck = 0, Checkmate = 0, Reassemble = 0 },
}

local target = { id = 200, name = "Dummy", alive = true, targetable = true, incombat = true,
    distance2d = 10, los = true, hp = { current = 1e9, max = 1e9, percent = 100 }, buffs = {},
    pos = { x = 0, y = 0, z = 0 } }
Player = { id = 100, alive = true, job = 31, incombat = true, hp = { current = 1, percent = 100 },
    buffs = {}, gauge = { 0, 0 }, castinginfo = { lastcastid = 0, timesincecast = 999999 },
    GetTarget = function() return target end }

local function status(id) return (sim.statuses[id] or 0) > clock end
local function grant(id, seconds) sim.statuses[id] = clock + seconds * 1000 end
local function strip(id) sim.statuses[id] = nil end

-- recast = own cooldown in seconds, max = charges, gcd = weaponskill
local defs = {
    [A.HeatedSplitShot] = { gcd = true, heat = 5, combo = 1 },
    [A.HeatedSlugShot] = { gcd = true, heat = 5, combo = 2 },
    [A.HeatedCleanShot] = { gcd = true, heat = 5, battery = 10, combo = 3 },
    [A.Drill] = { gcd = true, recast = 20, max = 2 },
    [A.AirAnchor] = { gcd = true, recast = 40, max = 1, battery = 20 },
    [A.ChainSaw] = { gcd = true, recast = 60, max = 1, battery = 20,
        effect = function() grant(ST.ExcavatorReady, 30) end },
    [A.Excavator] = { gcd = true, battery = 20, need = function() return status(ST.ExcavatorReady) end,
        effect = function() strip(ST.ExcavatorReady) end },
    [A.FullMetalField] = { gcd = true, need = function() return status(ST.FullMetalMachinist) end,
        effect = function() strip(ST.FullMetalMachinist) end, keepsReassemble = true },
    [A.BlazingShot] = { gcd = true, gcdTotal = 1500, need = function() return sim.overheatStacks > 0 and status(ST.Overheated) end,
        effect = function()
            sim.overheatStacks = sim.overheatStacks - 1
            if sim.overheatStacks <= 0 then strip(ST.Overheated) end
            for _, id in ipairs({ A.DoubleCheck, A.Checkmate }) do
                local st = sim.cd[id]
                st.charges = math.min(st.max, st.charges + 15 / st.recast)
            end
        end },
    [A.Hypercharge] = { recast = 10, max = 1, selfOnly = true,
        need = function() return (sim.heat >= 50 or status(ST.Hypercharged)) and not status(ST.Overheated) end,
        effect = function()
            if status(ST.Hypercharged) then strip(ST.Hypercharged) else sim.heat = sim.heat - 50 end
            grant(ST.Overheated, 10)
            sim.overheatStacks = 5
        end },
    [A.Wildfire] = { recast = 120, max = 1, effect = function()
            grant(ST.WildfireSelf, 10)
            sim.wildfireHits = 0
            sim.wildfireOpenAt = clock
        end },
    [A.BarrelStabilizer] = { recast = 120, max = 1, selfOnly = true, effect = function()
            grant(ST.Hypercharged, 30)
            grant(ST.FullMetalMachinist, 30)
        end },
    [A.Reassemble] = { recast = 55, max = 2, selfOnly = true, effect = function() grant(ST.Reassembled, 5) end },
    [A.DoubleCheck] = { recast = 30, max = 3 },
    [A.Checkmate] = { recast = 30, max = 3 },
    [A.AutomatonQueen] = { recast = 6, max = 1, selfOnly = true,
        need = function() return sim.battery >= 50 and clock >= sim.queenBusyUntil end,
        effect = function()
            table.insert(sim.queens, { t = clock / 1000, battery = sim.battery })
            sim.battery = 0
            sim.queenBusyUntil = clock + 21000
        end },
}

sim.cd = {}
for id, def in pairs(defs) do
    if def.recast then sim.cd[id] = { charges = def.max, max = def.max, recast = def.recast } end
end

local names = {}
for name, id in pairs(A) do names[id] = name end
function actionName(id) return names[id] or tostring(id) end

local objects = {}
local function makeAction(id)
    local def = defs[id]
    local ac = { id = id, name = actionName(id), usable = def ~= nil, highlighted = false }
    if not def then
        ac.IsReady = function() return false end
        ac.Cast = function() return false end
        return ac
    end
    local function refresh()
        local st = sim.cd[id]
        if st then
            ac.recasttime = st.recast
            if st.charges >= st.max then
                ac.cd, ac.cdmax, ac.isoncd = 0, 0, false
            else
                ac.cd, ac.cdmax, ac.isoncd = st.charges * st.recast, st.max * st.recast, true
            end
        else
            ac.recasttime = sim.gcdTotal / 1000
            local remaining = math.max(0, sim.gcdReadyAt - clock)
            if remaining <= 0 then
                ac.cd, ac.cdmax, ac.isoncd = 0, 0, false
            else
                ac.cd, ac.cdmax, ac.isoncd = (sim.gcdTotal - remaining) / 1000, sim.gcdTotal / 1000, true
            end
        end
    end
    ac.refresh = refresh
    ac.IsReady = function(self, targetID)
        if def.selfOnly and targetID ~= Player.id then return false end
        if not def.selfOnly and targetID ~= target.id then return false end
        if clock < sim.lockUntil then return false end
        if def.gcd and sim.gcdReadyAt - clock > 60 then return false end
        local st = sim.cd[id]
        if st and st.charges < 1 then return false end
        if def.need and not def.need() then return false end
        return true
    end
    ac.Cast = function(self, targetID)
        if not self:IsReady(targetID) then return false end
        local st = sim.cd[id]
        if st then st.charges = st.charges - 1 end
        if def.gcd then
            sim.gcdTotal = def.gcdTotal or 2500
            sim.gcdReadyAt = math.max(clock, sim.gcdReadyAt) + sim.gcdTotal
            if status(ST.WildfireSelf) then sim.wildfireHits = sim.wildfireHits + 1 end
            if status(ST.Reassembled) and not def.keepsReassemble then
                strip(ST.Reassembled)
                table.insert(sim.reassembled, actionName(id))
            end
            if def.combo then
                local continues = def.combo == 1 or (sim.comboID == def.combo - 1 and clock < sim.comboUntil)
                sim.comboOK = continues
                sim.comboID = continues and def.combo % 3 or 0
                sim.comboUntil = clock + 30000
                Player.lastcomboid = sim.comboID > 0 and id or 0
                if not continues then sim.brokenCombos = (sim.brokenCombos or 0) + 1 end
            end
        end
        local gainHeat, gainBattery = def.heat or 0, def.battery or 0
        if def.combo and def.combo > 1 and not sim.comboOK then gainHeat, gainBattery = 0, 0 end
        sim.wasted.heat = sim.wasted.heat + math.max(0, sim.heat + gainHeat - 100)
        sim.wasted.battery = sim.wasted.battery + math.max(0, sim.battery + gainBattery - 100)
        sim.heat = math.min(100, sim.heat + gainHeat)
        sim.battery = math.min(100, sim.battery + gainBattery)
        if def.effect then def.effect() end
        sim.lockUntil = clock + 600
        sim.lastCastAt, sim.lastCastID = clock, id
        table.insert(sim.log, { t = clock / 1000, id = id, name = actionName(id), gcd = def.gcd == true,
            heat = sim.heat, battery = sim.battery })
        return true
    end
    return ac
end

ActionList = {
    Get = function(self, actionType, id)
        if not objects[id] then objects[id] = makeAction(id) end
        if objects[id].refresh then objects[id].refresh() end
        return objects[id]
    end,
    IsCasting = function() return false end,
}

function advance(ms)
    local dt = ms / 1000
    -- idle accounting before the clock moves
    if clock >= sim.gcdReadyAt and clock >= sim.lockUntil then sim.idle.gcd = sim.idle.gcd + dt end
    if sim.cd[A.Drill].charges >= 2 then sim.idle.drillCapped = sim.idle.drillCapped + dt end
    for _, key in ipairs({ "AirAnchor", "ChainSaw" }) do
        if sim.cd[A[key]].charges >= 1 then sim.idle[key] = sim.idle[key] + dt end
    end
    for _, key in ipairs({ "DoubleCheck", "Checkmate", "Reassemble" }) do
        if sim.cd[A[key]].charges >= sim.cd[A[key]].max then sim.capped[key] = sim.capped[key] + dt end
    end
    clock = clock + ms
    for _, st in pairs(sim.cd) do
        if st.charges < st.max then st.charges = math.min(st.max, st.charges + dt / st.recast) end
    end
    if sim.wildfireOpenAt and not status(ST.WildfireSelf) then
        table.insert(sim.wildfires, { t = sim.wildfireOpenAt / 1000, hits = math.min(6, sim.wildfireHits) })
        sim.wildfireOpenAt = nil
    end
    if not status(ST.Overheated) then sim.overheatStacks = 0 end
    Player.buffs = {}
    for id, untilAt in pairs(sim.statuses) do
        if untilAt > clock then
            table.insert(Player.buffs, { id = id, ownerid = Player.id, duration = (untilAt - clock) / 1000 })
        end
    end
    Player.gauge = { sim.heat, sim.battery }
    Player.combotimeremain = math.max(0, (sim.comboUntil - clock) / 1000)
    Player.castinginfo = { lastcastid = sim.lastCastID, timesincecast = clock - sim.lastCastAt }
end

function run(seconds)
    local untilAt = clock + seconds * 1000
    while clock < untilAt do
        CielMachinistEngine.Step(true)
        advance(30)
    end
end

function gcdNames(count)
    local out = {}
    for _, entry in ipairs(sim.log) do
        if entry.gcd then table.insert(out, entry.name) end
        if #out >= count then break end
    end
    return table.concat(out, ",")
end

function countCasts(name, fromSeconds, toSeconds)
    local total = 0
    for _, entry in ipairs(sim.log) do
        if entry.name == name and entry.t >= (fromSeconds or 0) and entry.t < (toSeconds or 1e9) then total = total + 1 end
    end
    return total
end

-- Largest number of oGCDs between two consecutive weaponskills, split by
-- whether the preceding weaponskill was a Blazing Shot.
function maxWeaves()
    local normal, overheated, current, afterBlazing = 0, 0, 0, false
    for _, entry in ipairs(sim.log) do
        if entry.gcd then
            current, afterBlazing = 0, entry.name == "BlazingShot"
        else
            current = current + 1
            if afterBlazing then overheated = math.max(overheated, current)
            else normal = math.max(normal, current) end
        end
    end
    return normal, overheated
end

function dumpLog(toSeconds)
    local lines = {}
    for _, entry in ipairs(sim.log) do
        if entry.t <= toSeconds then
            table.insert(lines, string.format("%6.2f %s%s  heat=%d battery=%d", entry.t,
                entry.gcd and "" or "    ", entry.name, entry.heat, entry.battery))
        end
    end
    return table.concat(lines, "\n")
end
'''


def run_static() -> None:
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((MODULE / "CielMachinist_Data.lua").read_text(encoding="utf-8"))
    lua.execute(STATIC_ENV)
    lua.execute((MODULE / "CielMachinist_Rotation.lua").read_text(encoding="utf-8"))
    lua.execute(STATIC_SUITE)


def run_timeline(verbose: bool = False) -> None:
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((MODULE / "CielMachinist_Data.lua").read_text(encoding="utf-8"))
    lua.execute(TIMELINE_ENV)
    lua.execute((MODULE / "CielMachinist_Rotation.lua").read_text(encoding="utf-8"))
    lua.execute('''
        local config = {}
        local function clone(v) if type(v) ~= "table" then return v end
            local r = {} for k, c in pairs(v) do r[k] = clone(c) end return r end
        config = clone(CielMachinistData.Defaults)
        CielMachinistEngine.Init(config)
    ''')

    # --- Opener -------------------------------------------------------------
    lua.execute("run(30)")
    if verbose:
        print(lua.eval("dumpLog(30)"))
    opener = lua.eval("gcdNames(12)")
    expected = ("AirAnchor,Drill,ChainSaw,Excavator,Drill,FullMetalField,"
                "BlazingShot,BlazingShot,BlazingShot,BlazingShot,BlazingShot,Drill")
    assert opener == expected, f"opener GCDs were {opener}\n{lua.eval('dumpLog(30)')}"

    order = [entry.name for entry in lua.eval("sim.log").values()]
    wildfire, fmf, hyper = order.index("Wildfire"), order.index("FullMetalField"), order.index("Hypercharge")
    assert fmf < hyper and wildfire == hyper + 1 and wildfire < order.index("BlazingShot"), \
        "opener must go Full Metal Field -> Hypercharge -> Wildfire -> Blazing Shot"
    assert order.index("BarrelStabilizer") < order.index("ChainSaw"), "Barrel Stabilizer opens the burst"
    assert lua.eval("sim.wildfires[1].hits") == 6, "the opener Wildfire must catch six weaponskills"
    assert lua.eval("sim.queens[1].battery") == 60, "the opener Queen goes out at 60 battery"
    assert lua.eval("sim.queens[1].t") < 12, "the opener Queen must not be late"
    assert lua.eval("#sim.reassembled") == 2, "both Reassemble charges are spent in the opener"
    for index in (1, 2):
        name = lua.eval(f"sim.reassembled[{index}]")
        assert name in ("Drill", "AirAnchor", "ChainSaw", "Excavator"), f"Reassemble landed on {name}"
    print("opener ok")

    # --- Six-minute dummy fight ---------------------------------------------
    lua.execute("run(330)")
    seconds = lua.eval("clock / 1000")
    normal, overheated = lua.eval("maxWeaves()")
    assert normal <= 2, f"{normal} weaves after an ordinary weaponskill"
    assert overheated <= 1, f"{overheated} weaves after a Blazing Shot"

    stats = {
        "gcd idle": lua.eval("sim.idle.gcd"),
        "Drill capped": lua.eval("sim.idle.drillCapped"),
        "Air Anchor idle": lua.eval("sim.idle.AirAnchor"),
        "Chain Saw idle": lua.eval("sim.idle.ChainSaw"),
        "Double Check capped": lua.eval("sim.capped.DoubleCheck"),
        "Checkmate capped": lua.eval("sim.capped.Checkmate"),
        "Reassemble capped": lua.eval("sim.capped.Reassemble"),
        "heat wasted": lua.eval("sim.wasted.heat"),
        "battery wasted": lua.eval("sim.wasted.battery"),
    }
    casts = {name: lua.eval(f'countCasts("{name}")') for name in (
        "Drill", "AirAnchor", "ChainSaw", "Excavator", "FullMetalField", "BlazingShot", "Hypercharge",
        "Wildfire", "BarrelStabilizer", "Reassemble", "DoubleCheck", "Checkmate", "AutomatonQueen")}
    if verbose:
        for key, value in stats.items():
            print(f"  {key:22s} {value:8.2f}")
        for key, value in casts.items():
            print(f"  {key:22s} {value:5d}")
        print("  wildfire hits:", [w.hits for w in lua.eval("sim.wildfires").values()])
        print("  queen battery:", [q.battery for q in lua.eval("sim.queens").values()])

    # The GCD never sits idle, and no tool drifts by more than a GCD or two per use.
    assert stats["gcd idle"] < 0.02 * seconds, stats
    assert stats["Drill capped"] < 6, stats          # the pull itself starts capped
    assert stats["Air Anchor idle"] <= 2.6 * casts["AirAnchor"], stats
    assert stats["Chain Saw idle"] <= 2.6 * casts["ChainSaw"] + 3, stats
    assert lua.eval("sim.brokenCombos or 0") == 0, "the combo must never be broken"

    # Cooldowns are used at their natural rate over 360 s.
    assert casts["BarrelStabilizer"] == 3 and casts["Wildfire"] == 3, casts
    assert casts["FullMetalField"] == 3, casts
    assert casts["AirAnchor"] >= 9 and casts["ChainSaw"] >= 6 and casts["Excavator"] == casts["ChainSaw"], casts
    assert casts["Drill"] >= 18, casts
    assert casts["BlazingShot"] == 5 * casts["Hypercharge"], "every Hypercharge fits five Blazing Shots"
    assert casts["Reassemble"] >= 7, casts

    # Every Wildfire catches six weaponskills.
    hits = [w.hits for w in lua.eval("sim.wildfires").values()]
    assert hits == [6, 6, 6], f"Wildfire hits were {hits}"
    # Reassemble never lands on a filler, a Blazing Shot or Full Metal Field.
    for name in lua.eval("sim.reassembled").values():
        assert name in ("Drill", "AirAnchor", "ChainSaw", "Excavator"), f"Reassemble landed on {name}"

    # Resources are not thrown away.
    assert stats["heat wasted"] <= 10, stats
    assert stats["battery wasted"] <= 40, stats
    assert stats["Double Check capped"] < 10 and stats["Checkmate capped"] < 10, stats
    assert stats["Reassemble capped"] < 6, stats
    # The even-minute Queens carry a full battery.
    queens = [(q.t, q.battery) for q in lua.eval("sim.queens").values()]
    for mark in (120, 240):
        near = [battery for t, battery in queens if mark - 6 <= t <= mark + 15]
        assert near and max(near) >= 90, f"no full-battery Queen at the {mark}s burst: {queens}"
    print("six-minute fight ok")


if __name__ == "__main__":
    import sys

    parse_all()
    run_static()
    print("static priority cases ok")
    run_timeline(verbose="-v" in sys.argv)
    print("CielMachinist Lua syntax, mocked-runtime and timeline invariants passed.")
