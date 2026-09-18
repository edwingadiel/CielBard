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
        item.isoncd = nil
        item.statusgainedid = nil
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
    -- Timing gates are disabled for the priority tests the same way the
    -- throttle and the pulse are; the dedupe window has its own case below.
    config.requestDedupeMs = 0
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

-- Live Barrage: the client exposes the action's statusgainedid and the buff
-- sits on the player. 122 is a stand-in id; the engine reads it from the
-- action, exactly as it does for songs.
function setBarrageStatus(remaining)
    ActionList:Get(1, CielBardData.Actions.Barrage).statusgainedid = 122
    Player.buffs = remaining and { { id = 122, ownerid = 100, duration = remaining } } or {}
end

function clearBarrageStatus()
    ActionList:Get(1, CielBardData.Actions.Barrage).statusgainedid = nil
    Player.buffs = {}
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
-- Barrage-aware Shadowbite (0.5.1 review, High #2).
-- Ordinary Hawk's Eye proc: Shadowbite 200/target beats Refulgent 280 at two.
-- Barrage proc: Refulgent strikes three times (840) while Shadowbite is only
-- 300/target, so Shadowbite needs three targets.
----------------------------------------------------------------------------

local function shadowbiteContext(enemies)
    local sc = directContext()
    sc.enemies = enemies
    sc.aoe = true
    return sc
end

-- Two targets, no Barrage -> Shadowbite.
c = resetHarness()
expect(E.AoETargetsFor("Shadowbite") == 2, "default Shadowbite threshold should be two targets")
expect(c.aoeTargets.ShadowbiteBarrage == 3, "default Barrage Shadowbite threshold should be three targets")
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
expect(not E.BarrageActive(), "Barrage must not be reported active on a clean reset")
expect(E.ShadowbiteTargetsRequired() == 2, "without Barrage the ordinary threshold applies")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.Shadowbite, "two targets on an ordinary proc should use Shadowbite")

-- Two targets, Barrage active (live status) -> Refulgent Arrow.
c = resetHarness()
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
setBarrageStatus(8)
expect(E.BarrageActive(), "the live Barrage status should be detected")
expect(E.ShadowbiteTargetsRequired() == 3, "Barrage should raise the Shadowbite threshold")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.RefulgentArrow, "two targets under Barrage should use Refulgent Arrow")

-- Three targets, Barrage active -> Shadowbite.
c = resetHarness()
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
setBarrageStatus(8)
expect(E.TryGCD(shadowbiteContext(3)), "proc consumption should cast")
expect(lastCastID() == A.Shadowbite, "three targets under Barrage should use Shadowbite")

-- An expired Barrage status falls back to the ordinary threshold.
c = resetHarness()
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
setBarrageStatus(nil)
ActionList:Get(1, A.Barrage).statusgainedid = 122
expect(not E.BarrageActive(), "an absent Barrage buff must not count as active")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.Shadowbite, "two targets with Barrage expired should use Shadowbite")

-- Fallback timer: no statusgainedid on this build, so a requested Barrage
-- cast starts a local 10 s window that gates Shadowbite the same way.
c = resetHarness()
clearBarrageStatus()
setReady(A.Barrage)
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
expect(not E.BarrageActive(), "no status and no cast means no Barrage")
expect(E.TryCast(A.Barrage, target, "Barrage"), "Barrage request should be accepted")
expect(lastCastTarget() == Player.id, "Barrage is requested on the player")
expect(E.BarrageActive(), "an accepted Barrage request should start the fallback timer")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.RefulgentArrow, "the fallback timer blocks Shadowbite until the buff is spent")
-- That Refulgent Arrow consumed the Barrage. On a build with no status to
-- read, the observed weaponskill is the only consumption signal there is, so
-- the timer has to clear instead of running out the rest of the 10 s window.
Player.castinginfo = { lastcastid = A.RefulgentArrow, timesincecast = 50 }
E.ObserveLastCast()
Player.castinginfo = { lastcastid = 0, timesincecast = 999999 }
expect(not E.BarrageActive(), "a weaponskill after Barrage consumes it and clears the fallback timer")
expect(E.ShadowbiteTargetsRequired() == 2, "the ordinary threshold returns once Barrage is spent")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.Shadowbite, "the proc after a consumed Barrage goes to Shadowbite")

-- With nothing observed at all the window still expires on its own.
c = resetHarness()
clearBarrageStatus()
setReady(A.Barrage)
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
expect(E.TryCast(A.Barrage, target, "Barrage"), "Barrage request should be accepted")
expect(E.BarrageActive(), "an accepted Barrage request should start the fallback timer")
ticks = ticks + 11000 -- past CielBardData.BarrageWindowSeconds
expect(not E.BarrageActive(), "the fallback timer should expire after the 10 s window")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.Shadowbite, "after the window Shadowbite wins at two targets again")

-- A readable status is authoritative. Once the buff has been seen, its
-- disappearance means the proc was consumed, and the fallback timer must not
-- keep the threshold at three for the rest of the window.
c = resetHarness()
setReady(A.Barrage)
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
ActionList:Get(1, A.Barrage).statusgainedid = 122
Player.buffs = {}
expect(E.TryCast(A.Barrage, target, "Barrage"), "Barrage request should be accepted")
expect(E.BarrageActive(), "the timer still covers the request-to-buff latency window")
setBarrageStatus(9)
expect(E.BarrageActive(), "the buff is readable once it lands")
expect(E.ShadowbiteTargetsRequired() == 3, "Barrage should raise the Shadowbite threshold")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.RefulgentArrow, "two targets under Barrage should use Refulgent Arrow")
Player.buffs = {} -- Refulgent Arrow consumed the Barrage
expect(not E.BarrageActive(), "a consumed Barrage must not be kept alive by the fallback timer")
expect(E.ShadowbiteTargetsRequired() == 2, "the threshold drops back inside the same 10 s window")
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.Shadowbite, "the next ordinary proc at two targets goes to Shadowbite")

-- The fallback timer also starts from a cast observed on the client.
c = resetHarness()
clearBarrageStatus()
Player.castinginfo = { lastcastid = A.Barrage, timesincecast = 100 }
E.ObserveLastCast()
expect(E.BarrageActive(), "an observed Barrage cast should start the fallback timer")
setReady(A.Shadowbite)
setReady(A.RefulgentArrow)
expect(E.TryGCD(shadowbiteContext(2)), "proc consumption should cast")
expect(lastCastID() == A.RefulgentArrow, "an observed Barrage should block Shadowbite at two targets")
Player.castinginfo = { lastcastid = 0, timesincecast = 999999 }

----------------------------------------------------------------------------
-- Pending-request dedupe (0.5.1 review, medium finding).
----------------------------------------------------------------------------

c = resetHarness()
expect(CielBardData.Defaults.requestDedupeMs == 350, "the shipped dedupe window should be 350 ms")
c.requestDedupeMs = 350
setReady(A.BurstShot)
setReady(A.HeavyShot)
expect(E.TryCast(A.BurstShot, target, "first"), "the first request should be sent")
expect(not E.TryCast(A.BurstShot, target, "duplicate"), "an identical request inside the window is suppressed")
expect(count(A.BurstShot) == 1, "the duplicate must not reach the client")

-- The hold is tier-wide. Before that it was per-action, so the priority chain
-- simply fell through to the next candidate and sent a *different*
-- weaponskill into the same queue window; FFXIV keeps the most recent command,
-- so a 100-gauge Apex Arrow could be replaced by a 220-potency Burst Shot.
c = resetHarness()
c.requestDedupeMs = 350
setReady(A.ApexArrow)
setReady(A.BurstShot)
local apexCtx = directContext()
apexCtx.soulVoice = 100
apexCtx.burstActive = true
expect(E.TryGCD(apexCtx), "the first pulse should cast")
expect(lastCastID() == A.ApexArrow, "100 gauge in burst should cast Apex Arrow")
expect(E.PendingGCD(ticks), "the accepted Apex Arrow is still unconfirmed")
expect(E.TryGCD(apexCtx), "the held pulse still counts as handled")
expect(count(A.BurstShot) == 0, "no other weaponskill may be sent inside the window")
expect(count(A.ApexArrow) == 1, "and the Apex Arrow itself is not re-sent")
expect(E.state.lastDecision == "Waiting for client to confirm last GCD", "the hold should be reported")
ticks = ticks + 1000
expect(E.TryGCD(apexCtx), "once the window passes the engine casts again")
expect(count(A.ApexArrow) == 2, "the re-send after the window is the same action")

-- oGCDs are held on their own tier, so a pending GCD never blocks a weave.
c = resetHarness()
c.requestDedupeMs = 350
setReady(A.BurstShot)
setReady(A.EmpyrealArrow)
expect(E.TryCast(A.BurstShot, target, "GCD"), "the weaponskill request should be sent")
expect(not E.PendingOGCD(ticks), "a pending GCD must not hold the oGCD tier")
expect(E.TryOGCD(directContext()), "weaving continues while the GCD is unconfirmed")
expect(count(A.EmpyrealArrow) == 1, "the weave reached the client")

-- The window expires.
c = resetHarness()
c.requestDedupeMs = 350
setReady(A.BurstShot)
expect(E.TryCast(A.BurstShot, target, "first"), "the first request should be sent")
ticks = ticks + 1000
expect(E.TryCast(A.BurstShot, target, "after the window"), "the same action is sent again once the window passes")
expect(count(A.BurstShot) == 2, "two casts after the window expired")

-- An observed cast lifts the guard immediately.
c = resetHarness()
c.requestDedupeMs = 5000
setReady(A.BurstShot)
expect(E.TryCast(A.BurstShot, target, "first"), "the first request should be sent")
expect(not E.TryCast(A.BurstShot, target, "duplicate"), "suppressed while nothing was observed")
Player.castinginfo = { lastcastid = A.BurstShot, timesincecast = 50 }
E.ObserveLastCast()
expect(E.TryCast(A.BurstShot, target, "after the observed cast"), "an observed cast clears the guard")
expect(count(A.BurstShot) == 2, "the request after the observed cast reached the client")
Player.castinginfo = { lastcastid = 0, timesincecast = 999999 }

-- The client reporting the action on cooldown also lifts the guard.
c = resetHarness()
c.requestDedupeMs = 5000
setReady(A.BurstShot)
expect(E.TryCast(A.BurstShot, target, "first"), "the first request should be sent")
expect(not E.TryCast(A.BurstShot, target, "duplicate"), "suppressed while the client says nothing")
ActionList:Get(1, A.BurstShot).isoncd = true
expect(E.TryCast(A.BurstShot, target, "confirmed by cooldown"), "an on-cooldown report clears the guard")

-- Shared charges: isoncd is already true at any partial stack, so the flag by
-- itself confirms nothing. Execution is read from `cd` rewinding by one recast.
c = resetHarness()
c.requestDedupeMs = 5000
local hb = ActionList:Get(1, A.HeartbreakShot)
hb.ready = true
hb.recasttime = 15
hb.cdmax = 45
hb.cd = 30
hb.isoncd = true -- two of three charges: true for essentially the whole fight
expect(E.TryCast(A.HeartbreakShot, target, "first charge"), "the first charge should be sent")
expect(not E.TryCast(A.HeartbreakShot, target, "duplicate"), "a partial stack must not defeat the guard")
expect(count(A.HeartbreakShot) == 1, "only one request reached the client")
hb.cd = 15 -- the charge was spent: cd rewinds by one recast
expect(E.TryCast(A.HeartbreakShot, target, "second charge"), "cooldown movement confirms execution")
expect(count(A.HeartbreakShot) == 2, "the next charge is allowed once cd moves")

-- A rejected request never holds the guard.
c = resetHarness()
c.requestDedupeMs = 5000
local bs = ActionList:Get(1, A.BurstShot)
bs.ready = true
bs.Cast = function(self, targetID) return false end
expect(not E.TryCast(A.BurstShot, target, "rejected"), "a rejected request returns false")
expect(E.state.pendingActionID == 0, "a rejected request must not leave a pending guard")
bs.Cast = function(self, targetID)
    table.insert(castLog, { id = self.id, target = targetID })
    return true
end

----------------------------------------------------------------------------
-- CielBardData.GCD completeness. ObserveLastCast classifies an unlisted id as
-- a weave, so a missing weaponskill permanently inflates weavesSinceGCD and
-- E.TryOGCD stops weaving for the rest of the fight. Windbite (the level-sync
-- Stormbite fallback) was missing exactly this way.
----------------------------------------------------------------------------

local gcdPathActions = {
    { "HeavyShot", A.HeavyShot }, { "QuickNock", A.QuickNock },
    { "Windbite", A.Windbite }, { "VenomousBite", A.VenomousBite },
    { "Stormbite", A.Stormbite }, { "CausticBite", A.CausticBite },
    { "IronJaws", A.IronJaws }, { "RefulgentArrow", A.RefulgentArrow },
    { "Shadowbite", A.Shadowbite }, { "BurstShot", A.BurstShot },
    { "ApexArrow", A.ApexArrow }, { "Ladonsbite", A.Ladonsbite },
    { "BlastArrow", A.BlastArrow }, { "ResonantArrow", A.ResonantArrow },
    { "RadiantEncore", A.RadiantEncore },
}
for _, entry in ipairs(gcdPathActions) do
    expect(entry[2] ~= nil, "CielBardData.Actions is missing " .. entry[1])
    expect(CielBardData.GCD[entry[2]] == true,
        entry[1] .. " (" .. tostring(entry[2]) .. ") is cast on a GCD path but missing from CielBardData.GCD")
end

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

-- Multi-dot is Off by default since 0.5.2 (review High #3): the same
-- situation falls through to Burst Shot on the primary target.
c = resetHarness()
expect(c.multiDot == false, "multi-dot must be off in the shipped defaults")
entityList = { [300] = makeEnemy(300, "Add A", 80, true) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot and lastCastTarget() == 200,
    "the default configuration must not dot secondary targets")

-- Turned on: an engaged secondary target without DoTs receives Stormbite.
c = resetHarness()
c.multiDot = true
entityList = { [300] = makeEnemy(300, "Add A", 80, true) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "multi-dot GCD should cast")
expect(lastCastID() == A.Stormbite, "multi-dot should apply Stormbite to the secondary target")
expect(lastCastTarget() == 300, "multi-dot must target the secondary enemy, not the primary")

-- Toggle off explicitly: still nothing but filler on the primary.
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
c.multiDot = true
entityList = { [301] = makeEnemy(301, "Idle mob", 100, false) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot, "multi-dot must ignore enemies that are not in combat")

-- Low-HP adds are skipped.
c = resetHarness()
c.multiDot = true
entityList = { [302] = makeEnemy(302, "Dying add", 10, true) }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot, "multi-dot must skip targets below the HP floor")

-- Secondary target with both DoTs expiring gets Iron Jaws; a fresh one does not.
c = resetHarness()
c.multiDot = true
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
c.multiDot = true
entityList = { [303] = add }
setReady(A.Stormbite)
setReady(A.BurstShot)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "filler should cast")
expect(lastCastID() == A.BurstShot, "healthy secondary DoTs should not consume a GCD")

-- Multi-dot is suppressed when the fight is ending.
c = resetHarness()
c.multiDot = true
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
c.multiDot = true
entityList = { [300] = makeEnemy(300, "Add A", 80, true) }
setReady(A.Stormbite)
setReady(A.RefulgentArrow)
ctx = directContext()
E.state.multiDotScanAt = 0
expect(E.TryGCD(ctx), "proc should cast")
expect(lastCastID() == A.RefulgentArrow, "Refulgent should take priority over multi-dot")

----------------------------------------------------------------------------
-- Shared-charge count from the live cd/cdmax layout (cdmax = 45, recast = 15).
----------------------------------------------------------------------------
c = resetHarness()
local hb = ActionList:Get(1, A.HeartbreakShot)
hb.recasttime = 15
hb.cdmax, hb.cd, hb.isoncd = 45, 30.5, true
E.UpdateCharges()
expect(E.state.charges == 2, "cd=30.5 of 45 should read as 2 charges")
expect(math.abs(E.state.chargeRemaining - 14.5) < 0.01, "next charge should be 14.5s away")
hb.cd = 7.7
E.UpdateCharges()
expect(E.state.charges == 0, "cd=7.7 of 45 should read as 0 charges")
hb.cdmax, hb.cd, hb.isoncd = 0, 0, false
E.UpdateCharges()
expect(E.state.charges == 3 and E.state.chargeRemaining == 0, "off cooldown should be a full stack")

-- Pooling: at 3 charges 20s before burst, spend one (it returns in time);
-- at 2 charges 10s before burst, hold.
c = resetHarness()
hb = ActionList:Get(1, A.HeartbreakShot)
hb.recasttime = 15
hb.cdmax, hb.cd, hb.isoncd = 0, 0, false
setReady(A.HeartbreakShot)
E.UpdateCharges()
ctx = directContext()
ctx.nextBurst = 20
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "full stack 20s before burst should spend one")
expect(lastCastID() == A.HeartbreakShot, "spent Heartbreak from a full stack")
c = resetHarness()
hb = ActionList:Get(1, A.HeartbreakShot)
hb.recasttime = 15
hb.cdmax, hb.cd, hb.isoncd = 45, 40, true
setReady(A.HeartbreakShot)
E.UpdateCharges()
ctx = directContext()
ctx.nextBurst = 10
E.state.weavesSinceGCD = 0
E.TryOGCD(ctx)
expect(count(A.HeartbreakShot) == 0, "two charges 10s before burst should be held")
ctx.nextBurst = 60
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx) and lastCastID() == A.HeartbreakShot, "outside the pooling window charges are spent on cooldown")

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
