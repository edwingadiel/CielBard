#!/usr/bin/env python3
"""Offline invariants for CielDancer's priority engine.

Three layers, all against the shipped Lua loaded verbatim:
  1. every Lua file parses;
  2. direct priority cases against a static mocked MMOMinion runtime;
  3. sim_dnc's seeded fake client (random step sequences, 50% procs, Esprit from the
     party) runs the engine through the opener, the pre-pull and six-minute fights on
     several seeds and checks the rotation's shape.
"""

import sys
from pathlib import Path

from lupa import LuaRuntime
from luaparser import ast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
MODULE = ROOT / "CielDancer"
LUA_FILES = [MODULE / "CielDancer_Data.lua", MODULE / "CielDancer_Rotation.lua", MODULE / "CielDancer.lua",
             MODULE / "acr" / "CielDancer.lua"]


def parse_all() -> None:
    for path in LUA_FILES:
        ast.parse(path.read_text(encoding="utf-8"))


def static_env() -> str:
    """The Machinist suite's static mock, retargeted at the Dancer module."""
    import run_mch_mock_tests as mch
    env = mch.STATIC_ENV.replace("CielMachinistData", "CielDancerData").replace("CielMachinistEngine", "CielDancerEngine")
    env = env.replace("job = 31", "job = 38")
    a = env.index("-- Everything on a long cooldown")
    return env[:a] + r'''
function quietCooldowns()
    local A = CielDancerData.Actions
    setCooldown(A.TechnicalStep, 90, 120)
    setCooldown(A.StandardStep, 20, 30)
    setCooldown(A.Devilment, 90, 120)
    setCooldown(A.Flourish, 40, 60)
    Player.gauge = { 0, 0, 0, 0, 0, 0, 0 }
end

function directContext()
    return {
        target = target, ttk = 999, terminal = false, idealFinish = false,
        enemies = 1, aoe = false, nextBurst = 90, burstConfigured = true,
        burstActive = false, burstRemaining = 0, burstElapsed = 999,
        ttkBand = "SUSTAIN", esprit = 0, feathers = 0, dancing = nil, gcdRemaining = 1.5, pullNow = true,
    }
end
'''


STATIC_SUITE = r'''
local A = CielDancerData.Actions
local ST = CielDancerData.Statuses
local E = CielDancerEngine

local function expect(condition, message)
    if not condition then error(message, 2) end
end

local c = resetHarness()
expect(E.AbilityEnabled("TechnicalStep"), "optimized Technical Step default should be enabled")
expect(not E.AbilityEnabled("SecondWind") and not E.AbilityEnabled("ShieldSamba"), "utility stays opt-in")
expect(not c.usePotion and not c.enabled, "potion and execution are opt-in")

----------------------------------------------------------------------------
-- Dancing: steps from the gauge, then the highlight; the finish; the range hold.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setStatus(ST.StandardStep, 14)
Player.gauge = { 0, 0, 3, 1, 0, 0, 0 }
for _, id in ipairs({ A.Emboite, A.Entrechat, A.Jete, A.Pirouette, A.DoubleStandardFinish, A.Cascade }) do setReady(id) end
local ctx = directContext()
ctx.dancing = E.Dancing()
expect(ctx.dancing == "STANDARD", "the Standard Step status means dancing")
expect(E.TryGCD(ctx) and lastCastID() == A.Jete, "first step comes from gauge slot 3")
expect(lastCastTarget() == 100, "steps are requested on the player")
Player.gauge = { 0, 0, 3, 1, 0, 0, 1 }
expect(E.TryGCD(ctx) and lastCastID() == A.Emboite, "second step comes from gauge slot 4")
Player.gauge = { 0, 0, 3, 1, 0, 0, 2 }
expect(E.TryGCD(ctx) and lastCastID() == A.DoubleStandardFinish, "two steps done: Double Standard Finish")
-- Nothing else is ever pressed mid-dance, and no oGCD is weaved.
Player.gauge = { 0, 0, 3, 1, 0, 0, 0 }
setReady(A.Jete, false)
local before = #castLog
expect(E.TryGCD(ctx) and #castLog == before, "a step that is not ready yet is waited for, not replaced")
setReady(A.FanDanceIII)
E.state.weavesSinceGCD = 0
expect(not E.TryOGCD(ctx), "no weaving while dancing")

-- The finish is a 15 yalm circle around the dancer.
setReady(A.Jete)
Player.gauge = { 0, 0, 3, 1, 0, 0, 2 }
target.distance2d = 22
before = #castLog
expect(E.TryGCD(ctx) and #castLog == before, "the finish is held for a target outside 15 yalms")
Player.buffs = {}
setStatus(ST.StandardStep, 1.5)
expect(E.TryGCD(ctx) and lastCastID() == A.DoubleStandardFinish, "unless the dance is about to lapse")
target.distance2d = 10

-- Unreadable gauge: fall back to the highlighted step.
c = resetHarness()
quietCooldowns()
setStatus(ST.TechnicalStep, 14)
Player.gauge = {}
for _, id in ipairs({ A.Emboite, A.Entrechat, A.Jete, A.Pirouette }) do setReady(id) end
ActionList:Get(1, A.Pirouette).highlighted = true
ctx = directContext()
ctx.dancing = E.Dancing()
expect(ctx.dancing == "TECHNICAL", "the Technical Step status means dancing")
expect(E.TryGCD(ctx) and lastCastID() == A.Pirouette, "the highlighted step is the fallback")
ActionList:Get(1, A.Pirouette).highlighted = false
before = #castLog
expect(E.TryGCD(ctx) and #castLog == before, "no readable step: wait, never guess")
Player.gauge = { 0, 0, 2, 4, 1, 3, 4 }
setReady(A.QuadrupleTechnicalFinish)
expect(E.TryGCD(ctx) and lastCastID() == A.QuadrupleTechnicalFinish, "four steps done: Quadruple Technical Finish")

-- A step the engine has just had accepted counts as dancing before the status shows.
c = resetHarness()
quietCooldowns()
setCooldown(A.StandardStep, 0, 30)
setReady(A.StandardStep)
setStatus(ST.StandardFinish, 40)
ctx = directContext()
expect(E.TryGCD(ctx) and lastCastID() == A.StandardStep, "Standard Step on cooldown")
expect(E.Dancing() == "STANDARD", "an accepted Standard Step is dancing")

----------------------------------------------------------------------------
-- Dance gating.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setCooldown(A.TechnicalStep, 0, 120)
setCooldown(A.StandardStep, 0, 30)
setReady(A.TechnicalStep) setReady(A.StandardStep)
ctx = directContext()
ctx.nextBurst = 0
expect(E.TryGCD(ctx) and lastCastID() == A.StandardStep, "no Standard Finish buff: Standard Step before Technical Step")
c = resetHarness()
quietCooldowns()
setCooldown(A.TechnicalStep, 0, 120)
setReady(A.TechnicalStep) setReady(A.StandardStep)
setStatus(ST.StandardFinish, 40)
ctx = directContext()
ctx.nextBurst = 0
expect(E.TryGCD(ctx) and lastCastID() == A.TechnicalStep, "buffed: Technical Step goes first")
ctx.ttk = 8
setReady(A.Cascade)
expect(not E.TechnicalStepAllowed(ctx), "Technical Step is skipped on a dying target")

c = resetHarness()
quietCooldowns()
setStatus(ST.StandardFinish, 40)
ctx = directContext()
ctx.nextBurst = 3
expect(not E.StandardStepAllowed(ctx), "a Standard dance that would overlap Technical Step is held")
ctx.nextBurst = 7
expect(E.StandardStepAllowed(ctx), "one that fits goes out")
ctx.burstActive = true
expect(not E.StandardStepAllowed(ctx), "never a five-second dance inside the burst")

----------------------------------------------------------------------------
-- Burst order: Tillana, Dance of the Dawn, Last Dance, Finishing Move, Saber, Starfall.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setStatus(ST.TechnicalFinish, 19)
setStatus(ST.FlourishingStarfall, 19)
for _, id in ipairs({ A.Tillana, A.DanceOfTheDawn, A.LastDance, A.FinishingMove, A.SaberDance, A.StarfallDance, A.Fountainfall, A.Cascade }) do setReady(id) end
ctx = directContext()
ctx.burstActive, ctx.burstRemaining, ctx.esprit = true, 19, 0
expect(E.TryGCD(ctx) and lastCastID() == A.Tillana, "burst opens with Tillana")
setReady(A.Tillana, false)
ctx.esprit = 50
expect(E.TryGCD(ctx) and lastCastID() == A.DanceOfTheDawn, "then Dance of the Dawn")
setReady(A.DanceOfTheDawn, false)
expect(E.TryGCD(ctx) and lastCastID() == A.LastDance, "then the banked Last Dance, before Finishing Move overwrites it")
setReady(A.LastDance, false)
expect(E.TryGCD(ctx) and lastCastID() == A.FinishingMove, "then Finishing Move")
setReady(A.FinishingMove, false)
expect(E.TryGCD(ctx) and lastCastID() == A.SaberDance, "then Saber Dance")
ctx.esprit = 20
expect(E.TryGCD(ctx) and lastCastID() == A.StarfallDance, "then Starfall Dance")
setReady(A.StarfallDance, false)
expect(E.TryGCD(ctx) and lastCastID() == A.Fountainfall, "then procs")
-- Tillana waits while its 50 Esprit would overcap, but never lapses.
setReady(A.Tillana) setReady(A.SaberDance)
ctx.esprit = 70
expect(E.TryGCD(ctx) and lastCastID() == A.SaberDance, "high Esprit: spend before Tillana")
setStatus(ST.FlourishingFinish, 6)
expect(E.TryGCD(ctx) and lastCastID() == A.Tillana, "a lapsing Tillana is pressed regardless")
-- Starfall Dance jumps the queue when Flourishing Starfall is running out.
Player.buffs = {}
setStatus(ST.TechnicalFinish, 4)
setStatus(ST.FlourishingStarfall, 4)
setReady(A.StarfallDance) setReady(A.Tillana, false)
ctx.esprit = 60
expect(E.TryGCD(ctx) and lastCastID() == A.StarfallDance, "a lapsing Starfall Dance goes first")

----------------------------------------------------------------------------
-- Outside the burst.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setStatus(ST.StandardFinish, 40)
for _, id in ipairs({ A.SaberDance, A.Fountainfall, A.ReverseCascade, A.Fountain, A.Cascade }) do setReady(id) end
ctx = directContext()
ctx.esprit = 70
expect(E.TryGCD(ctx) and lastCastID() == A.Fountainfall, "70 Esprit is pooled; Fountainfall before Reverse Cascade")
ctx.esprit = 80
expect(E.TryGCD(ctx) and lastCastID() == A.SaberDance, "80 Esprit is spent")
setReady(A.Fountainfall, false)
ctx.esprit = 0
expect(E.TryGCD(ctx) and lastCastID() == A.ReverseCascade, "Reverse Cascade before the combo")
setReady(A.ReverseCascade, false)
expect(E.TryGCD(ctx) and lastCastID() == A.Cascade, "Cascade starts the combo")
Player.lastcomboid, Player.combotimeremain = A.Cascade, 20
expect(E.TryGCD(ctx) and lastCastID() == A.Fountain, "Fountain continues it")
Player.lastcomboid, Player.combotimeremain = nil, nil
-- 85+ outranks the dances; an unused Last Dance goes before the next dance.
setCooldown(A.StandardStep, 0, 30)
setReady(A.StandardStep) setReady(A.LastDance)
ctx.esprit = 90
expect(E.TryGCD(ctx) and lastCastID() == A.SaberDance, "85+ Esprit is spent ahead of Standard Step")
ctx.esprit = 0
expect(E.TryGCD(ctx) and lastCastID() == A.LastDance, "Last Dance before Standard Step overwrites it")
setReady(A.LastDance, false)
expect(E.TryGCD(ctx) and lastCastID() == A.StandardStep, "then Standard Step")
-- Last Dance is kept for a burst that arrives while it is still up.
c = resetHarness()
quietCooldowns()
setStatus(ST.LastDanceReady, 25)
ctx = directContext()
ctx.nextBurst = 10
expect(not E.LastDanceAllowed(ctx), "Last Dance is kept for the burst")
ctx.nextBurst = 40
expect(E.LastDanceAllowed(ctx), "and spent when the burst is too far")

-- The permanent filler.
c = resetHarness()
quietCooldowns()
c.advancedEnabled = true
for key in pairs(CielDancerData.AbilityDefaults) do c.abilities[key] = false end
setReady(A.Cascade) setReady(A.Fountainfall) setReady(A.SaberDance)
ctx = directContext()
ctx.esprit = 100
expect(E.TryGCD(ctx) and lastCastID() == A.Cascade, "everything Off still presses Cascade")

-- AoE replacements are counted around the dancer.
c = resetHarness()
quietCooldowns()
setStatus(ST.StandardFinish, 40)
for _, id in ipairs({ A.Windmill, A.Cascade, A.Bloodshower, A.Fountainfall }) do setReady(id) end
ctx = directContext()
ctx.enemies = 2
expect(E.TryGCD(ctx) and lastCastID() == A.Bloodshower, "Bloodshower at two targets")
setReady(A.Bloodshower, false) setReady(A.Fountainfall, false)
expect(E.TryGCD(ctx) and lastCastID() == A.Windmill, "Windmill at two targets")
expect(lastCastTarget() == 100, "circles around the dancer are requested on the player")
ctx.enemies = 1
expect(E.TryGCD(ctx) and lastCastID() == A.Cascade, "Cascade on one")

----------------------------------------------------------------------------
-- oGCDs.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
setStatus(ST.TechnicalFinish, 20)
setReady(A.Devilment) setReady(A.Flourish) setReady(A.FanDance)
E.state.lastGCDID = A.QuadrupleTechnicalFinish
E.state.weavesSinceGCD = 0
ctx = directContext()
ctx.burstActive, ctx.burstRemaining, ctx.feathers = true, 20, 4
expect(E.TryOGCD(ctx) and lastCastID() == A.Devilment, "Devilment right behind Technical Finish")
expect(lastCastTarget() == 100, "on the player")
E.state.weavesSinceGCD = 1
expect(not E.TryOGCD(ctx), "one weave only behind a 1.5 s finish")
E.state.lastGCDID = A.Tillana
setReady(A.Devilment, false)
expect(E.TryOGCD(ctx) and lastCastID() == A.Flourish, "then Flourish")
-- Flourish would overwrite a waiting Threefold / Fourfold.
setStatus(ST.ThreefoldFanDance, 20)
setReady(A.FanDanceIII)
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx) and lastCastID() == A.FanDanceIII, "Fan Dance III before Flourish")
expect(not E.FlourishAllowed(ctx), "Flourish waits while Threefold is up")

c = resetHarness()
quietCooldowns()
setReady(A.FanDance)
E.state.weavesSinceGCD = 0
ctx = directContext()
ctx.feathers = 3
expect(not E.TryOGCD(ctx), "three feathers are kept outside the burst")
ctx.feathers = 4
expect(E.TryOGCD(ctx) and lastCastID() == A.FanDance, "four feathers are spent")
ctx.feathers = 0
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "a feather count of zero while Fan Dance is ready is not trusted")
ctx.feathers = 1
ctx.burstActive = true
E.state.weavesSinceGCD = 0
expect(E.TryOGCD(ctx), "the burst dumps every feather")
-- Flourish is kept for a burst that is seconds away.
c = resetHarness()
quietCooldowns()
ctx = directContext()
ctx.nextBurst = 5
expect(not E.FlourishAllowed(ctx), "Flourish waits for an imminent burst")
ctx.nextBurst = 50
expect(E.FlourishAllowed(ctx), "and is used on cooldown otherwise")
-- Esprit falls back to 50 whenever Saber Dance is ready.
Player.gauge = {}
setReady(A.SaberDance)
expect(E.GetEsprit(200) == 50, "a miscalibrated Esprit index cannot silence Saber Dance")

----------------------------------------------------------------------------
-- Pre-pull and the master switches.
----------------------------------------------------------------------------

c = resetHarness()
quietCooldowns()
c.enabled = true
c.requireCombat = true
Player.incombat = false
setCooldown(A.StandardStep, 0, 30)
setReady(A.StandardStep) setReady(A.Cascade)
E.OnUpdate()
expect(#castLog == 0, "an unarmed engine does nothing out of combat")
E.ArmPrepull(14)
E.OnUpdate()
expect(#castLog == 1 and lastCastID() == A.StandardStep, "an armed pre-pull starts the dance")
setStatus(ST.StandardStep, 12)
Player.gauge = { 0, 0, 2, 4, 0, 0, 2 }
setReady(A.DoubleStandardFinish)
E.OnUpdate()
expect(#castLog == 1, "the finish is held until combat starts: the engine never pulls for you")
Player.incombat = true
E.OnUpdate()
expect(lastCastID() == A.DoubleStandardFinish, "and lands as soon as it does")
Player.buffs = {}

c = resetHarness()
c.enabled = true
Player.job = 31
setReady(A.Cascade)
E.OnUpdate()
expect(#castLog == 0, "the engine must not act on another job")
Player.job = 38
'''


def run_static() -> None:
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((MODULE / "CielDancer_Data.lua").read_text(encoding="utf-8"))
    lua.execute(static_env())
    lua.execute((MODULE / "CielDancer_Rotation.lua").read_text(encoding="utf-8"))
    lua.execute(STATIC_SUITE)


STEPS = {"Emboite", "Entrechat", "Jete", "Pirouette"}


def run_timeline(verbose: bool = False) -> None:
    from sim_dnc.core import FightConfig, simulate
    from sim_dnc.run import format_report

    # --- The engine pulls: pre-pull Standard Step, potion, finish as the pull ----
    pre = simulate(FightConfig(seconds=40, start_in_combat=False, potions=1, engine={"requireCombat": False}))
    if verbose:
        print(format_report(pre, timeline_s=40))
    early = [e["name"] for e in pre.log if e["t"] < 0 and e["name"] not in STEPS]
    assert early == ["StandardStep", "Potion"], f"pre-pull was {early}"
    shown = [e["name"] for e in pre.log if e["t"] >= 0 and e["name"] not in STEPS]
    assert shown[:4] == ["DoubleStandardFinish", "TechnicalStep", "QuadrupleTechnicalFinish", "Devilment"], shown[:6]
    gcds = [e["name"] for e in pre.log if e["gcd"] and e["t"] > 0 and e["name"] not in STEPS]
    assert gcds[2] == "Tillana" and gcds[3] == "DanceOfTheDawn", f"burst opened with {gcds[:6]}"
    print("pre-pull and opener ok")

    # Someone else pulls: nothing until armed; armed dances but never pulls.
    waiting = simulate(FightConfig(seconds=10, start_in_combat=False, pull_after_s=12.0))
    assert all(e["t"] >= 0 for e in waiting.log), "an unarmed engine must not act before the pull"
    armed = simulate(FightConfig(seconds=10, start_in_combat=False, pull_after_s=12.0, arm_prepull_at_s=1.0))
    before = [e["name"] for e in armed.log if e["t"] < 0]
    assert before[0] == "StandardStep" and len(before) == 3 and set(before[1:]) <= STEPS, before
    assert armed.log[3]["name"] == "DoubleStandardFinish" and 0 <= armed.log[3]["t"] < 0.2, armed.log[3]
    print("armed pre-pull ok")

    # --- Six-minute fights on several seeds ------------------------------------
    for seed in range(1, 9):
        fight = simulate(FightConfig(seconds=360, seed=seed))
        stats, casts = fight.stats, fight.casts
        if verbose and seed == 1:
            print(format_report(fight))
        label = f"seed {seed}: "
        assert stats["wrong_steps"] == 0, label + "a wrong step was pressed"
        assert stats["broken_combos"] == 0, label + "the combo was broken"
        assert stats.get("lapsed_Dance", 0) == 0, label + "a dance lapsed"
        for key in ("SilkenSymmetry", "SilkenFlow", "FlourishingSymmetry", "FlourishingFlow", "FourfoldFanDance",
                    "LastDanceReady", "DanceOfTheDawnReady", "FlourishingFinish", "FlourishingStarfall"):
            assert stats.get(f"lapsed_{key}", 0) == 0, label + f"{key} lapsed unused"
        assert stats.get("overwritten_LastDanceReady", 0) == 0, label + "a Last Dance was overwritten"
        assert stats.get("overwritten_FourfoldFanDance", 0) == 0, label + "a Fan Dance IV was overwritten"
        assert stats["gcd_idle_s"] < 0.02 * fight.duration_s, label + str(stats)
        assert stats["feathers_wasted"] <= 2, label + str(stats)
        assert stats["esprit_wasted"] <= 60, label + str(stats)
        assert casts["TechnicalStep"] == 3 and casts["QuadrupleTechnicalFinish"] == 3, label + str(casts)
        assert casts["Devilment"] == 3 and casts["Tillana"] == 3 and casts["StarfallDance"] == 3, label + str(casts)
        assert casts["DanceOfTheDawn"] == 3, label + str(casts)
        assert casts["Flourish"] >= 6 and casts["FanDanceIV"] >= 6, label + str(casts)
        assert casts["FinishingMove"] + casts["StandardStep"] >= 11, label + str(casts)
        assert casts.get("SingleStandardFinish", 0) == 0 and casts.get("StandardFinish", 0) == 0, label + "short dance"
        assert casts["LastDance"] >= casts["FinishingMove"] + casts["DoubleStandardFinish"] - 1, label + str(casts)
        # Weaves: none inside a dance, one behind a finish or a Step, two otherwise.
        current, after = 0, None
        for entry in fight.log:
            if entry["gcd"]:
                current, after = 0, entry["name"]
                continue
            current += 1
            if after in STEPS:
                raise AssertionError(label + f"{entry['name']} weaved inside a dance")
            limit = 1 if after and (after.endswith("Finish") or after.endswith("Step")) else 2
            assert current <= limit, label + f"{current} weaves behind {after}"
        # Devilment goes out within a weave of every Technical Finish.
        names = [e["name"] for e in fight.log]
        for index, name in enumerate(names):
            if name == "QuadrupleTechnicalFinish":
                assert names[index + 1] == "Devilment", label + f"after Technical Finish came {names[index + 1]}"
    print("six-minute fights ok (8 seeds)")

    # --- Multi-target -------------------------------------------------------------
    pack = simulate(FightConfig(seconds=120, enemies=3, seed=3))
    assert pack.casts.get("Windmill", 0) > 0 and pack.casts.get("Cascade", 0) == 0, pack.casts
    assert pack.casts.get("FanDanceII", 0) > 0 and pack.casts.get("FanDance", 0) == 0, pack.casts
    assert pack.stats["broken_combos"] == 0
    print("multi-target ok")


if __name__ == "__main__":
    parse_all()
    run_static()
    print("static priority cases ok")
    run_timeline(verbose="-v" in sys.argv)
    print("CielDancer Lua syntax, mocked-runtime and timeline invariants passed.")
