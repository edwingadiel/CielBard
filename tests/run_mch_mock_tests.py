#!/usr/bin/env python3
"""Offline invariants for CielMachinist's priority engine.

Three layers, all against the shipped Lua loaded verbatim:
  1. every Lua file parses;
  2. direct priority cases against a static mocked MMOMinion runtime;
  3. sim_mch's time-stepped fake client (GCD, animation lock, charges, Heat,
     Battery, statuses, Wildfire hit counting) runs the engine through the
     opener, the pre-pull and a six-minute dummy fight and checks the
     rotation's shape.

Install the two lightweight test dependencies with:
    python -m pip install lupa luaparser
"""

import sys
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

-- BEFORE placement: Wildfire one weaponskill ahead of Hypercharge, late-weaved.
c = resetHarness()
quietCooldowns()
c.wildfirePlacement = "BEFORE"
setCooldown(A.Wildfire, 0, 120)
setReady(A.Wildfire) setReady(A.Hypercharge) setReady(A.DoubleCheck)
setStatus(ST.FullMetalMachinist, 25)
E.state.weavesSinceGCD = 0
ctx = directContext()
ctx.gcdRemaining = 1.9
expect(not E.WildfireAllowed(ctx), "too early in the GCD for the late weave")
expect(E.TryOGCD(ctx) and lastCastID() == A.DoubleCheck, "the first weave slot is still free for other oGCDs")
E.state.weavesSinceGCD = 1
expect(not E.TryOGCD(ctx) and lastCastID() == A.DoubleCheck, "the last weave slot is kept for Wildfire")
ctx.gcdRemaining = 1.2
expect(E.TryOGCD(ctx) and lastCastID() == A.Wildfire, "Wildfire goes out as the late weave")
setCooldown(A.Wildfire, 119, 120)
setReady(A.Wildfire, false)
E.state.weavesSinceGCD = 0
Player.buffs = {}
expect(not E.HyperchargeAllowed(ctx), "Hypercharge waits for the weaponskill in between")
Player.castinginfo = { lastcastid = A.FullMetalField, timesincecast = 100 }
E.ObserveLastCast()
expect(E.HyperchargeAllowed(ctx), "and follows it")
-- Two weaponskills still due: Wildfire waits a GCD.
c = resetHarness()
quietCooldowns()
c.wildfirePlacement = "BEFORE"
setCooldown(A.Wildfire, 0, 120)
setReady(A.Wildfire) setReady(A.Hypercharge)
setStatus(ST.FullMetalMachinist, 25)
setCharges(A.Drill, 1, 2, 20, 1)
E.UpdateCharges()
ctx = directContext()
ctx.gcdRemaining = 1.0
expect(not E.WildfireAllowed(ctx), "Drill and Full Metal Field both due: not yet")
expect(not E.HyperchargeAllowed(ctx), "and Hypercharge does not jump the queue")
Player.buffs = {}

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

----------------------------------------------------------------------------
-- Heat pooling for a second burst Hypercharge (opt-in).
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setReady(A.Hypercharge)
ctx = directContext()
ctx.heat, ctx.nextBurst = 60, 20
expect(c.hyperchargeBurstHeat == 0, "heat pooling ships Off")
expect(E.HyperchargeAllowed(ctx), "with pooling Off, heat is spent as soon as the tools allow")
c.hyperchargeBurstHeat = 45
expect(E.HeatPooledForBurst(ctx), "60 heat 20 s before burst leaves 10 + 20 < 45")
expect(not E.HyperchargeAllowed(ctx), "so Hypercharge is kept")
ctx.nextBurst = 60
expect(E.HyperchargeAllowed(ctx), "far from the burst the heat regenerates in time")
ctx.nextBurst = 20
ctx.heat = 100
expect(E.HyperchargeAllowed(ctx), "a full gauge is never sat on")
ctx.heat = 0
expect(E.HyperchargeAllowed(ctx), "a gauge that reads under 50 while Hypercharge is ready is not trusted")
ctx.heat = 60
ctx.burstActive = true
expect(E.HyperchargeAllowed(ctx), "inside the burst the pooled heat is spent")
ctx.burstActive = false
ctx.terminal = true
expect(E.HyperchargeAllowed(ctx), "the terminal band spends it too")
ctx.terminal = false
setStatus(ST.Hypercharged, 20)
expect(E.HyperchargeAllowed(ctx), "the free Hypercharge is never pooled")
Player.buffs = {}
c.resourcePooling = false
expect(E.HyperchargeAllowed(ctx), "pooling Off disables it")

----------------------------------------------------------------------------
-- Pre-pull.
----------------------------------------------------------------------------

-- Waiting for someone else's pull: nothing until armed, and never a weaponskill.
c = resetHarness()
quietCooldowns()
c.enabled = true
c.requireCombat = true
Player.incombat = false
setCharges(A.Reassemble, 2, 2, 55)
setReady(A.Reassemble) setReady(A.AirAnchor) setReady(A.HeatedSplitShot)
E.OnUpdate()
expect(#castLog == 0, "an unarmed engine does nothing out of combat")
E.ArmPrepull(10)
E.OnUpdate()
expect(#castLog == 1 and lastCastID() == A.Reassemble, "an armed pre-pull presses Reassemble")
expect(lastCastTarget() == 100, "on the player")
setStatus(ST.Reassembled, 4)
E.OnUpdate()
expect(#castLog == 1, "and then waits for the pull without pulling itself")
Player.buffs = {}

-- Only from a full stack, so an aborted pull costs nothing but the recharge.
c = resetHarness()
quietCooldowns()
c.enabled = true
Player.incombat = false
E.ArmPrepull(10)
setCharges(A.Reassemble, 1, 2, 55, 10)
setReady(A.Reassemble)
E.OnUpdate()
expect(#castLog == 0, "no pre-pull Reassemble from a partial stack")

-- The engine pulls itself: Reassemble first, then the weaponskill.
c = resetHarness()
quietCooldowns()
c.enabled = true
c.requireCombat = false
Player.incombat = false
setCharges(A.Reassemble, 2, 2, 55)
setReady(A.Reassemble) setReady(A.AirAnchor)
E.OnUpdate()
expect(lastCastID() == A.Reassemble, "self-pull starts with Reassemble")
setStatus(ST.Reassembled, 4.5)
setCharges(A.Reassemble, 1, 2, 55, 1)
E.OnUpdate()
expect(lastCastID() == A.AirAnchor, "and then opens with Air Anchor")
Player.buffs = {}
-- Switched off, it goes straight to the weaponskill.
c = resetHarness()
quietCooldowns()
c.enabled = true
c.requireCombat = false
c.prepull = false
Player.incombat = false
setCharges(A.Reassemble, 2, 2, 55)
setReady(A.Reassemble) setReady(A.AirAnchor)
E.OnUpdate()
expect(lastCastID() == A.AirAnchor, "pre-pull Off opens with the weaponskill")
Player.incombat = true

-- Wrong job does nothing.
c = resetHarness()
c.enabled = true
Player.job = 23
setReady(A.HeatedSplitShot)
E.OnUpdate()
expect(#castLog == 0, "the engine must not act on another job")
Player.job = 31
'''


def run_static() -> None:
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((MODULE / "CielMachinist_Data.lua").read_text(encoding="utf-8"))
    lua.execute(STATIC_ENV)
    lua.execute((MODULE / "CielMachinist_Rotation.lua").read_text(encoding="utf-8"))
    lua.execute(STATIC_SUITE)


def run_timeline(verbose: bool = False) -> None:
    """Drive the shipped engine through sim_mch's fake client and check the rotation's shape."""
    sys.path.insert(0, str(ROOT))
    from sim_mch.core import FightConfig, simulate
    from sim_mch.run import format_report

    ok = ("Drill", "AirAnchor", "ChainSaw", "Excavator")

    # --- Opener -------------------------------------------------------------
    opener = simulate(FightConfig(seconds=30))
    if verbose:
        print(format_report(opener, timeline_s=30))
    gcds = [e["name"] for e in opener.log if e["gcd"]][:12]
    expected = ["AirAnchor", "Drill", "ChainSaw", "Excavator", "Drill", "FullMetalField"] + \
        ["BlazingShot"] * 5 + ["Drill"]
    assert gcds == expected, f"opener GCDs were {gcds}"
    order = [e["name"] for e in opener.log]
    wildfire, fmf, hyper = order.index("Wildfire"), order.index("FullMetalField"), order.index("Hypercharge")
    assert fmf < hyper and wildfire == hyper + 1 and wildfire < order.index("BlazingShot"), \
        "opener must go Full Metal Field -> Hypercharge -> Wildfire -> Blazing Shot"
    assert order.index("BarrelStabilizer") < order.index("ChainSaw"), "Barrel Stabilizer opens the burst"
    assert opener.wildfire_hits == [6], "the opener Wildfire must catch six weaponskills"
    assert opener.queens[0][1] == 60 and opener.queens[0][0] < 12, "the opener Queen goes out at 60 battery"
    reassembled = [e["name"] for e in opener.log if e["reassembled"]]
    assert len(reassembled) == 2 and all(name in ok for name in reassembled), reassembled
    print("opener ok")

    # --- Pre-pull: the engine pulls, so Reassemble and the potion go first ----
    pre = simulate(FightConfig(seconds=20, start_in_combat=False, potions=1,
                               engine={"requireCombat": False}))
    names = [e["name"] for e in pre.log[:3]]
    assert names == ["Reassemble", "Potion", "AirAnchor"], f"pre-pull was {names}"
    assert pre.log[0]["t"] < 0 and pre.log[1]["t"] < 0 and pre.log[2]["t"] == 0
    assert pre.log[2]["reassembled"], "the pre-pull Reassemble must land on Air Anchor"
    assert pre.casts.get("Potion") == 1, "the potion is not taken twice"
    # Someone else pulls: nothing happens until the user arms the pre-pull.
    waiting = simulate(FightConfig(seconds=10, start_in_combat=False, pull_after_s=8.0))
    assert all(e["t"] >= 0 for e in waiting.log), "an unarmed engine must not act before the pull"
    armed = simulate(FightConfig(seconds=10, start_in_combat=False, pull_after_s=8.0, arm_prepull_at_s=4.0))
    early = [e for e in armed.log if e["t"] < 0]
    assert [e["name"] for e in early] == ["Reassemble"], f"armed pre-pull pressed {early}"
    assert not any(e["gcd"] for e in early), "an armed pre-pull must never pull"
    print("pre-pull ok")

    # --- Six-minute dummy fight ---------------------------------------------
    fight = simulate(FightConfig(seconds=360))
    if verbose:
        print(format_report(fight))
    seconds, stats, casts = fight.duration_s, fight.stats, fight.casts

    normal = overheated = current = 0
    after_short = False
    for entry in fight.log:
        if entry["gcd"]:
            current, after_short = 0, entry["name"] in ("BlazingShot", "AutoCrossbow")
        else:
            current += 1
            if after_short:
                overheated = max(overheated, current)
            else:
                normal = max(normal, current)
    assert normal <= 2, f"{normal} weaves after an ordinary weaponskill"
    assert overheated <= 1, f"{overheated} weaves after a Blazing Shot"

    # The GCD never sits idle, and no tool drifts by more than a GCD or two per use.
    assert stats["gcd_idle_s"] < 0.02 * seconds, stats
    assert stats["drill_capped_s"] < 6, stats          # the pull itself starts capped
    assert stats["air_anchor_idle_s"] <= 2.6 * casts["AirAnchor"], stats
    assert stats["chain_saw_idle_s"] <= 2.6 * casts["ChainSaw"] + 3, stats
    assert stats["broken_combos"] == 0, "the combo must never be broken"

    # Cooldowns are used at their natural rate over 360 s.
    assert casts["BarrelStabilizer"] == 3 and casts["Wildfire"] == 3, casts
    assert casts["FullMetalField"] == 3, casts
    assert casts["AirAnchor"] >= 9 and casts["ChainSaw"] >= 6 and casts["Excavator"] == casts["ChainSaw"], casts
    assert casts["Drill"] >= 18, casts
    assert casts["BlazingShot"] == 5 * casts["Hypercharge"], "every Hypercharge fits five Blazing Shots"
    assert casts["Hypercharge"] >= 10, casts
    assert casts["Reassemble"] >= 7, casts

    assert fight.wildfire_hits == [6, 6, 6], f"Wildfire hits were {fight.wildfire_hits}"
    for entry in fight.log:
        if entry["reassembled"]:
            assert entry["name"] in ok, f"Reassemble landed on {entry['name']}"

    # Resources are not thrown away.
    assert stats["heat_wasted"] <= 10, stats
    assert stats["battery_wasted"] <= 40, stats
    assert stats["double_check_capped_s"] < 10 and stats["checkmate_capped_s"] < 10, stats
    assert stats["reassemble_capped_s"] < 6, stats
    # The even-minute Queens carry a full battery.
    for mark in (120, 240):
        near = [battery for t, battery in fight.queens if mark - 6 <= t <= mark + 15]
        assert near and max(near) >= 90, f"no full-battery Queen at the {mark}s burst: {fight.queens}"
    print("six-minute fight ok")

    # --- Wildfire one weaponskill before Hypercharge (opt-in) ------------------
    before = simulate(FightConfig(seconds=360, engine={"wildfirePlacement": "BEFORE"}))
    order = [e["name"] for e in before.log]
    wildfire, fmf, hyper = order.index("Wildfire"), order.index("FullMetalField"), order.index("Hypercharge")
    assert wildfire < fmf < hyper, "BEFORE must go Wildfire -> Full Metal Field -> Hypercharge"
    assert before.wildfire_hits == [6, 6, 6], before.wildfire_hits
    assert before.casts["BlazingShot"] == 5 * before.casts["Hypercharge"]
    assert abs(before.dps / fight.dps - 1) < 0.002, "the two placements are worth the same with clean timing"
    print("wildfire placement ok")

    # --- Heat pooling (off by default) buys a second Hypercharge in the burst --
    pooled = simulate(FightConfig(seconds=200, engine={"hyperchargeBurstHeat": 45}))
    in_burst = [e["t"] for e in pooled.log if e["name"] == "Hypercharge" and 120 <= e["t"] <= 150]
    assert len(in_burst) == 2, f"pooled heat should fund two Hypercharges in the 2:00 burst: {in_burst}"
    plain = [e["t"] for e in fight.log if e["name"] == "Hypercharge" and 120 <= e["t"] <= 150]
    assert len(plain) == 1, f"without pooling the burst has the free Hypercharge only: {plain}"
    print("heat pooling ok")


if __name__ == "__main__":
    parse_all()
    run_static()
    print("static priority cases ok")
    run_timeline(verbose="-v" in sys.argv)
    print("CielMachinist Lua syntax, mocked-runtime and timeline invariants passed.")
