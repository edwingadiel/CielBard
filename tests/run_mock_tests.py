#!/usr/bin/env python3
"""Offline invariants for CielBard's configurable priority engine.

Install the two lightweight test dependencies with:
    python -m pip install lupa luaparser
"""

from pathlib import Path
import sys

from lupa import LuaRuntime
from luaparser import ast


ROOT = Path(__file__).resolve().parents[1]
LUA_FILES = [
    ROOT / "CielBard" / "CielBard_Data.lua",
    ROOT / "CielBard" / "CielBard_Rotation.lua",
    ROOT / "CielBard" / "CielBard.lua",
]


def parse_all() -> None:
    for path in LUA_FILES:
        ast.parse(path.read_text(encoding="utf-8"))


def run_rotation_invariants() -> None:
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((ROOT / "CielBard" / "CielBard_Data.lua").read_text(encoding="utf-8"))
    lua.execute(
        r'''
ticks = 10000
castLog = {}
entityList = {}
inventoryItems = {}
Now = function() ticks = ticks + 200; return ticks end

MIsLoading = function() return false end
MIsLocked = function() return false end
MIsCasting = function() return false end
EntityList = function(filter) return entityList end

target = {
    id = 200, name = "Primary", alive = true, targetable = true, incombat = true,
    distance2d = 10, los = true,
    hp = { current = 100000, max = 100000, percent = 100 }, buffs = {}, pos = { x = 0, y = 0, z = 0 },
}
Player = {
    id = 100, alive = true, job = 23, incombat = true,
    hp = { current = 100000, percent = 100 }, buffs = {}, gauge = {},
    castinginfo = { lastcastid = 0, timesincecast = 999999 },
    GetTarget = function() return target end,
}

local actions = {}
local function makeAction(id)
    local item = {
        id = id, name = "Action " .. tostring(id), usable = true,
        ready = false, cd = 0, cdmax = 60, highlighted = false,
    }
    item.IsReady = function(self, targetID) return self.ready end
    item.Cast = function(self, targetID)
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

-- Mock of FFXIVMinion's GetItem(hqid, inventories): returns item, action.
GetItem = function(hqid, inventories)
    local item = inventoryItems[hqid]
    if not item then return nil, nil end
    return item, item.action
end

function makeEnemy(id, name, hpPercent, incombat)
    return {
        id = id, name = name, alive = true, targetable = true, incombat = incombat ~= false,
        los = true, distance2d = 8,
        hp = { current = hpPercent * 1000, max = 100000, percent = hpPercent },
        buffs = {}, pos = { x = 3, y = 0, z = 0 },
    }
end

function makePotion(hqid, ready)
    local potion = { hqid = hqid, ready = ready ~= false }
    potion.action = { id = 900000 + hqid, isoncd = not potion.ready, cd = 0, cdmax = 270 }
    if not potion.ready then potion.action.cd = 0 else potion.action.cd = 270 end
    potion.IsReady = function(self, targetID) return self.ready end
    potion.Cast = function(self, targetID)
        table.insert(castLog, { id = "potion:" .. tostring(self.hqid), target = targetID })
        return true
    end
    potion.GetAction = function(self) return self.action end
    return potion
end

local function clone(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, child in pairs(value) do result[key] = clone(child) end
    return result
end

function resetHarness()
    castLog = {}
    entityList = {}
    inventoryItems = {}
    for _, item in pairs(actions) do
        item.ready = false
        item.highlighted = false
        item.cd = 0
        item.cdmax = 60
    end
    Player.gauge = {}
    Player.buffs = {}
    Player.hp.percent = 100
    Player.castinginfo = { lastcastid = 0, timesincecast = 999999 }
    target.buffs = {}
    target.hp.percent = 100
    target.los = true
    local config = clone(CielBardData.Defaults)
    config.requestThrottleMs = 0
    config.pulseMs = 0
    config.requireCombat = false
    CielBardEngine.Init(config)
    CielBardEngine.state.potionScanAt = 0
    CielBardEngine.state.potionUsedAt = 0
    CielBardEngine.state.potionItem = nil
    CielBardEngine.state.potionAction = nil
    CielBardEngine.state.potionActionID = 0
    return config
end

function setReady(id, value)
    ActionList:Get(1, id).ready = value ~= false
end

function lastCastID()
    return #castLog > 0 and castLog[#castLog].id or 0
end

function lastCastTarget()
    return #castLog > 0 and castLog[#castLog].target or 0
end

function directContext()
    return {
        target = target, ttk = 999, terminal = false, idealFinish = false,
        enemies = 1, aoe = false, storm = 30, caustic = 30,
        song = "WM", songRemaining = 30, nextSongKey = "MB", songSwapIn = 27.3,
        codas = 1, nextBurst = 60,
        burstElapsed = 999, burstActive = false, burstConfigured = true,
        dotsReady = true, oneDotReady = true, ttkBand = "SUSTAIN", soulVoice = 0, repertoire = 0,
    }
end
'''
    )
    lua.execute((ROOT / "CielBard" / "CielBard_Rotation.lua").read_text(encoding="utf-8"))

    suite = r'''
local A = CielBardData.Actions
local E = CielBardEngine

local function expect(condition, message)
    if not condition then error(message, 2) end
end

local function count(id)
    local total = 0
    for _, entry in ipairs(castLog) do if entry.id == id then total = total + 1 end end
    return total
end

-- Normal users retain optimized damage defaults while utility remains opt-in.
local c = resetHarness()
expect(E.AbilityEnabled("ApexArrow"), "optimized Apex default should be enabled")
expect(not E.AbilityEnabled("SecondWind"), "utility should remain disabled by default")
expect(not c.usePotion, "potion use must be opt-in")

-- Disabling Apex must remove both the cast and its resource-pooling stall.
c = resetHarness()
c.advancedEnabled = true
c.abilities.ApexArrow = false
setReady(A.ApexArrow)
setReady(A.BurstShot)
local ctx = directContext()
ctx.soulVoice = 100
expect(E.TryGCD(ctx), "GCD fallback should cast")
expect(lastCastID() == A.BurstShot, "Apex Off should fall through to Burst Shot")

-- A deliberately empty song configuration must warn and safely continue.
c = resetHarness()
c.advancedEnabled = true
c.abilities.WanderersMinuet = false
c.abilities.MagesBallad = false
c.abilities.ArmysPaeon = false
ctx = directContext()
ctx.nextSongKey = nil
expect(not E.TrySong(ctx), "all songs Off should not attempt a song")
expect(#E.GetConfigurationWarnings() >= 1, "all songs Off should produce a warning")

-- Iron Jaws Off changes maintenance to individual DoT refreshes.
c = resetHarness()
c.advancedEnabled = true
c.abilities.IronJaws = false
setReady(A.IronJaws)
setReady(A.Stormbite)
ctx = directContext()
ctx.storm = 2
expect(E.TryGCD(ctx), "manual DoT refresh should cast")
expect(lastCastID() == A.Stormbite, "Iron Jaws Off should manually refresh Stormbite")

-- No-DoT configurations must continue direct damage without stalling.
c = resetHarness()
c.advancedEnabled = true
c.abilities.Stormbite = false
c.abilities.CausticBite = false
c.abilities.IronJaws = false
setReady(A.BurstShot)
ctx = directContext()
ctx.storm, ctx.caustic = 0, 0
expect(E.TryGCD(ctx), "No DoTs should still cast direct damage")
expect(lastCastID() == A.BurstShot, "No DoTs should fall through to Burst Shot")

-- Burst Shot is followed by Heavy Shot as the permanent level-sync fallback.
c = resetHarness()
c.advancedEnabled = true
setReady(A.HeavyShot)
expect(E.TryGCD(directContext()), "Heavy Shot fallback should cast")
expect(lastCastID() == A.HeavyShot, "Heavy Shot should be the final GCD fallback")

-- GCD-only mode must never emit an oGCD while the GCD is locked.
c = resetHarness()
c.enabled = true
c.advancedEnabled = true
c.executionMode = "GCD_ONLY"
c.abilities.WanderersMinuet = false
c.abilities.MagesBallad = false
c.abilities.ArmysPaeon = false
c.abilities.RagingStrikes = false
c.abilities.BattleVoice = false
c.abilities.RadiantFinale = false
setReady(A.EmpyrealArrow)
E.OnUpdate()
expect(#castLog == 0, "GCD-only mode emitted an oGCD")

----------------------------------------------------------------------------
-- Per-action AoE thresholds.
----------------------------------------------------------------------------

-- Ladonsbite honors its own threshold independently of Rain of Death.
c = resetHarness()
c.aoeTargets.Ladonsbite = 3
c.aoeTargets.RainOfDeath = 2
setReady(A.Ladonsbite)
setReady(A.BurstShot)
ctx = directContext()
ctx.enemies = 2
ctx.aoe = true
expect(E.TryGCD(ctx), "two-target filler should cast")
expect(lastCastID() == A.BurstShot, "Ladonsbite must wait for its own threshold (3)")
ctx.enemies = 3
expect(E.TryGCD(ctx), "three-target filler should cast")
expect(lastCastID() == A.Ladonsbite, "Ladonsbite should fire at its threshold")

-- Rain of Death replaces Heartbreak at two targets while Ladonsbite waits.
c = resetHarness()
c.aoeTargets.Ladonsbite = 3
c.aoeTargets.RainOfDeath = 2
setReady(A.RainOfDeath)
setReady(A.HeartbreakShot)
ActionList:Get(1, A.RainOfDeath).cd = 60
ActionList:Get(1, A.HeartbreakShot).cd = 60
ctx = directContext()
ctx.enemies = 2
ctx.aoe = true
ctx.burstConfigured = false
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "near-cap charge should be spent")
expect(lastCastID() == A.RainOfDeath, "Rain of Death should replace Heartbreak at two targets")

-- Shadowbite uses its own threshold too.
c = resetHarness()
c.aoeTargets.Shadowbite = 4
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
ctx = directContext()
ctx.enemies = 2
ctx.aoe = true
expect(E.TryGCD(ctx), "proc consumption should cast")
expect(lastCastID() == A.RefulgentArrow, "Shadowbite below its threshold should yield to Refulgent")

----------------------------------------------------------------------------
-- Burst start DoT gate.
----------------------------------------------------------------------------

local function burstContext()
    local b = directContext()
    b.nextBurst = 0
    b.song = "WM"
    return b
end

-- ONE (default): Raging Strikes starts with a single DoT active.
c = resetHarness()
setReady(A.RagingStrikes)
ctx = burstContext()
ctx.storm, ctx.caustic = 40, 0
ctx.dotsReady, ctx.oneDotReady = false, true
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "burst should start")
expect(lastCastID() == A.RagingStrikes, "ONE gate should start burst after the first DoT")

-- ONE: no DoTs at all still waits (the first DoT is one GCD away).
c = resetHarness()
setReady(A.RagingStrikes)
ctx = burstContext()
ctx.storm, ctx.caustic = 0, 0
ctx.dotsReady, ctx.oneDotReady = false, false
E.state.weavesSinceGCD = 0
E.TryOGCD(ctx)
expect(count(A.RagingStrikes) == 0, "ONE gate should wait for the first DoT")

-- BOTH: a single DoT is not enough.
c = resetHarness()
c.burstDotGate = "BOTH"
setReady(A.RagingStrikes)
ctx = burstContext()
ctx.storm, ctx.caustic = 40, 0
ctx.dotsReady, ctx.oneDotReady = false, true
E.state.weavesSinceGCD = 0
E.TryOGCD(ctx)
expect(count(A.RagingStrikes) == 0, "BOTH gate should wait for both DoTs")

-- NONE: burst never waits for DoTs.
c = resetHarness()
c.burstDotGate = "NONE"
setReady(A.RagingStrikes)
ctx = burstContext()
ctx.storm, ctx.caustic = 0, 0
ctx.dotsReady, ctx.oneDotReady = false, false
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "NONE gate should start burst")
expect(lastCastID() == A.RagingStrikes, "NONE gate should not wait for DoTs")

----------------------------------------------------------------------------
-- Radiant Finale coda awareness.
----------------------------------------------------------------------------

-- Zero codas: Radiant Finale is never requested, Battle Voice proceeds.
c = resetHarness()
setReady(A.RadiantFinale)
setReady(A.BattleVoice)
ctx = directContext()
ctx.codas = 0
ctx.burstActive = true
ctx.burstElapsed = 2
E.state.ragingAt = ticks
E.state.gcdsSinceRaging = 1
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "burst weave should cast")
expect(lastCastID() == A.BattleVoice, "Battle Voice should fire")
E.state.weavesSinceGCD = 1
E.TryOGCD(ctx)
expect(count(A.RadiantFinale) == 0, "Radiant Finale must not be requested at zero codas")

-- Codas are tracked from observed song casts and cleared by Radiant Finale.
c = resetHarness()
expect(E.CodaCount() == 0, "codas should start at zero")
Player.castinginfo = { lastcastid = A.WanderersMinuet, timesincecast = 10 }
E.ObserveLastCast()
expect(E.CodaCount() == 1 and E.state.codas.WM, "observed Wanderer's should add its coda")
Player.castinginfo = { lastcastid = A.MagesBallad, timesincecast = 10 }
E.ObserveLastCast()
expect(E.CodaCount() == 2, "observed Mage's should add a second coda")
Player.castinginfo = { lastcastid = A.RadiantFinale, timesincecast = 10 }
E.ObserveLastCast()
expect(E.CodaCount() == 0, "Radiant Finale should clear tracked codas")

-- One coda in the opener is allowed (no hold that could lose a use).
c = resetHarness()
setReady(A.RadiantFinale)
E.state.codas.WM = true
ctx = directContext()
ctx.codas = 1
ctx.burstActive = true
ctx.burstElapsed = 2
ctx.songSwapIn = 40
E.state.ragingAt = ticks
E.state.gcdsSinceRaging = 1
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "one-coda Finale should cast")
expect(lastCastID() == A.RadiantFinale, "opener Radiant Finale should fire at one coda")
expect(E.CodaCount() == 0, "requesting Radiant Finale should clear codas")

-- A song due within the hold window that would add a coda lands first.
c = resetHarness()
setReady(A.RadiantFinale)
E.state.codas.WM = true
ctx = directContext()
ctx.codas = 1
ctx.nextSongKey = "MB"
ctx.songSwapIn = 1.0
ctx.burstActive = true
ctx.burstElapsed = 2
E.state.ragingAt = ticks
E.state.gcdsSinceRaging = 1
E.state.weavesSinceGCD = 0
E.TryOGCD(ctx)
expect(count(A.RadiantFinale) == 0, "Radiant Finale should let an imminent coda-adding song land first")

-- The hold is ignored when the fight is ending.
ctx.terminal = true
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "terminal Finale should cast")
expect(lastCastID() == A.RadiantFinale, "terminal band should not hold Radiant Finale")

-- The hold does not apply when the next song's coda is already held.
c = resetHarness()
setReady(A.RadiantFinale)
E.state.codas.WM = true
E.state.codas.MB = true
ctx = directContext()
ctx.codas = 2
ctx.nextSongKey = "MB"
ctx.songSwapIn = 1.0
ctx.burstActive = true
ctx.burstElapsed = 2
E.state.ragingAt = ticks
E.state.gcdsSinceRaging = 1
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "Finale should cast when the next song adds nothing")
expect(lastCastID() == A.RadiantFinale, "no hold when the imminent song's coda is already held")

----------------------------------------------------------------------------
-- Potion.
----------------------------------------------------------------------------

-- Opt-in potion is weaved immediately before Raging Strikes, HQ preferred.
c = resetHarness()
c.usePotion = true
local hq = CielBardData.Potions[2].id + CielBardData.HQOffset
inventoryItems[CielBardData.Potions[2].id] = makePotion(CielBardData.Potions[2].id, true)
inventoryItems[hq] = makePotion(hq, true)
setReady(A.RagingStrikes)
ctx = burstContext()
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "potion weave should cast")
expect(lastCastID() == "potion:" .. tostring(hq), "HQ potion should be used before Raging Strikes")
expect(E.state.weavesSinceGCD == 1, "potion should count as a weave")
expect(E.TryOGCD(ctx), "Raging Strikes should follow the potion")
expect(lastCastID() == A.RagingStrikes, "Raging Strikes should follow the potion in the same window")

-- Potion off: nothing is used even when available.
c = resetHarness()
inventoryItems[hq] = makePotion(hq, true)
setReady(A.RagingStrikes)
ctx = burstContext()
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "burst should still start")
expect(lastCastID() == A.RagingStrikes, "no potion when usePotion is off")
expect(count("potion:" .. tostring(hq)) == 0, "potion must not be used when disabled")

-- Potion on cooldown: burst is not delayed.
c = resetHarness()
c.usePotion = true
inventoryItems[hq] = makePotion(hq, false)
setReady(A.RagingStrikes)
ctx = burstContext()
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "burst should start without a ready potion")
expect(lastCastID() == A.RagingStrikes, "a potion on cooldown must not delay Raging Strikes")

-- Potion on but none in inventory: a warning is shown and burst proceeds.
c = resetHarness()
c.usePotion = true
setReady(A.RagingStrikes)
ctx = burstContext()
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "burst should start without any potion")
expect(lastCastID() == A.RagingStrikes, "missing potion must not block burst")
local sawWarning = false
for _, warning in ipairs(E.GetConfigurationWarnings()) do
    if warning:find("Gemdraught") then sawWarning = true end
end
expect(sawWarning, "missing potion should produce a configuration warning")

-- Potion is skipped when the fight ends too soon to pay off.
c = resetHarness()
c.usePotion = true
inventoryItems[hq] = makePotion(hq, true)
setReady(A.RagingStrikes)
ctx = burstContext()
ctx.ttk = 5
ctx.terminal = true
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "terminal burst should start")
expect(lastCastID() == A.RagingStrikes, "potion should be skipped under potionMinimumTTK")

----------------------------------------------------------------------------
-- Multi-dot.
----------------------------------------------------------------------------

-- Default on: an engaged secondary target without DoTs receives Stormbite.
c = resetHarness()
entityList = { [300] = makeEnemy(300, "Add A", 80, true) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "multi-dot GCD should cast")
expect(lastCastID() == A.Stormbite, "multi-dot should apply Stormbite to the secondary target")
expect(lastCastTarget() == 300, "multi-dot must target the secondary enemy, not the primary")

-- Toggle off: the same situation falls through to Burst Shot on the primary.
c = resetHarness()
c.multiDot = false
entityList = { [300] = makeEnemy(300, "Add A", 80, true) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot and lastCastTarget() == 200, "multi-dot Off must not touch secondary targets")

-- Idle (not in combat) enemies are never dotted.
c = resetHarness()
entityList = { [301] = makeEnemy(301, "Idle mob", 100, false) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot, "multi-dot must ignore enemies that are not in combat")

-- Low-HP adds are skipped.
c = resetHarness()
entityList = { [302] = makeEnemy(302, "Dying add", 10, true) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot, "multi-dot must skip targets below the HP floor")

-- Secondary target with both DoTs expiring gets Iron Jaws; a fresh one does not.
c = resetHarness()
local add = makeEnemy(303, "Add B", 90, true)
add.buffs = {
    { id = CielBardData.Statuses.Stormbite, ownerid = 100, duration = 2 },
    { id = CielBardData.Statuses.CausticBite, ownerid = 100, duration = 2 },
}
entityList = { [303] = add }
setReady(A.IronJaws)
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "multi-dot refresh should cast")
expect(lastCastID() == A.IronJaws and lastCastTarget() == 303, "multi-dot should Iron Jaws a secondary target with both DoTs expiring")

-- Secondary DoTs already healthy: normal filler continues.
add.buffs[1].duration = 30
add.buffs[2].duration = 30
c = resetHarness()
entityList = { [303] = add }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot, "healthy secondary DoTs should not consume a GCD")

-- Multi-dot is suppressed when the fight is ending.
c = resetHarness()
entityList = { [300] = makeEnemy(300, "Add A", 80, true) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
ctx.ttk = 25
ctx.idealFinish = true
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot, "multi-dot should stop when the kill is near")

-- Procs still win over secondary DoTs.
c = resetHarness()
entityList = { [300] = makeEnemy(300, "Add A", 80, true) }
setReady(A.Stormbite)
setReady(A.RefulgentArrow)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "proc should cast")
expect(lastCastID() == A.RefulgentArrow, "Refulgent should take priority over multi-dot")

-- Single-target preset switches multi-dot off through the normal merge path.
c = resetHarness()
for key, value in pairs(CielBardData.Presets.SingleTarget) do
    if type(value) ~= "table" then c[key] = value end
end
expect(c.multiDot == false, "Single target preset should disable multi-dot")

return true
'''
    assert lua.execute(suite) is True


if __name__ == "__main__":
    try:
        parse_all()
        run_rotation_invariants()
    except Exception as exc:  # concise output for CI and local terminals
        print(f"CielBard tests failed: {exc}", file=sys.stderr)
        raise
    print("CielBard Lua syntax and mocked-runtime invariants passed.")
