"""Module B tests: the fake MMOMinion client driving the shipped CielBard Lua engine.

Written pytest-style (plain `assert`) inside `unittest.TestCase` subclasses so both
runners work. Action specs are derived from `CielBard/CielBard_Data.lua` directly; this
file must not import `sim.tables`.
"""

from __future__ import annotations

import re
import statistics
import sys
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.client import (  # noqa: E402
    ActionSpec,
    ActionView,
    BuffView,
    EntityView,
    FakeClient,
    LuaBridgeError,
    PlayerView,
    PotionView,
)

DATA_LUA = (ROOT / "CielBard" / "CielBard_Data.lua").read_text(encoding="utf-8")

PLAYER_ID = 100
TARGET_ID = 200

# Song status ids the simulator uses; the engine only ever compares
# action.statusgainedid to buff.id, so self-consistency is what matters.
SONG_STATUS = {"WanderersMinuet": 865, "MagesBallad": 139, "ArmysPaeon": 138}

CHARGE_POOL = {"HeartbreakShot", "Bloodletter", "RainOfDeath"}
OGCD_RECAST = {
    "EmpyrealArrow": 15.0,
    "Sidewinder": 60.0,
    "PitchPerfect": 1.0,
    "HeartbreakShot": 15.0,
    "Bloodletter": 15.0,
    "RainOfDeath": 15.0,
    "Barrage": 120.0,
    "RagingStrikes": 120.0,
    "BattleVoice": 120.0,
    "RadiantFinale": 110.0,
    "WanderersMinuet": 120.0,
    "MagesBallad": 120.0,
    "ArmysPaeon": 120.0,
    "SecondWind": 120.0,
    "Troubadour": 90.0,
    "NaturesMinne": 120.0,
    "WardensPaean": 45.0,
}


def _lua_block(name: str) -> str:
    """Return the text of one `CielBardData.<name> = { ... }` block."""
    start = DATA_LUA.index(f"CielBardData.{name} = {{")
    end = DATA_LUA.index("\n}", start)
    return DATA_LUA[start:end]


def _named_ids(name: str) -> dict[str, int]:
    return {k: int(v) for k, v in re.findall(r"(\w+)\s*=\s*(\d+)", _lua_block(name))}


def _bracket_ids(name: str) -> set[int]:
    return {int(v) for v in re.findall(r"\[(\d+)\]\s*=\s*true", _lua_block(name))}


ACTION_IDS = _named_ids("Actions")
GCD_IDS = _bracket_ids("GCD")
SELF_TARGET_IDS = _bracket_ids("SelfTarget")


def build_specs() -> list[ActionSpec]:
    """One ActionSpec per shipped action id, derived from CielBard_Data.lua."""
    specs: list[ActionSpec] = []
    for key, action_id in sorted(ACTION_IDS.items()):
        is_gcd = action_id in GCD_IDS
        recast = 2.5 if is_gcd else OGCD_RECAST.get(key, 60.0)
        specs.append(
            ActionSpec(
                action_id=action_id,
                name=key,
                is_gcd=is_gcd,
                self_target=action_id in SELF_TARGET_IDS,
                recast_s=recast,
                max_charges=3 if key in CHARGE_POOL else 1,
                status_gained_id=SONG_STATUS.get(key, 0),
            )
        )
    return specs


SPECS = build_specs()
SPEC_BY_KEY = {s.name: s for s in SPECS}


def action_id(key: str) -> int:
    return ACTION_IDS[key]


def default_player(**kwargs: Any) -> PlayerView:
    base = dict(id=PLAYER_ID, job=23, alive=True, incombat=True, hp_percent=100.0)
    base.update(kwargs)
    return PlayerView(**base)


def default_target(**kwargs: Any) -> EntityView:
    base = dict(
        id=TARGET_ID,
        name="Striking Dummy",
        hp_current=1.0e9,
        hp_max=1.0e9,
        hp_percent=100.0,
        distance2d=3.0,
    )
    base.update(kwargs)
    return EntityView(**base)


def idle_actions(**ready_keys: bool) -> dict[int, ActionView]:
    """Every action usable and off cooldown; `ready` only where asked for."""
    views: dict[int, ActionView] = {}
    for spec in SPECS:
        ready = bool(ready_keys.get(spec.name, False))
        views[spec.action_id] = ActionView(
            cd=0.0, cdmax=0.0, isoncd=False, usable=True, ready=ready, highlighted=False
        )
    return views


def make_client(overrides: dict[str, Any] | None = None, **kwargs: Any) -> FakeClient:
    """A client with the shipped Lua loaded and the engine initialised."""
    client = FakeClient(ROOT, SPECS, player_id=PLAYER_ID, target_id=TARGET_ID, **kwargs)
    config: dict[str, Any] = {"debug": False}
    if overrides:
        config.update(overrides)
    client.init_engine(config)
    return client


def live_client(overrides: dict[str, Any] | None = None, **kwargs: Any) -> FakeClient:
    """A client configured so `step()` reaches the decision code every pulse."""
    config: dict[str, Any] = {
        "enabled": True,
        "debug": False,
        "pulseMs": 0,
        "requestThrottleMs": 0,
        "requireCombat": True,
        "requireLOS": False,
    }
    if overrides:
        config.update(overrides)
    client = make_client(config, **kwargs)
    client.set_time(1)
    client.set_player(default_player())
    target = default_target()
    client.set_target(target)
    client.set_entities([target])
    client.set_actions(idle_actions())
    client.set_last_cast(0, 999999)
    return client


class ClientCase(unittest.TestCase):
    """Base case that always closes the client it made."""

    def setUp(self) -> None:
        self._clients: list[FakeClient] = []

    def tearDown(self) -> None:
        for client in self._clients:
            client.close()

    def client(self, overrides: dict[str, Any] | None = None, **kwargs: Any) -> FakeClient:
        made = make_client(overrides, **kwargs)
        self._clients.append(made)
        return made

    def live(self, overrides: dict[str, Any] | None = None, **kwargs: Any) -> FakeClient:
        made = live_client(overrides, **kwargs)
        self._clients.append(made)
        return made


class TestLoadAndInit(ClientCase):
    def test_loads_shipped_lua_and_inits(self) -> None:
        client = self.client()
        assert client.data["Version"] == "0.5.3"
        assert int(client.data["BardJobID"]) == 23
        assert client.warnings() == []
        assert client.engine.state["lastDecision"] == "Initialized"
        assert client.errors == []

    def test_missing_lua_raises_bridge_error(self) -> None:
        try:
            FakeClient(ROOT / "no-such-dir", SPECS)
        except LuaBridgeError as exc:
            assert "CielBard_Data.lua" in str(exc)
        else:
            raise AssertionError("expected LuaBridgeError")

    def test_config_overrides_flat_and_nested(self) -> None:
        client = self.client(
            {"enabled": True, "abilities.ApexArrow": False, "aoeTargets.Ladonsbite": 3}
        )
        assert client.config["enabled"] is True
        assert client.config["abilities"]["ApexArrow"] is False
        assert int(client.config["aoeTargets"]["Ladonsbite"]) == 3
        # The shipped defaults must not have been mutated by the deep copy.
        assert client.data["AbilityDefaults"]["ApexArrow"] is True
        assert int(client.data["AoEDefaults"]["Ladonsbite"]) == 2
        # sim/README.md's multi-target table copies these by hand, so pin the
        # two it got wrong: Rain of Death is 2 (100/target vs Heartbreak Shot
        # 180), and ShadowbiteBarrage is the Barrage-specific gate at 3.
        assert int(client.data["AoEDefaults"]["RainOfDeath"]) == 2
        assert int(client.data["AoEDefaults"]["ShadowbiteBarrage"]) == 3
        # Advanced mode makes the engine read the per-ability table.
        client.init_engine({"debug": False, "advancedEnabled": True, "abilities.ApexArrow": False})
        assert client.engine.AbilityEnabled("ApexArrow") is False

    def test_unknown_config_key_raises(self) -> None:
        client = self.client()
        for bad in ("notAKey", "abilities.NotAnAbility", "nope.deeper"):
            try:
                client.init_engine({bad: 1})
            except KeyError:
                pass
            else:
                raise AssertionError(f"expected KeyError for {bad}")
        client.init_engine({"_allow_new": True, "brandNew": 5, "nested.leaf": 7})
        assert int(client.config["brandNew"]) == 5
        assert int(client.config["nested"]["leaf"]) == 7


class TestLuaTypes(ClientCase):
    def test_containers_are_lua_tables(self) -> None:
        client = self.client()
        client.set_player(default_player(buffs=(BuffView(865, PLAYER_ID, 40.0),)))
        target = default_target(buffs=(BuffView(1201, PLAYER_ID, 30.0),))
        client.set_target(target)
        client.set_entities([target])
        lua = client.lua
        assert lua.eval('type(Player.gauge)') == "table"
        assert lua.eval('type(Player.buffs)') == "table"
        assert lua.eval('type(EntityList("alive,attackable"))') == "table"
        assert lua.eval('next(Player.buffs) ~= nil') is True
        assert lua.eval('type(Player.buffs[1])') == "table"
        assert lua.eval('type(Player:GetTarget().buffs)') == "table"
        assert lua.eval('next(EntityList("alive")) ~= nil') is True

    def test_callables_are_lua_functions(self) -> None:
        # A bare Python callable answers type() == "userdata", which would send the
        # engine down its "API missing" fallbacks (os.clock time, Inventory scan,
        # nil target). Everything the engine type-checks must be a Lua function.
        client = self.client()
        lua = client.lua
        for expr in (
            "Now",
            "MIsLoading",
            "MIsLocked",
            "MIsCasting",
            "GetItem",
            "d",
            "Player.GetTarget",
            "ActionList.IsCasting",
            "ActionList:Get(1, 16495).IsReady",
            "ActionList:Get(1, 16495).Cast",
        ):
            assert lua.eval(f"type({expr})") == "function", expr
        # table.valid stays undefined so the engine uses its own valid() fallback.
        assert lua.eval("type(table.valid)") == "nil"

    def test_now_is_monotonic_and_visible(self) -> None:
        client = self.client()
        client.set_time(1234)
        assert client.lua.eval("Now()") == 1234
        client.set_time(1234)
        assert client.now_ms == 1234

    def test_set_time_monotonic_enforced(self) -> None:
        client = self.client()
        client.set_time(500)
        try:
            client.set_time(499)
        except ValueError as exc:
            assert "499" in str(exc)
        else:
            raise AssertionError("expected ValueError")


class TestGaugeAndCharges(ClientCase):
    def test_gauge_indices_visible_to_engine(self) -> None:
        client = self.client()
        client.set_player(default_player(gauge=(1, 2, 30, 85, 0)))
        assert int(client.engine.GetSoulVoice()) == 85
        assert int(client.engine.GetRepertoire()) == 2
        assert int(client.engine.GetGauge(3)) == 30
        assert int(client.engine.GetGauge(1)) == 1

    def test_charge_reading_matches_live_layout(self) -> None:
        client = self.client()
        heartbreak = action_id("HeartbreakShot")
        client.set_action(heartbreak, ActionView(cd=30.5, cdmax=45.0, isoncd=True, usable=True))
        client.engine.UpdateCharges()
        state = client.engine_state()
        assert int(state["charges"]) == 2
        assert abs(float(state["chargeRemaining"]) - 14.5) < 0.01
        assert int(state["maxCharges"]) == 3

        client.set_action(heartbreak, ActionView(cd=7.7, cdmax=45.0, isoncd=True, usable=True))
        client.engine.UpdateCharges()
        assert int(client.engine_state()["charges"]) == 0

        client.set_action(heartbreak, ActionView(cd=0.0, cdmax=0.0, isoncd=False, usable=True))
        client.engine.UpdateCharges()
        state = client.engine_state()
        assert int(state["charges"]) == 3
        assert float(state["chargeRemaining"]) == 0.0

    def test_gcd_remaining_uses_cd_and_cdmax(self) -> None:
        client = self.client()
        client.set_action(
            action_id("BurstShot"), ActionView(cd=1.0, cdmax=2.5, isoncd=True, usable=True)
        )
        client.set_action(
            action_id("HeavyShot"), ActionView(cd=1.0, cdmax=2.5, isoncd=True, usable=False)
        )
        assert abs(float(client.engine.GCDRemaining(None)) - 1.5) < 1e-9


class TestTargetingAndCasts(ClientCase):
    def test_self_target_actions_reject_enemy_id(self) -> None:
        client = self.client()
        keys = ["RagingStrikes", "BattleVoice", "Barrage", "RadiantFinale",
                "WanderersMinuet", "MagesBallad", "ArmysPaeon"]
        for key in keys:
            aid = action_id(key)
            assert aid in SELF_TARGET_IDS, key
            client.set_action(aid, ActionView(usable=True, ready=True))
            action = client.lua.eval(f"ActionList:Get(1, {aid})")
            assert action.IsReady(action, TARGET_ID) is False, key
            assert action.IsReady(action, PLAYER_ID) is True, key
        burst = client.lua.eval(f"ActionList:Get(1, {action_id('BurstShot')})")
        client.set_action(action_id("BurstShot"), ActionView(usable=True, ready=True))
        assert burst.IsReady(burst, TARGET_ID) is True

    def test_cast_records_request_and_returns_true(self) -> None:
        client = self.client()
        client.set_time(4200)
        aid = action_id("BurstShot")
        client.set_action(aid, ActionView(usable=True, ready=True))
        action = client.lua.eval(f"ActionList:Get(1, {aid})")
        assert action.Cast(action, TARGET_ID) is True
        requests = client.take_requests()
        assert len(requests) == 1
        assert requests[0].action_id == aid
        assert requests[0].target_id == TARGET_ID
        assert requests[0].is_item is False
        assert requests[0].request_ms == 4200
        assert client.take_requests() == []
        assert client.take_rejections() == []

    def test_cast_when_not_ready_records_rejection_and_returns_false(self) -> None:
        client = self.client()
        client.set_time(900)
        aid = action_id("Sidewinder")
        client.set_action(aid, ActionView(usable=True, ready=False))
        action = client.lua.eval(f"ActionList:Get(1, {aid})")
        assert action.Cast(action, TARGET_ID) is False
        rejections = client.take_rejections()
        assert len(rejections) == 1
        assert rejections[0].reason == "not-ready"
        assert rejections[0].action_id == aid
        assert rejections[0].request_ms == 900
        assert client.take_requests() == []

        song = action_id("MagesBallad")
        client.set_action(song, ActionView(usable=True, ready=True))
        song_action = client.lua.eval(f"ActionList:Get(1, {song})")
        assert song_action.Cast(song_action, TARGET_ID) is False
        rejections = client.take_rejections()
        assert [r.reason for r in rejections] == ["self-target-mismatch"]

    def test_unknown_action_returns_unusable_stub(self) -> None:
        client = self.client()
        stub = client.lua.eval("ActionList:Get(1, 987654)")
        assert 987654 in client.unknown_action_ids
        assert stub.usable is False
        assert float(stub.cd) == 0.0
        assert float(stub.cdmax) == 0.0
        assert stub.isoncd is False
        assert float(stub.recasttime) == 0.0
        assert stub.IsReady(stub, TARGET_ID) is False
        assert stub.Cast(stub, TARGET_ID) is False
        assert [r.reason for r in client.take_rejections()] == ["unknown-action"]
        # Cached: the same object comes back every time, with no reallocation.
        again = client.lua.eval("ActionList:Get(1, 987654)")
        assert again.id == stub.id

    def test_engine_targets_self_actions_at_the_player(self) -> None:
        client = self.live()
        views = idle_actions(WanderersMinuet=True)
        # A rolling GCD with room to weave: the engine only reaches TryOGCD when
        # the GCD is not ready but more than weaveMinGcdRemaining is left.
        for key in ("BurstShot", "HeavyShot"):
            views[action_id(key)] = ActionView(cd=1.0, cdmax=2.5, isoncd=True, usable=True)
        client.set_actions(views)
        client.set_time(50)
        assert client.step() is True
        requests = client.take_requests()
        assert len(requests) == 1
        assert requests[0].action_id == action_id("WanderersMinuet")
        assert requests[0].target_id == PLAYER_ID
        assert client.take_rejections() == []


class TestStatusObservation(ClientCase):
    def test_song_status_detection(self) -> None:
        client = self.client()
        client.set_player(default_player(buffs=(BuffView(865, PLAYER_ID, 40.0),)))
        key, remaining = client.engine.GetSong()
        assert key == "WM"
        assert abs(float(remaining) - 40.0) < 1e-9
        # The status path was used, so the 45 s local fallback never ran.
        assert float(client.engine.state["songStartedAt"]) == 0.0
        assert client.engine.state["currentSong"] == "NONE"
        # A song buff owned by someone else does not count.
        client.set_player(default_player(buffs=(BuffView(865, 999, 40.0),)))
        key, remaining = client.engine.GetSong()
        assert key == "NONE"
        assert float(remaining) == 0.0

    def test_dot_ownership_respected(self) -> None:
        client = self.client()
        client.set_player(default_player())
        mine = default_target(
            buffs=(BuffView(1201, PLAYER_ID, 41.0), BuffView(1200, PLAYER_ID, 39.0))
        )
        client.set_target(mine)
        client.lua.execute(
            "function probe_dots() return CielBardEngine.GetDotState(Player:GetTarget()) end"
        )
        storm, caustic = client.lua.globals().probe_dots()
        assert abs(float(storm) - 41.0) < 1e-9
        assert abs(float(caustic) - 39.0) < 1e-9

        theirs = default_target(
            buffs=(BuffView(1201, 777, 41.0), BuffView(1200, 777, 39.0))
        )
        client.set_target(theirs)
        storm, caustic = client.lua.globals().probe_dots()
        assert (float(storm), float(caustic)) == (0.0, 0.0)

    def test_last_cast_observation_counts_weaves(self) -> None:
        client = self.live()
        empyreal = action_id("EmpyrealArrow")
        client.set_time(100)
        client.set_last_cast(empyreal, 0)
        client.step()
        assert int(client.engine_state()["weavesSinceGCD"]) == 1

        # Same id, growing timesincecast: the same cast, not a new one.
        client.set_time(700)
        client.set_last_cast(empyreal, 600)
        client.step()
        assert int(client.engine_state()["weavesSinceGCD"]) == 1

        # timesincecast resets at execution, so the repeat is seen.
        client.set_time(1400)
        client.set_last_cast(empyreal, 0)
        client.step()
        state = client.engine_state()
        assert int(state["weavesSinceGCD"]) == 2
        assert state["lastActionName"] == "EmpyrealArrow"

        # A GCD cast resets the weave counter.
        client.set_time(2100)
        client.set_last_cast(action_id("BurstShot"), 0)
        client.step()
        assert int(client.engine_state()["weavesSinceGCD"]) == 0


class TestEntities(ClientCase):
    def test_entity_list_filter_drops_out_of_combat(self) -> None:
        client = self.client()
        target = default_target()
        idle = EntityView(id=301, name="Idle add", incombat=False, pos=(1.0, 0.0, 0.0))
        fighting = EntityView(id=302, name="Add", incombat=True, pos=(2.0, 0.0, 0.0))
        client.set_entities([target, idle, fighting])
        lua = client.lua
        lua.execute(
            "function probe_count(f) local n = 0 for _ in pairs(EntityList(f)) do n = n + 1 end"
            " return n end"
        )
        assert int(lua.globals().probe_count("alive,attackable,maxdistance=30")) == 3
        assert int(lua.globals().probe_count("alive,attackable,incombat,maxdistance=25")) == 2
        # Shrinking the list removes the stale keys.
        client.set_entities([target])
        assert int(lua.globals().probe_count("alive,attackable,maxdistance=30")) == 1

    def test_entity_list_filter_applies_maxdistance(self) -> None:
        """`maxdistance=N` is enforced, because the engine never re-checks it.

        `E.FindMultiDotTarget` trusts the filter and reads no `distance2d` of its
        own, so an unbounded `--enemy-spread` used to hand it entities the live
        client would never have listed.
        """
        client = self.client()
        target = default_target()
        near = EntityView(id=301, name="Near add", distance2d=20.0, pos=(1.0, 0.0, 0.0))
        far = EntityView(id=302, name="Far add", distance2d=33.0, pos=(2.0, 0.0, 0.0))
        client.set_entities([target, near, far])
        lua = client.lua
        lua.execute(
            "function probe_ids(f) local t = {} for id in pairs(EntityList(f)) do"
            " t[#t + 1] = id end table.sort(t) return table.concat(t, ',') end"
        )
        assert lua.globals().probe_ids("alive,attackable,maxdistance=30") == "200,301"
        assert lua.globals().probe_ids("alive,attackable,incombat,maxdistance=25") == "200,301"
        # A tighter bound drops the 20-yalm add as well.
        assert lua.globals().probe_ids("alive,attackable,maxdistance=10") == "200"
        # No maxdistance clause means no distance bound.
        assert lua.globals().probe_ids("alive,attackable") == "200,301,302"

    def test_target_none_is_nil(self) -> None:
        client = self.client()
        client.set_player(default_player())
        client.set_target(default_target())
        assert client.lua.eval("Player:GetTarget() ~= nil") is True
        client.set_target(None)
        assert client.lua.eval("Player:GetTarget() == nil") is True
        assert client.engine.GetTarget() is None


class TestPotions(ClientCase):
    def test_getitem_hq_preference(self) -> None:
        client = self.client({"usePotion": True})
        hq = 49235 + 1000000
        client.set_potions([PotionView(hqid=hq, action_id=900001, ready=True)])
        client.lua.execute(
            "function probe_item(h) local ok, i, a = pcall(GetItem, h, {0,1,2,3})"
            " if not ok or not i then return nil end return i.hqid, a.id end"
        )
        found = client.lua.globals().probe_item(hq)
        assert int(found[0]) == hq
        assert int(found[1]) == 900001
        assert client.lua.globals().probe_item(49235) is None

        client.set_potions([PotionView(hqid=49235, action_id=900002, ready=True)])
        found = client.lua.globals().probe_item(49235)
        assert int(found[0]) == 49235
        assert client.lua.globals().probe_item(hq) is None

        client.set_potions([])
        assert client.lua.globals().probe_item(49235) is None
        assert client.lua.eval('type(GetItem)') == "function"

    def test_engine_finds_and_casts_a_potion(self) -> None:
        client = self.live({"usePotion": True, "potionOnlyWithBurst": False})
        hq = 49235 + 1000000
        client.set_potions([PotionView(hqid=hq, action_id=900001, ready=True)])
        client.engine.RefreshPotion(True)
        assert client.engine.PotionAvailable() is True
        assert client.engine.PotionReady() is True
        assert "Grade 4" in str(client.engine_state()["potionName"])
        assert client.warnings() == []

        client.lua.execute(
            "function probe_potion() return CielBardEngine.TryPotion("
            "{ target = Player:GetTarget(), ttk = 999 }, 'test') end"
        )
        # TryPotion refuses within 3 s of the last potion (state starts at 0).
        client.set_time(5000)
        assert client.lua.globals().probe_potion() is True
        requests = client.take_requests()
        assert len(requests) == 1
        assert requests[0].is_item is True
        assert requests[0].hqid == hq
        assert requests[0].action_id == 900001
        assert requests[0].target_id == PLAYER_ID

    def test_potion_not_ready_is_refused(self) -> None:
        client = self.client({"usePotion": True})
        hq = 49235 + 1000000
        client.set_potions([PotionView(hqid=hq, action_id=900001, ready=False, cd=30.0)])
        client.engine.RefreshPotion(True)
        assert client.engine.PotionAvailable() is True
        assert client.engine.PotionReady() is False
        assert client.warnings() == []

    def test_missing_potion_produces_configuration_warning(self) -> None:
        client = self.client({"usePotion": True})
        client.set_potions([])
        client.engine.RefreshPotion(True)
        warnings = client.warnings()
        assert len(warnings) == 1
        assert "Gemdraught" in warnings[0]


class TestErrors(ClientCase):
    def test_step_wraps_lua_error(self) -> None:
        def boom(_message: str) -> None:
            raise RuntimeError("debug sink exploded")

        client = self.live({"debug": True}, debug_sink=boom)
        client.set_time(2000)
        try:
            client.step()
        except LuaBridgeError as exc:
            assert "debug sink exploded" in str(exc)
            assert "2000ms" in str(exc)
        else:
            raise AssertionError("expected LuaBridgeError")

    def test_callback_error_is_recorded_and_seen_by_pcall(self) -> None:
        client = self.live()
        # A self-target action evaluates int(target_id); a Lua table is not an int.
        aid = action_id("RagingStrikes")
        client.set_action(aid, ActionView(usable=True, ready=True))
        client.set_time(3000)
        client.lua.execute(
            "function probe_ready(id) local ac = ActionList:Get(1, id)"
            " local ok, r = pcall(function() return ac:IsReady({}) end) return ok, r end"
        )
        ok, _result = client.lua.globals().probe_ready(aid)
        assert ok is False
        assert len(client.errors) == 1
        assert "IsReady" in client.errors[0]
        assert "3000ms" in client.errors[0]

    def test_step_on_closed_client_raises(self) -> None:
        client = make_client()
        client.close()
        client.close()  # idempotent
        try:
            client.step()
        except LuaBridgeError:
            pass
        else:
            raise AssertionError("expected LuaBridgeError")


class TestEngineState(ClientCase):
    def test_engine_state_is_plain_python(self) -> None:
        client = self.live()
        client.set_time(60)
        client.step()
        state = client.engine_state()
        for name in (
            "lastDecision",
            "lastActionName",
            "weavesSinceGCD",
            "currentSong",
            "songRemaining",
            "charges",
            "chargeRemaining",
            "ttk",
            "ttkBand",
            "gcdRemaining",
            "gcdsSinceRaging",
            "codaCount",
        ):
            assert name in state, name
            assert isinstance(state[name], (bool, int, float, str, type(None))), name
        assert state["codaCount"] == 0
        assert state["ttkBand"] in ("LEARNING", "SUSTAIN", "EXTENDED_TAIL",
                                    "IDEAL_FINISH", "TERMINAL")


class TestPerformance(ClientCase):
    def test_pulse_cost_smoke(self) -> None:
        client = self.live()
        player = default_player()
        target = default_target()
        views = idle_actions(BurstShot=True)
        samples: list[float] = []
        now = 1
        for index in range(2000):
            now += 30
            start = time.perf_counter()
            client.set_time(now)
            player.gauge = (1, index % 4, 30, index % 100, 0)
            client.set_player(player)
            target.hp_percent = 100.0 - index * 0.02
            target.hp_current = target.hp_max * target.hp_percent / 100.0
            client.set_target(target)
            client.set_entities([target])
            client.set_actions(views)
            client.set_last_cast(action_id("BurstShot"), (index % 5) * 100)
            client.step()
            client.take_requests()
            client.take_rejections()
            samples.append(time.perf_counter() - start)
        median_ms = statistics.median(samples) * 1000.0
        print(f"\n[test_pulse_cost_smoke] median pulse {median_ms:.3f} ms "
              f"over {len(samples)} pulses")
        assert client.errors == []
        assert median_ms < 2.0, f"median pulse {median_ms:.3f} ms"


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
