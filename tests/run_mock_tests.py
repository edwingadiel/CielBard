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
Now = function() ticks = ticks + 200; return ticks end

MIsLoading = function() return false end
MIsLocked = function() return false end
MIsCasting = function() return false end
EntityList = function() return {} end

local target = {
    id = 200, alive = true, targetable = true, distance2d = 10, los = true,
    hp = { current = 100000, percent = 100 }, buffs = {}, pos = { x = 0, y = 0, z = 0 },
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

local function clone(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, child in pairs(value) do result[key] = clone(child) end
    return result
end

function resetHarness()
    castLog = {}
    for _, item in pairs(actions) do
        item.ready = false
        item.highlighted = false
        item.cd = 0
        item.cdmax = 60
    end
    Player.gauge = {}
    Player.buffs = {}
    Player.hp.percent = 100
    target.buffs = {}
    target.hp.percent = 100
    target.los = true
    local config = clone(CielBardData.Defaults)
    config.requestThrottleMs = 0
    config.pulseMs = 0
    config.requireCombat = false
    CielBardEngine.Init(config)
    return config
end

function setReady(id, value)
    ActionList:Get(1, id).ready = value ~= false
end

function lastCastID()
    return #castLog > 0 and castLog[#castLog].id or 0
end

function directContext()
    return {
        target = target, ttk = 999, terminal = false, idealFinish = false,
        enemies = 1, aoe = false, storm = 30, caustic = 30,
        song = "WM", songRemaining = 30, nextBurst = 60,
        burstElapsed = 999, burstActive = false, burstConfigured = true,
        dotsReady = true, ttkBand = "SUSTAIN", soulVoice = 0, repertoire = 0,
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

-- Normal users retain optimized damage defaults while utility remains opt-in.
local c = resetHarness()
expect(E.AbilityEnabled("ApexArrow"), "optimized Apex default should be enabled")
expect(not E.AbilityEnabled("SecondWind"), "utility should remain disabled by default")

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
expect(not E.TrySong(directContext()), "all songs Off should not attempt a song")
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
