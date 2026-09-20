#!/usr/bin/env python3
"""The shared smart hold (CielShared.hold) across the three modules, and Dancer's partner choice.

Holding must stop the two-minute burst from *starting* and keep the potion, and must not
stop anything that would otherwise be lost: the GCD, cooldown weaponskills, procs, and
resources that are about to overcap. A burst that is already running finishes.
"""

import sys
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def shared_flag() -> None:
    """One flag, three engines, never persisted."""
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        import run_mch_gui_tests as gui
    lua = LuaRuntime(unpack_returned_tuples=True)
    mods = ["CielBard", "CielMachinist", "CielDancer"]
    for m in mods:
        lua.execute((ROOT / m / f"{m}_Data.lua").read_text(encoding="utf-8"))
    lua.execute(gui.ENV_LUA)
    for m in mods:
        lua.execute((ROOT / m / f"{m}_Rotation.lua").read_text(encoding="utf-8"))
        lua.execute((ROOT / m / f"{m}.lua").read_text(encoding="utf-8"))
        lua.execute(f'handlers["{m}.Init"]()')
    assert lua.eval("CielShared.hold") is False, "the hold starts off"
    lua.execute("CielBardEngine.SetHold(true)")
    assert all(lua.eval(f"{m}Engine.HoldActive()") for m in mods), "one switch reaches every module"
    lua.execute("CielDancerEngine.ToggleHold()")
    assert not any(lua.eval(f"{m}Engine.HoldActive()") for m in mods)
    # Never saved: nothing about the hold reaches the settings store.
    lua.execute("CielMachinistEngine.SetHold(true)")
    for m in mods:
        lua.execute(f'handlers["{m}.Update"]()')
        leaked = lua.eval(f'''(function() for k in pairs(Settings.{m}) do
            if k == "hold" or k == "holdAt" then return true end end return false end)()''')
        assert not leaked, f"{m} persisted the hold"
    # Auto release.
    lua.execute("CielMachinistEngine.config.holdAutoReleaseSeconds = 30; ticks = ticks + 31000")
    assert lua.eval("CielMachinistEngine.HoldActive()") is False, "the hold releases itself after the limit"
    assert lua.eval("CielShared.hold") is False
    # The floating button and the window draw without error in every module.
    lua.execute("CielBardEngine.SetHold(true)")
    for m, job in zip(mods, (23, 31, 38)):
        lua.execute(f"Player.job = {job}")
        lua.execute(f'handlers["{m}.Draw"]()')
        lua.execute(f"{m}UI.DrawWindow()")
    print("shared hold flag ok")


def simulated_holds() -> None:
    from sim_mch.core import FightConfig as MchConfig, build_runtime as mch_runtime, load_tables as mch_tables
    from sim_dnc.core import FightConfig as DncConfig, build_runtime as dnc_runtime, load_tables as dnc_tables

    # --- Machinist: hold from 1:50 to 2:30 ---------------------------------------
    lua = mch_runtime(MchConfig(seconds=400), mch_tables())
    lua.execute("""
        function runUntil(t) while clock - CLOCK0 < t * 1000 do CielMachinistEngine.Step(true) advance(30) end end
        runUntil(110) CielMachinistEngine.SetHold(true) runUntil(150) CielMachinistEngine.SetHold(false) runUntil(200)
    """)
    log = [dict(e.items()) for e in lua.globals().sim.log.values()]
    t0 = lua.globals().sim.pullAt / 1000
    during = [e for e in log if 110 <= e["t"] - t0 < 150]
    names = [e["name"] for e in during]
    assert "BarrelStabilizer" not in names and "Wildfire" not in names, "the burst must not start while holding"
    assert {"AirAnchor", "Drill", "ChainSaw", "Excavator"} & set(names) >= {"AirAnchor", "Drill", "ChainSaw"}, \
        f"tools keep rolling while holding: {sorted(set(names))}"
    gcds = [e["t"] for e in during if e["gcd"]]
    assert max(b - a for a, b in zip(gcds, gcds[1:])) < 2.6, "the GCD never stops while holding"
    assert lua.globals().sim.wasted.heat == 0 and lua.globals().sim.wasted.battery <= 20, "nothing overcaps while holding"
    after = [e["name"] for e in log if 150 <= e["t"] - t0 < 175]
    assert "BarrelStabilizer" in after and "Wildfire" in after and "Hypercharge" in after, f"release starts the burst: {after}"
    queen = [e for e in log if e["name"] == "AutomatonQueen" and 150 <= e["t"] - t0 < 175]
    assert queen, "the pooled battery goes into the released burst"
    fires = [dict(w.items()) for w in lua.globals().sim.wildfires.values()]
    assert all(w["hits"] == 6 for w in fires), fires
    print("machinist hold ok")

    # --- Machinist: a hold pressed mid-burst does not abandon it -------------------
    lua = mch_runtime(MchConfig(seconds=60), mch_tables())
    lua.execute("""
        function runUntil(t) while clock - CLOCK0 < t * 1000 do CielMachinistEngine.Step(true) advance(30) end end
        runUntil(3) CielMachinistEngine.SetHold(true) runUntil(40)
    """)
    names = [e.name for e in lua.globals().sim.log.values()]
    assert "Wildfire" in names and "FullMetalField" in names and names.count("BlazingShot") >= 5, \
        "Barrel Stabilizer was already out: the burst is finished, not abandoned"
    print("machinist mid-burst hold ok")

    # --- Dancer: hold from 1:50 to 2:30, several seeds ------------------------------
    for seed in (1, 2, 3, 4):
        lua = dnc_runtime(DncConfig(seconds=400, seed=seed), dnc_tables())
        lua.execute("""
            function runUntil(t) while clock - CLOCK0 < t * 1000 do CielDancerEngine.Step(true) advance(30) end end
            runUntil(110) CielDancerEngine.SetHold(true) runUntil(150) CielDancerEngine.SetHold(false) runUntil(200)
        """)
        sim = lua.globals().sim
        log = [dict(e.items()) for e in sim.log.values()]
        # The hold is timed on the client clock; the pull (first damage) comes a Standard dance later.
        t0 = lua.globals().CLOCK0 / 1000
        during = [e["name"] for e in log if 112 <= e["t"] - t0 < 150]
        assert "TechnicalStep" not in during and "Devilment" not in during, f"seed {seed}: burst started while holding"
        assert "StandardStep" in during or "FinishingMove" in during, f"seed {seed}: Standard Step keeps going: {during}"
        lapsed = {k: v for k, v in sim.lapsed.items()}
        assert not lapsed, f"seed {seed}: something lapsed while holding: {lapsed}"
        assert sim.wasted.feathers <= 1, f"seed {seed}: feathers overcapped while holding"
        after = [e["name"] for e in log if 150 <= e["t"] - t0 < 175]
        assert "TechnicalStep" in after and "Devilment" in after and "Tillana" in after, f"seed {seed}: {after}"
    print("dancer hold ok (4 seeds)")


def bard_hold() -> None:
    """Bard, through the full simulator: the hold must stop Raging Strikes and nothing else."""
    from sim.runconfig import FightConfig
    from sim.core import Simulation

    from sim import client as sim_client

    # The Bard simulator creates its client inside run(), so the hold is switched from the
    # client's own step: on from 1:50 to 2:30 of the fight clock.
    real_step = sim_client.FakeClient.step

    def step_with_hold(self):
        self._lua.globals().CielShared.hold = 110_000 <= self._now_ms < 150_000
        return real_step(self)

    sim_client.FakeClient.step = step_with_hold
    try:
        result = Simulation(FightConfig(seconds=200.0, seed=3)).run()
    finally:
        sim_client.FakeClient.step = real_step
    casts = [(c.t_s, c.key) for c in result.casts]
    during = [name for t, name in casts if 112 <= t < 150]
    assert not {"RagingStrikes", "BattleVoice", "RadiantFinale", "Barrage"} & set(during), during
    assert "EmpyrealArrow" in during and "BurstShot" in during, "the rotation keeps running while holding"
    assert {"WanderersMinuet", "MagesBallad", "ArmysPaeon"} & set(during), "songs keep cycling while holding"
    gcds = [t for t, name in casts if 112 <= t < 150 and name in ("BurstShot", "RefulgentArrow", "IronJaws", "ApexArrow", "BlastArrow")]
    assert max(b - a for a, b in zip(gcds, gcds[1:])) < 5.1, "the GCD keeps rolling while holding"
    after = [name for t, name in casts if 150 <= t < 165]
    assert "RagingStrikes" in after and "BattleVoice" in after, f"release starts the burst: {after}"
    print("bard hold ok")


PARTNER_SUITE = r'''
local A = CielDancerData.Actions
local ST = CielDancerData.Statuses
local E = CielDancerEngine
local function expect(condition, message) if not condition then error(message, 2) end end
local function member(id, name, job, extra)
    local e = { id = id, name = name, job = job, alive = true, buffs = {}, distance2d = 10 }
    for k, v in pairs(extra or {}) do e[k] = v end
    return e
end

-- The Balance: SAM > PCT/RPR/VPR/MNK/NIN > DRG/BLM > RDM > SMN > MCH > BRD > DNC > tanks > healers.
local R = CielDancerData.PartnerRank
expect(R[34] < R[42] and R[42] < R[39] and R[30] < R[22] and R[25] < R[35] and R[35] < R[27], "melee and caster tiers")
expect(R[27] < R[31] and R[31] < R[23] and R[23] < R[38] and R[38] < R[32] and R[19] < R[40], "ranged, then tanks, then healers")

local c = resetHarness()
quietCooldowns()
c.enabled = true
Player.incombat = false
setReady(A.ClosedPosition)
entityList = { member(100, "Me", 38), member(301, "Tank", 19), member(302, "Healer", 24),
    member(303, "Bard", 23), member(304, "Dragoon", 22), member(305, "Samurai", 34) }
E.OnUpdate()
expect(lastCastID() == A.ClosedPosition and lastCastTarget() == 305, "Samurai is the first choice")

-- No Samurai: the first job of the next tier present. Dead or out-of-party members never count.
c = resetHarness()
quietCooldowns()
c.enabled = true
Player.incombat = false
setReady(A.ClosedPosition)
entityList = { member(301, "Tank", 19), member(303, "Bard", 23), member(304, "Dragoon", 22),
    member(306, "Ninja", 30), member(307, "Dead Samurai", 34, { alive = false }), member(200, "Boss") }
E.OnUpdate()
expect(lastCastTarget() == 306, "Ninja outranks Dragoon; a dead Samurai and an enemy are ignored")

-- Already partnered: nothing is pressed, and never in combat.
c = resetHarness()
quietCooldowns()
c.enabled = true
setReady(A.ClosedPosition) setReady(A.Ending)
entityList = { member(303, "Bard", 23, { buffs = { { id = ST.DancePartner, ownerid = 100, duration = 0 } } }),
    member(305, "Samurai", 34) }
Player.incombat = true
setReady(A.Cascade)
E.state.weavesSinceGCD = 0
local ctx = directContext()
expect(not E.TryPartner(), "in combat a partner is never swapped")
expect(E.HasPartner(), "a permanent status with zero duration still counts")
-- Out of combat the better partner is taken: Ending first.
c = resetHarness()
quietCooldowns()
c.enabled = true
Player.incombat = false
setReady(A.ClosedPosition) setReady(A.Ending)
entityList = { member(303, "Bard", 23, { buffs = { { id = ST.DancePartner, ownerid = 100, duration = 0 } } }),
    member(305, "Samurai", 34) }
E.OnUpdate()
expect(lastCastID() == A.Ending and lastCastTarget() == 100, "out of combat: Ending, to take the Samurai")
-- Someone else's partner mark does not count as mine.
c = resetHarness()
quietCooldowns()
c.enabled = true
Player.incombat = false
setReady(A.ClosedPosition)
entityList = { member(305, "Samurai", 34, { buffs = { { id = ST.DancePartner, ownerid = 999, duration = 0 } } }) }
E.OnUpdate()
expect(lastCastTarget() == 305, "another dancer's partner is still available to me")
-- Off means off; solo means nothing to do.
c = resetHarness()
quietCooldowns()
c.enabled = true
c.autoPartner = false
Player.incombat = false
setReady(A.ClosedPosition)
entityList = { member(305, "Samurai", 34) }
E.OnUpdate()
expect(#castLog == 0, "automatic partner Off presses nothing")
c = resetHarness()
quietCooldowns()
c.enabled = true
Player.incombat = false
setReady(A.ClosedPosition)
entityList = {}
E.OnUpdate()
expect(#castLog == 0, "solo: no Closed Position")
'''


def partner_choice() -> None:
    import run_dnc_mock_tests as dnc
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((ROOT / "CielDancer" / "CielDancer_Data.lua").read_text(encoding="utf-8"))
    lua.execute(dnc.static_env())
    lua.execute((ROOT / "CielDancer" / "CielDancer_Rotation.lua").read_text(encoding="utf-8"))
    lua.execute(PARTNER_SUITE)
    print("dance partner choice ok")


if __name__ == "__main__":
    shared_flag()
    simulated_holds()
    bard_hold()
    partner_choice()
    print("Smart hold and dance partner invariants passed.")
