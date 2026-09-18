# CielBard Simulator — Implementation Specification

Version 1.0 · target engine: CielBard 0.5.0 · written 2026-09-17

This document is the complete contract for the Python package `sim` that lives at
`C:\dev\CielBard\sim`. It simulates a level-100 Bard on a single training dummy by
**driving the real, shipped CielBard Lua engine** through `lupa`.

An implementer must be able to build their assigned module from this document plus the
repository alone. Everything another module will hand you, or expect from you, is
reproduced here verbatim.

---

## 0. Ground rules

### 0.1 Hard constraints

1. **The engine under test is the shipped Lua, unmodified.** No file under
   `C:\dev\CielBard\CielBard\` may be created, edited, renamed or deleted by this work.
   The simulator loads `CielBard/CielBard_Data.lua` and `CielBard/CielBard_Rotation.lua`
   verbatim into a `LuaRuntime`. `CielBard/CielBard.lua` (GUI + MMOMinion settings proxy)
   is **not** loaded — it is not part of the decision engine.
2. **Both existing suites must stay green.** After your change:
   ```
   "C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" tests/run_mock_tests.py
   "C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" tests/run_gui_tests.py
   ```
   Neither may be edited.
3. **Game mechanics are data-driven.** Every potency, duration, recast, proc rate, buff
   percentage and status id lives in JSON under `sim/data/`. An expansion patch must be a
   table edit, never a code edit. No mechanic constant may be written as a literal in
   `sim/core.py`, `sim/damage.py` or the CLI.
4. **Deterministic given a seed.** Two runs with the same `FightConfig` produce
   byte-identical `FightResult` JSON. No use of `random` module-level functions, no
   `set`/`dict` iteration order dependence for anything that reaches output, no wall clock
   in any computed value (only in the "generated at" line of reports).
5. **Fast enough for sweeps.** Budget: a 510 s fight at the shipped 30 ms pulse must run in
   **≤ 2.0 s** on one core of the dev machine; 1000 such fights must complete in **≤ 5 min**
   using the batch runner's process pool. Section 6.7 lists the mandatory optimisations.
6. **No two modules share a file.** Ownership is listed in §2. If a file you need does not
   exist yet because its owner has not landed, stub it inside your own test file — never
   create a file you do not own.

### 0.2 Python, style, tests

- Interpreter: `C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe`
  (has `lupa` 2.8 and `luaparser`). Plain `python` is a Store stub — never use it.
- Standard library only, plus `lupa`. No numpy, pandas, pytest requirement, no new
  dependency in `tests/requirements.txt`.
- Tests are written **pytest-style** (plain `assert`, module-level `test_*` functions are
  allowed) **but must also run under `unittest`**. Concretely: every test file defines
  `unittest.TestCase` subclasses whose methods use plain `assert`. That satisfies both
  runners. Test files live in `tests/` and are named `test_*.py`.
- Canonical test invocation (Module E owns the runner):
  ```
  "C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" tests/run_sim_tests.py
  ```
  which is equivalent to `python -m unittest discover -s tests -p "test_*.py" -t .`.
- Type hints on every public signature. Docstrings on every public class and function —
  the docstrings given in this spec are the minimum content, not a suggestion.
- Line length 100. No emoji anywhere in code, output or docs.

### 0.3 Directory layout

```
sim/
  SPEC.md                  (this file — already exists, do not edit)
  __init__.py              A
  rng.py                   A
  tables.py                A
  damage.py                A
  data/
    actions.json           A
    statuses.json          A
    job.json               A
    stats.json             A
  client.py                B
  core.py                  C
  events.py                C
  runconfig.py             C
  run.py                   D
  batch.py                 D
  sweep.py                 D
  calibrate.py             D
  report.py                D
  output/                  D creates at runtime; E owns output/.gitkeep
  README.md                E
tests/
  test_tables.py           A
  test_damage.py           A
  test_client.py           B
  test_core.py             C
  test_cli.py              D
  test_integration.py      E
  run_sim_tests.py         E
```

---

## 1. The system in one page

```
          +-------------------------------------------------------+
          |  sim.core.Simulation          (Module C)               |
          |  owns THE CLOCK, the event heap, and all game state    |
          +-------------------------------------------------------+
             |  every pulse (config.pulseMs)         ^   cast request
             |  writes a mirror of game state        |   (action_id, target_id)
             v                                       |
          +-------------------------------------------------------+
          |  sim.client.FakeClient        (Module B)               |
          |  Python objects + Lua tables in a LuaRuntime:          |
          |  Now, Player, ActionList, EntityList, MIs*, GetItem    |
          +-------------------------------------------------------+
             |  CielBardEngine.Step(false)           ^
             v                                       |
          +-------------------------------------------------------+
          |  CielBard_Data.lua + CielBard_Rotation.lua  (SHIPPED)  |
          +-------------------------------------------------------+

  sim.tables / sim.damage / sim.rng   (Module A)  <- pure data + math, no Lua
  sim.run / batch / sweep / calibrate (Module D)  <- drives C, writes reports
  tests/test_integration.py           (Module E)  <- end-to-end invariants
```

**Nobody advances time except `Simulation`.** The Lua engine's `Now()` is a read of the
simulation clock. The client never schedules anything. The CLI never touches the clock.

---

## 2. Module split (5 modules, parallel-safe)

| Module | Owns files | Depends on | Can start |
|---|---|---|---|
| **A — data + damage** | `sim/__init__.py`, `sim/rng.py`, `sim/tables.py`, `sim/damage.py`, `sim/data/*.json`, `tests/test_tables.py`, `tests/test_damage.py` | nothing | immediately |
| **B — fake client** | `sim/client.py`, `tests/test_client.py` | `lupa`, the shipped Lua | immediately |
| **C — game core** | `sim/core.py`, `sim/events.py`, `sim/runconfig.py`, `tests/test_core.py` | A (§4), B (§5) — both fully specified here | immediately, against the literal dataclasses in §4.6 and §5.2 |
| **D — runner/CLI** | `sim/run.py`, `sim/batch.py`, `sim/sweep.py`, `sim/calibrate.py`, `sim/report.py`, `tests/test_cli.py` | C (§6.9) | immediately, against the literal dataclasses in §6.9 |
| **E — integration** | `tests/test_integration.py`, `tests/run_sim_tests.py`, `sim/README.md`, `sim/output/.gitkeep` | D | immediately, against §8 |

Modules C, D and E may write a temporary private stub of an upstream type **inside their
own test file** while waiting, e.g. `tests/test_core.py` may define a minimal
`_StubClient`. They must never create `sim/client.py`.

`sim/__init__.py` (Module A) must contain exactly:

```python
"""CielBard simulator: drives the shipped CielBard Lua engine over a modelled fight."""

__version__ = "1.0.0"
ENGINE_VERSION = "0.5.0"
```

---

## 3. Facts about the engine and the live client that the sim must honour

These are load-bearing. Violating any of them silently produces a simulator that measures
something other than the shipped engine.

### 3.1 Engine entry points and globals

`CielBard_Rotation.lua` defines the global `CielBardEngine` (aliased `E`). The sim uses:

| Symbol | Use |
|---|---|
| `CielBardEngine.Init(configTable)` | called once; `configTable` **must be a Lua table** |
| `CielBardEngine.Step(false)` | one decision pulse; returns `true` if a request was issued |
| `CielBardEngine.state` | read-only diagnostics (see §5.6) |
| `CielBardEngine.GetConfigurationWarnings()` | list of warning strings |
| `CielBardData.Defaults` | the config template to deep-copy |

Globals the engine reads (all supplied by `FakeClient`):

`Now()`, `Player`, `ActionList`, `EntityList(filter)`, `MIsLoading()`, `MIsLocked()`,
`MIsCasting()`, `GetItem(hqid, bags)` (optional), `Inventory` (optional, absent),
`d(string)` (optional debug sink), `table.valid` (optional, absent).

### 3.2 `valid()` and Lua types — the single biggest trap

`CielBard_Rotation.lua`:

```lua
local function valid(value)
    if type(table.valid) == "function" then return table.valid(value) end
    return type(value) == "table" and next(value) ~= nil
end
```

Verified on lupa 2.8: **`type(python_object)` in Lua is `"userdata"`, not `"table"`.**
Therefore every container the engine passes to `valid()`, `pairs()` or `ipairs()` **must be
a real Lua table**, or the engine silently sees "no data":

- `Player.gauge` — `valid()` + numeric index → **Lua table**, 1-based, indices 1..5 filled.
- `Player.buffs` — `valid()` + `pairs()` → **Lua table** of **Lua tables**.
- `entity.buffs` (target and every entity) → **Lua table** of **Lua tables**.
- the `EntityList(filter)` return value → **Lua table**, `pairs()`-iterated.
- the config table passed to `Init` → **Lua table** (`c.abilities`, `c.aoeTargets` are
  `pairs()`-iterated).
- `CielBardData.Potions`, `.Songs`, `.GCD`, `.SelfTarget` are already Lua tables.

Scalar-only holders may be Python objects, because they are only attribute-read:
`Player`, `Player.hp`, `Player.castinginfo`, each entity, each `ActionList` action, each
inventory item. `Player.hp.percent` works on a Python object; `valid(Player.hp)` is never
called.

### 3.3 Method calls from Lua

`ac:IsReady(id)`, `ac:Cast(id)`, `ActionList:Get(1, id)`, `Player:GetTarget()`,
`item:IsReady(id)`, `item:Cast(id)`, `item:GetAction()` are colon calls. Probed on lupa
2.8: a Python **bound** method receives only the explicit arguments — lupa strips the
duplicated receiver. Do not rely on that across versions: Module B decorates every
Lua-callable method with

```python
def lua_method(fn):
    """Make a method callable both as Lua `obj:M(a)` and as Python `obj.M(a)`.

    lupa passes the receiver again for some runtime/version combinations; drop a
    leading argument that is the receiver itself.
    """
    @functools.wraps(fn)
    def wrapper(self, *args):
        if args and args[0] is self:
            args = args[1:]
        return fn(self, *args)
    return wrapper
```

The runtime must be created as `LuaRuntime(unpack_returned_tuples=True)` — the engine does
`local ok, item, itemAction = pcall(GetItem, hqid, {...})`, and a Python function returning
a tuple only becomes multiple Lua values under that flag (verified).

`pcall` around a Python call works: a Python exception becomes a caught Lua error. The
engine wraps `IsReady` and `Cast` in `pcall`, so a bug in the client turns into "action not
ready" rather than a crash. **Module B must therefore never swallow its own exceptions** —
it records them in `FakeClient.errors` and `Simulation` re-raises at end of fight
(§6.8).

### 3.4 Cooldown / charge semantics observed on the live client

Reproduce exactly:

| Situation | `cd` | `cdmax` | `isoncd` | `recasttime` |
|---|---|---|---|---|
| Action off cooldown (incl. non-charged) | `0` | `0` | `false` | its recast |
| Non-charged action rolling | elapsed s | total s | `true` | its recast |
| GCD (Burst Shot) rolling | elapsed s | current GCD recast (2.5 base) | `true` | the current GCD recast |
| Charged action, partial stack | elapsed s in `[0, recast*maxCharges)` | `recast * maxCharges` (45 for Heartbreak) | `true` | 15 |
| Charged action, full stack | `0` | `0` | `false` | 15 |

`remaining = cdmax - cd`. `charges = floor(cd / recasttime)`.
`chargeRemaining = recast - (cd % recast)`.

The engine's `E.UpdateCharges()` and the shipped test at
`tests/run_mock_tests.py:607-619` pin this. The simulator must produce identical readings:
`recasttime=15, cdmax=45, cd=30.5 -> 2 charges, 14.5 s to next`.

For the GCD group, `recasttime` is the **hasted** recast, so it agrees with `cdmax`.
`Simulation._sync_client` republishes it through `FakeClient.set_recast` whenever Army's
Paeon or Army's Muse moves the GCD (a handful of writes per fight, not one per pulse):
under full Paeon haste both read 2.10, never a `cdmax` of 2.10 beside a `recasttime` of
2.50, which is a pair no live client would produce.

**The client action queue.** `IsReady` does not reflect the recast on live clients
(`CielBard/CielBard_Rotation.lua:1006-1007`), which is the whole reason `E.GCDRemaining`
exists and reads `cdmax - cd` instead. The engine exploits the game's action queue: it
enters `E.TryGCD` as soon as `gcdRemaining <= gcdLeadSeconds` (default 0.05,
`CielBard_Rotation.lua:1021`) and the client holds the request until the recast ends. The
simulator models the queue with `job.gcd_queue_window_s` (0.5, the in-game queue): a GCD
request arriving with `0 < gcd_ready - t <= gcd_queue_window_s` is **accepted** and
resolved at `gcd_ready`, and everything — the animation lock, the next `gcd_ready`, the
cooldown, `last_cast_us`, the `action_execute` event and `CastRecord.t_s` — is computed
from that instant. A request further out than the window is still rejected
`gcd-not-ready`. Without this, every GCD slips to the next pulse boundary,
`gcdLeadSeconds` is inert, and `clipped_s` measures pulse-grid commensurability instead
of rotation quality.

### 3.5 Targeting

`IsReady(targetID)` is **false for self-targeted actions when asked about an enemy id**.
`CielBardData.SelfTarget` lists them (songs, Raging Strikes, Battle Voice, Barrage, Radiant
Finale, the four utilities). The engine passes `Player.id` for those. The fake client
enforces the same rule, so a regression in engine targeting shows up as "action never
fires".

### 3.6 Gauge

`config.soulVoiceGaugeIndex = 4`, `config.repertoireGaugeIndex = 2`,
`config.songTimerGaugeIndex = 3` (1-based Lua indices). Fill `Player.gauge[1..5]`:

| index | contents |
|---|---|
| 1 | song id proxy: 0 none, 1 WM, 2 MB, 3 AP |
| 2 | repertoire: Pitch Perfect stacks under WM, Army's Paeon stacks under AP, 0 under MB (Mage's Ballad maintains no visible Repertoire counter; `ballad_procs` stays internal to the charge pool) |
| 3 | song timer, seconds remaining (integer) |
| 4 | Soul Voice 0..100 |
| 5 | coda bitmask, 1=WM 2=MB 4=AP (engine ignores it today; provided for future use) |

Index 2 semantics follow the live gauge: it is whatever "Repertoire" counter the current
song maintains. Under WM it is the 0..3 Pitch Perfect stack count, which is what
`E.TryOGCD` consumes; under AP it is the 0..4 Army's Paeon haste stack count; under MB it
is **0**, because Mage's Ballad maintains no visible Repertoire counter — its procs only
advance the shared Heartbreak/Bloodletter charge pool, and `ballad_procs` stays internal
to the core. This is not cosmetic: `CielBard_Rotation.lua` gates Pitch Perfect inside the
burst on `ctx.repertoire >= 3` without checking the song, so publishing a Ballad proc
count here would drive the engine into Pitch Perfect attempts that `_resource_ok` rejects,
and invariant 12 of §8.2 requires zero rejections.

### 3.7 Song detection

`E.GetSong()` matches `ActionList:Get(1, songId).statusgainedid` against `Player.buffs[].id`
with `ownerid == Player.id`, and falls back to a local 45 s timer. The client must expose
`statusgainedid` on the three song actions and put the matching buff on the player, so the
**status path** is exercised (the fallback then never fires — assert that in tests).

### 3.8 Last-cast observation

`Player.castinginfo.lastcastid` / `.timesincecast` (ms) drive weave counting, coda tracking
and burst-window state. `E.ObserveLastCast` treats a cast as new when
`castID ~= lastObservedCastID or since + 50 < lastObservedTimeSince`. So a repeated cast of
the same action is only seen if `timesincecast` drops by more than 50 ms — the client must
reset it to `0` at execution and grow it every pulse.

---

## 4. Module A — data tables, RNG, stat/damage model

**Owns:** `sim/__init__.py`, `sim/rng.py`, `sim/tables.py`, `sim/damage.py`,
`sim/data/{actions,statuses,job,stats}.json`, `tests/test_tables.py`, `tests/test_damage.py`.
**Imports nothing from B, C, D, E.**

### 4.1 `sim/data/actions.json`

One JSON object, key = CielBard ability key (exactly the keys in
`CielBardData.Actions` / `CielBardData.AbilityDefaults`), so the core can map engine
decisions to mechanics without a translation table.

Record schema (unknown keys are an error; missing optional keys take the default shown):

```jsonc
{
  "BurstShot": {
    "id": 16495,                  // must equal CielBardData.Actions.BurstShot
    "name": "Burst Shot",
    "kind": "gcd",                // "gcd" | "ogcd" | "song" | "buff" | "item"
    "potency": 220,
    "recast_s": 2.5,              // GCD recast for kind=="gcd" (scaled by haste at runtime)
    "cooldown_s": 0.0,            // own cooldown; 0 => shares the GCD
    "max_charges": 1,
    "self_target": false,
    "aoe": false,
    "falloff": 0.0,               // secondary-target damage share, 0 = single target
    "multi_hit_eligible": false,  // Barrage makes this land statuses.Barrage.weaponskill_hits
                                  //   times; gcd only; Refulgent Arrow alone carries it
    "barrage_potency": 0,         // Barrage raises this action's potency to this value
                                  //   instead of multiplying its hits; gcd only; mutually
                                  //   exclusive with multi_hit_eligible; 0 = no override
    "grants": [                   // status applications on execution
      {"status": "HawksEye", "chance": 0.35}
    ],
    "requires": [],               // statuses consumed; action unavailable without them
    "status_gained_id": 0,        // mirrored to action.statusgainedid
    "notes": "35% Hawk's Eye"
  }
}
```

Required entries and their values (level 100, single target). `potency` is the action's own
potency; DoT tick potency lives in `statuses.json`.

| key | id | kind | potency | cooldown_s | charges | notes |
|---|---:|---|---:|---:|---:|---|
| `HeavyShot` | 97 | gcd | 160 | 0 | 1 | level-sync fallback only; never expected at 100 |
| `BurstShot` | 16495 | gcd | 220 | 0 | 1 | 35 % `HawksEye`; not a Barrage weaponskill |
| `RefulgentArrow` | 7409 | gcd | 280 | 0 | 1 | requires `HawksEye`; `multi_hit_eligible` (840 under Barrage) |
| `Stormbite` | 7407 | gcd | 100 | 0 | 1 | applies `Stormbite` |
| `CausticBite` | 7406 | gcd | 150 | 0 | 1 | applies `CausticBite` |
| `IronJaws` | 3560 | gcd | 100 | 0 | 1 | refreshes + resnapshots both DoTs |
| `ApexArrow` | 16496 | gcd | scaled | 0 | 1 | aoe, no falloff; see §4.4 |
| `BlastArrow` | 25784 | gcd | 700 | 0 | 1 | aoe, `falloff` 0.5; requires `BlastArrowReady` |
| `ResonantArrow` | 36976 | gcd | 640 | 0 | 1 | aoe, `falloff` 0.5; requires `ResonantArrowReady` |
| `RadiantEncore` | 36977 | gcd | scaled | 0 | 1 | aoe, `falloff` 0.5; requires `RadiantEncoreReady`; 700/800/1100 by codas consumed by the Finale that granted it |
| `Ladonsbite` | 25783 | gcd | 140 | 0 | 1 | aoe cone, no falloff, 35 % `HawksEye`; not a Barrage weaponskill |
| `Shadowbite` | 16494 | gcd | 200 | 0 | 1 | aoe, no falloff, requires `HawksEye`; `barrage_potency` 300 |
| `QuickNock` | 106 | gcd | 110 | 0 | 1 | pre-76 fallback; not a Barrage weaponskill |
| `EmpyrealArrow` | 3558 | ogcd | 260 | 15 | 1 | guaranteed Repertoire |
| `Sidewinder` | 3562 | ogcd | 400 | 60 | 1 | |
| `HeartbreakShot` | 36975 | ogcd | 180 | 15 | 3 | `cdmax = 45` |
| `Bloodletter` | 110 | ogcd | 130 | 15 | 3 | shares the charge pool; see §4.7 note 2 |
| `RainOfDeath` | 117 | ogcd | 100 | 15 | 3 | aoe, shares the charge pool |
| `PitchPerfect` | 7404 | ogcd | scaled | 1 | 1 | 100/220/360 by stacks; WM only |
| `Barrage` | 107 | buff | 0 | 120 | 1 | grants `Barrage` (10 s, see §4.2 note) + `ResonantArrowReady` + `HawksEye` |
| `RagingStrikes` | 101 | buff | 0 | 120 | 1 | grants `RagingStrikes` 20 s |
| `BattleVoice` | 118 | buff | 0 | 120 | 1 | grants `BattleVoice` 20 s |
| `RadiantFinale` | 25785 | buff | 0 | 110 | 1 | grants `RadiantFinale` 20 s + `RadiantEncoreReady` 30 s |
| `WanderersMinuet` | 3559 | song | 0 | 120 | 1 | |
| `MagesBallad` | 114 | song | 0 | 120 | 1 | |
| `ArmysPaeon` | 116 | song | 0 | 120 | 1 | |
| `SecondWind` | 7541 | buff | 0 | 120 | 1 | utility, off by default |
| `Troubadour` | 7405 | buff | 0 | 90 | 1 | utility |
| `NaturesMinne` | 7408 | buff | 0 | 120 | 1 | utility |
| `WardensPaean` | 3561 | buff | 0 | 45 | 1 | utility |
| `Windbite` | 113 | gcd | 60 | 0 | 1 | pre-64 fallback; never used at 100 |
| `VenomousBite` | 100 | gcd | 100 | 0 | 1 | pre-64 fallback |
| `Potion` | 900000 | item | 0 | 270 | 1 | id is a placeholder; see §5.5 |

Every id **must** match `CielBardData.Actions`. `tests/test_tables.py` asserts that by
parsing the Lua with `luaparser` or a regex over `CielBard/CielBard_Data.lua` — a mismatch
is a test failure, not a silent drift.

### 4.2 `sim/data/statuses.json`

```jsonc
{
  "Stormbite": {
    "id": 1201,                   // must equal CielBardData.Statuses.Stormbite
    "name": "Stormbite",
    "duration_s": 45.0,
    "on_target": true,
    "dot_potency": 25,            // per 3 s tick, 0 if not a DoT
    "snapshots": true,
    "max_stacks": 1
  }
}
```

Required statuses:

| key | id | duration | dot_potency | effect |
|---|---:|---:|---:|---|
| `Stormbite` | 1201 | 45 | 25 | target DoT |
| `CausticBite` | 1200 | 45 | 20 | target DoT |
| `Windbite` | 129 | 30 | 20 | legacy target DoT |
| `VenomousBite` | 124 | 30 | 20 | legacy target DoT |
| `HawksEye` | 3861 | 30 | 0 | enables Refulgent / Shadowbite |
| `RagingStrikes` | 125 | 20 | 0 | `damage_mult = 1.15` |
| `BattleVoice` | 141 | 20 | 0 | `dh_add = 0.20` |
| `RadiantFinale` | 2722 | 20 | 0 | `damage_mult` 1.02/1.04/1.06 by codas |
| `BlastArrowReady` | 2692 | 10 | 0 | enables Blast Arrow |
| `ResonantArrowReady` | 3862 | 30 | 0 | enables Resonant Arrow |
| `RadiantEncoreReady` | 3863 | 30 | 0 | enables Radiant Encore |
| `Barrage` | 128 | 10 | 0 | `weaponskill_hits = 3`: the next `multi_hit_eligible` weaponskill (Refulgent Arrow) lands three times; an action with `barrage_potency` takes that potency instead. Corrections 8's 30 s is the Resonant Arrow window, which `ResonantArrowReady` carries |
| `WanderersMinuet` | 865 | 45 | 0 | `crit_add = 0.02`; `status_gained_id` of action 3559 |
| `MagesBallad` | 139 | 45 | 0 | `damage_mult = 1.01`; `status_gained_id` of action 114 |
| `ArmysPaeon` | 138 | 45 | 0 | `dh_add = 0.03`; `status_gained_id` of action 116 |
| `ArmysMuse` | 1932 | 10 | 0 | post-Paeon haste, see §4.5 |
| `ArmysEthos` | 1933 | 30 | 0 | post-Paeon carry-over, see §4.5 |
| `Medicated` | 49 | 30 | 0 | `damage_mult` from `stats.json` |

**Verification note (must be reproduced in `calibration.md` §7.4):** the DoT status ids
(1200/1201/129/124) are cross-checked against `CielBardData.Statuses`. **All other status
ids above are internal to the simulator** — the engine only ever compares
`action.statusgainedid` to `buff.id`, never to a hard-coded number, so self-consistency is
sufficient. They are flagged as unverified rather than presented as live-client facts.

**Barrage's effect** is a table mechanic, not code, and per the job guide it is not
always a triple hit:

- `statuses.json` `Barrage` carries `weaponskill_hits: 3`, and `actions.json`
  `multi_hit_eligible: true` marks the weaponskills that land that many times. **Only
  Refulgent Arrow carries it** (280 -> 840).
- `actions.json` `barrage_potency` marks the flat potency increase the AoE Hawk's Eye
  weaponskills take instead: Shadowbite 200 -> 300 *per target*. (Wide Volley's
  140 -> 220 is the same rule below level 72; Wide Volley is absent from
  `CielBardData.Actions`, so the simulator has no record for it.) The two fields are
  mutually exclusive and `tables.py` rejects a record that sets both.
- `Simulation._potency_for` substitutes the override at cast time so that the cast record
  and the damage events agree; `Simulation._consume_multi_hit` repeats the damage and
  removes the status when the cast lands.
- Everything else - Heavy Shot, Burst Shot, Ladonsbite, Quick Nock, Resonant Arrow, Apex,
  the DoTs, Radiant Encore, every off-GCD and the potion - neither benefits from the buff
  nor consumes it. That rule is what makes MECHANICS_CORRECTIONS.md item 15 reachable:
  the engine casts Resonant Arrow in the GCD between Barrage and the Refulgent Arrow.

The arithmetic this produces is the point of the v0.5.1 review's second high-priority
finding: at two targets a Barrage-Refulgent Arrow is 840 while a Barrage-Shadowbite is
only 300 x 2 = 600, so Shadowbite wins from three targets (900) upward even though a
plain Hawk's Eye proc already prefers it at two (400 vs 280). The potencies come from the
tooltips; what stays an **assumption** (§10) is that an ineligible weaponskill leaves the
buff untouched instead of wasting it.

### 4.3 `sim/data/job.json`

Mechanics that are not per-action:

```jsonc
{
  "gcd_base_s": 2.50,
  "gcd_rounding_ms": 10,
  "anim_lock_gcd_s": 0.60,
  "anim_lock_ogcd_s": 0.60,
  "server_tick_s": 3.0,
  "repertoire_proc_chance": 0.80,
  "repertoire_on_song_timer": true,
  "repertoire_independent_of_dots": true,
  "repertoire_skip_final_tick": true,
  "soul_voice_per_repertoire": 5,
  "soul_voice_max": 100,
  "pitch_perfect_max_stacks": 3,
  "pitch_perfect_potency": [100, 220, 360],
  "army_paeon_max_stacks": 4,
  "army_paeon_haste_per_stack_pct": 4.0,
  "army_muse_haste_by_stacks_pct": [1.0, 2.0, 4.0, 12.0],
  "army_ethos_s": 30.0,
  "ballad_charge_reduction_s": 7.5,
  "song_duration_s": 45.0,
  "coda_damage_mult": [1.0, 1.02, 1.04, 1.06],
  "radiant_encore_potency": [0, 700, 800, 1100],
  "apex": {"gauge_min": 20, "gauge_max": 100, "potency_min": 140, "potency_max": 700,
           "blast_gauge_threshold": 80},
  "hawks_eye_proc_chance": 0.35,
  "aoe_cluster_radius_yalms": 5.0,   // how far from the target an enemy may stand and
                                     //   still be splashed by an AoE; mirrors the 5 y
                                     //   cluster test in E.CountEnemiesNear
  "auto_attack_interval_s": 3.04,
  "gcd_queue_window_s": 0.5
}
```

`coda_damage_mult` and `radiant_encore_potency` are indexed by coda count 0..3.

`hawks_eye_proc_chance` is the single source of truth for the Hawk's Eye *proc* rate:
`Simulation._apply_grants` uses it for every `HawksEye` grant the action record writes
as a chance below 1 (Burst Shot, Stormbite, Caustic Bite, Iron Jaws, Ladonsbite),
whatever number that record carries, so a sweep or a `job_overrides` entry moves every
proc source at once. A grant written as certain stays certain: MECHANICS_CORRECTIONS.md
item 7 makes Barrage's Hawk's Eye guaranteed and the proc rate must not gate it.

The three `repertoire_*` booleans implement MECHANICS_CORRECTIONS.md item 1.
`repertoire_on_song_timer` puts the rolls on the song's own 3 s grid (42, 39, ... s
remaining) instead of the world tick, `repertoire_skip_final_tick` suppresses the roll
in the song's last 3 s, and `repertoire_independent_of_dots` (default `true`) is the
modelling assumption that a roll needs no DoT on the target; setting it to `false`
restores the DoT requirement. The superseded key `repertoire_requires_dot` is still
read as its inverse when the new key is absent, and `_validate_job` therefore requires
*one* of the two to be present and boolean rather than demanding the new spelling, so a
legacy `job.json` still loads. `army_ethos_s` is passed as the Army's Ethos duration by
`_end_song`.

`FightConfig.job_overrides` is merged on top of this table by
`Simulation._apply_job_overrides` and gets the data file's own checks: a `None` value
deletes a key (which is how an override reproduces a legacy table), any other key must
already exist in `job.json`, be one of `sim.core.LEGACY_JOB_KEYS`
(`repertoire_requires_dot`) or one of `sim.core.CORE_ONLY_JOB_KEYS` (`damage_delay_s`,
`level_sync_disabled`, `potion_hqid` — knobs the core reads with an in-code default
because they are not in the data file), and the merged mapping is re-validated with
`sim.tables._validate_job`. A misspelled key, a wrong type or an out-of-range value
raises `SimConfigError` instead of silently leaving the default in place — the same
protection `stat_overrides` has.

There is no `dot_tick_s`: DoTs tick on the server tick grid, so `server_tick_s` is the
DoT tick. A second key would have been a silent no-op.

`auto_attack_interval_s` is the Bard auto-attack delay; it only matters when
`stats.auto_attack_dps` is non-zero. `gcd_queue_window_s` is the client action queue
of §3.4.

### 4.4 `sim/data/stats.json`

```jsonc
{
  "crit_rate": 0.2454,
  "crit_mult": 1.60,
  "dh_rate": 0.2282,
  "dh_mult": 1.25,
  "crit_dh_independent": true,
  "potency_to_damage": 100.0,
  "auto_attack_dps": 0.0,
  "damage_variance": 0.05,
  "potion_damage_mult": 1.08
}
```

`crit_rate` / `dh_rate` are **base** rates, before any buff. The merged report's top-10
figures (25.366 % crit, 28.587 % DH) are *realized* event rates that already contain
Wanderer's Minuet (+2 % crit), Army's Paeon (+3 % DH) and Battle Voice (+20 % DH), all of
which `sim/damage.py` adds again through `snap.crit_add` / `snap.dh_add`. Using them
directly double-counts those buffs and inflates their marginal value in every sweep, so
they are deconvolved: `base = observed - E[bonus]`, with the expectation taken over the
simulator's own damage events (0.0083 crit, 0.0577 DH at the shipped song allocation).
`FightResult.crit_rate` / `.dh_rate` report the realized rates back, and `report`,
`format_batch` and the calibration header print them, so the round trip to 25.366 % /
28.587 % is checkable rather than invisible.

`auto_attack_dps` is real: a non-zero value schedules an `auto_attack` event every
`job.auto_attack_interval_s` and rolls the potency that produces that DPS at the model's
own unbuffed expectation through `DamageModel.roll` with the live snapshot, tagged
`source="auto"`. It ships at 0.0, so by default Bard auto attacks (~7-10 % of real aDPS)
are absorbed by `potency_to_damage`; `calibrate.LIMITATIONS` says so.

`potion_damage_mult` and `auto_attack_dps` are read by `sim.core`, not by `StatProfile`.
`Simulation.__init__` validates every `--stat` key against `stats.json` (raising
`SimConfigError`, not `TypeError`) and forwards only the `StatProfile` fields.
`crit_rate` / `dh_rate` defaults come from the top-10 observed rates in
`bard-analysis/output/merged-report.md` (25.366 % crit-event, 28.587 % DH). `crit_mult`
1.60 and `dh_mult` 1.25 are the brief's values. `potency_to_damage` is the single
calibration scalar (§7). `damage_variance` is FFXIV's +/-5 % damage roll; set it to 0.0 to
get the expected-value fast path.

### 4.5 Mechanics the tables must encode (narrative, for the core's benefit)

- **GCD**: `recast = round_down_to(gcd_base_s * (100 - haste_pct) / 100, gcd_rounding_ms)`.
- **Army's Paeon haste**: `haste_pct = stacks * army_paeon_haste_per_stack_pct` while the
  song is up. When Army's Paeon ends, the stack count at that moment selects
  `army_muse_haste_by_stacks_pct[stacks-1]` and grants `ArmysMuse` for its duration. If no
  song is started immediately, `ArmysEthos` holds the stack count for `army_ethos_s` and
  converts to `ArmysMuse` when the next song starts.
  **Verification note:** the brief says "haste stacks, up to 4, 4% each"; the Muse/Ethos
  conversion table above is the simulator's model and is *not* verifiable from any document
  in this repository. It is listed in `calibration.md` §7.4 as an unverified assumption.
- **Repertoire** (MECHANICS_CORRECTIONS.md item 1 supersedes the original DoT-gated
  model): the rolls sit on the *song's own* `server_tick_s` grid, not on the world tick.
  One roll at every `server_tick_s` of song time, from `song_duration_s - server_tick_s`
  remaining down to `server_tick_s` remaining (42 s, 39 s, ... 3 s for a 45 s song at a 3 s
  tick), each at `repertoire_proc_chance`; there is **no** roll in the song's final tick.
  A roll is **independent of the DoTs** unless `repertoire_independent_of_dots` is set to
  `false`, which restores the requirement that one of our DoTs be on the current target.
  The two grid flags are `repertoire_on_song_timer` and `repertoire_skip_final_tick`
  (§4.4). Empyreal Arrow grants one unconditionally. Every proc grants
  `soul_voice_per_repertoire` Soul Voice (capped) plus the song-specific effect:
  WM -> +1 Pitch Perfect stack (capped, overcap counted as waste);
  MB -> shared-charge progress += `ballad_charge_reduction_s`;
  AP -> +1 Army's Paeon stack (capped).
- **Codas**: each song cast adds its coda; Radiant Finale consumes all of them, its buff
  multiplier is `coda_damage_mult[n]` and the Radiant Encore it grants is worth
  `radiant_encore_potency[n]`.
- **Apex Arrow**: `potency = potency_min + (gauge - gauge_min) * (potency_max -
  potency_min) / (gauge_max - gauge_min)`, rounded to the nearest integer, clamped to
  `[potency_min, potency_max]`. Used at `gauge >= blast_gauge_threshold` it grants
  `BlastArrowReady`. **Verification note:** both endpoints - 140 potency at 20 gauge and
  700 at 100 - are the official job guide's Patch 7.5 values; the linear interpolation
  between them is the simulator's assumption.

### 4.6 Public API — literal signatures (C and D code against these)

`sim/rng.py`:

```python
class SeededRNG:
    """Deterministic named random streams.

    A named substream is independent of every other substream, so adding a roll to one
    system never perturbs another system's sequence. This is what makes the simulator's
    determinism robust to code changes rather than merely reproducible.
    """

    def __init__(self, seed: int) -> None: ...

    @property
    def seed(self) -> int: ...

    def stream(self, name: str) -> random.Random:
        """Return the `random.Random` for `name`, creating it on first use.

        The stream's seed is derived as
        `int.from_bytes(hashlib.blake2b(f"{seed}:{name}".encode(), digest_size=8), "big")`,
        which is stable across interpreter runs (unlike `hash()`).
        """
```

Mandatory stream names (no others may be introduced without adding them here):
`"crit"`, `"dh"`, `"variance"`, `"repertoire"`, `"hawks_eye"`, `"tick_offset"`.

`sim/tables.py`:

```python
class SimDataError(ValueError):
    """Raised when a data file is missing, malformed, or inconsistent with the Lua."""


@dataclass(frozen=True)
class Grant:
    status: str
    chance: float = 1.0
    duration_s: float | None = None   # None -> the status's own duration


@dataclass(frozen=True)
class ActionData:
    key: str
    id: int
    name: str
    kind: str                # "gcd" | "ogcd" | "song" | "buff" | "item"
    potency: int
    recast_s: float
    cooldown_s: float
    max_charges: int
    self_target: bool
    aoe: bool
    falloff: float
    grants: tuple[Grant, ...]
    requires: tuple[str, ...]
    status_gained_id: int
    notes: str

    @property
    def is_gcd(self) -> bool: ...


@dataclass(frozen=True)
class StatusData:
    key: str
    id: int
    name: str
    duration_s: float
    on_target: bool
    dot_potency: int
    snapshots: bool
    max_stacks: int
    damage_mult: float = 1.0
    crit_add: float = 0.0
    dh_add: float = 0.0


class Tables:
    """All game data, loaded once and shared read-only between fights."""

    actions: Mapping[str, ActionData]
    statuses: Mapping[str, StatusData]
    job: Mapping[str, Any]
    stats: Mapping[str, Any]

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Tables":
        """Load and validate the four JSON files (default: `sim/data`).

        Raises SimDataError on: a missing file, an unknown key in a record, a `grants`
        entry naming an unknown status, a `requires` entry naming an unknown status, a
        duplicate action id, or a negative duration/potency.
        """

    def action(self, key: str) -> ActionData:
        """Look up by CielBard ability key. Raises KeyError with the key in the message."""

    def by_id(self, action_id: int) -> ActionData | None:
        """Look up by FFXIV action id; None when the id is unknown (e.g. an item)."""

    def status(self, key: str) -> StatusData: ...

    def status_by_id(self, status_id: int) -> StatusData | None: ...

    def verify_against_lua(self, repo_root: Path) -> list[str]:
        """Return human-readable discrepancies between actions.json/statuses.json and
        `CielBard/CielBard_Data.lua`. Empty list means the tables match the shipped ids.

        Implementation: regex `(\\w+)\\s*=\\s*(\\d+)` inside the `CielBardData.Actions`
        and `CielBardData.Statuses` blocks. Do not import the Lua runtime here — this
        must work without lupa.
        """
```

`sim/damage.py`:

```python
@dataclass(frozen=True)
class StatProfile:
    """Stat-side inputs. Everything here is loaded from stats.json and overridable."""
    crit_rate: float
    crit_mult: float
    dh_rate: float
    dh_mult: float
    potency_to_damage: float
    damage_variance: float
    crit_dh_independent: bool = True

    @classmethod
    def from_tables(cls, tables: Tables, **overrides: float) -> "StatProfile": ...


@dataclass(frozen=True)
class BuffSnapshot:
    """Multipliers frozen at cast time (or DoT application time).

    `damage_mult` is the product of every multiplicative buff (Raging Strikes, Mage's
    Ballad, Radiant Finale, Medicated). `crit_add` / `dh_add` are additive rate bonuses
    (Wanderer's Minuet, Army's Paeon, Battle Voice).
    """
    damage_mult: float = 1.0
    crit_add: float = 0.0
    dh_add: float = 0.0

    def combined(self, other: "BuffSnapshot") -> "BuffSnapshot": ...


@dataclass(frozen=True)
class DamageResult:
    amount: float
    potency: int
    crit: bool
    direct_hit: bool
    multiplier: float


class DamageModel:
    """Potency -> damage, with crit/direct-hit rolls drawn from named RNG streams."""

    def __init__(self, profile: StatProfile, rng: SeededRNG) -> None: ...

    def roll(self, potency: int, snap: BuffSnapshot) -> DamageResult:
        """One damage instance.

        amount = potency * potency_to_damage * snap.damage_mult
                 * (crit_mult if crit else 1) * (dh_mult if dh else 1) * variance

        crit is `stream("crit").random() < clamp(crit_rate + snap.crit_add, 0, 1)`,
        dh likewise from `stream("dh")`; the two rolls are independent when
        `crit_dh_independent`. variance is
        `1 + stream("variance").uniform(-damage_variance, damage_variance)`, and is
        skipped entirely (no draw) when `damage_variance == 0.0` so the expected-value
        mode does not consume the stream.
        """

    def expected(self, potency: int, snap: BuffSnapshot) -> float:
        """Closed-form expectation of `roll`, consuming no randomness.

        Used by sweeps that want low variance and by `test_damage` to check that the
        mean of 200_000 rolls is within 1 % of the expectation.
        """
```

### 4.7 Notes the tables must carry

1. `HeavyShot`, `Windbite`, `VenomousBite`, `QuickNock` exist only because the engine
   falls back to them. At level 100 they must be **unavailable** (the core marks them
   `usable=False`), and any fight in which one is cast is a bug — the integration test
   asserts zero casts of them.
2. **Bloodletter vs Heartbreak Shot.** The brief lists Bloodletter at 130 potency. At level
   100 Bloodletter is trait-upgraded to Heartbreak Shot (180) and cannot be cast; the
   engine treats Bloodletter as a fallback (`E.UpdateCharges`, `chargeActions`). The tables
   carry both, `Bloodletter` is marked unavailable at level 100, and this is recorded in
   `calibration.md` §7.4 as a brief/game discrepancy rather than resolved silently.
3. `Ladonsbite` 140/target and `Shadowbite` 200/target are **verified from the repo**
   (`CielBard/CielBard_Data.lua` AoE comment block and `HANDOFF.md` "AoE" section) and
   agree with Burst Shot 220 / Refulgent 280 / Rain of Death 100 / Heartbreak 180 from the
   brief. No conflict.

### 4.8 Tests — `tests/test_tables.py`, `tests/test_damage.py`

`test_tables.py`
1. `test_load_default_tables` — `Tables.load()` succeeds and has all keys listed in §4.1/§4.2.
2. `test_ids_match_shipped_lua` — `verify_against_lua(repo_root)` returns `[]`.
3. `test_unknown_status_in_grants_raises` — patched temp data dir, expects `SimDataError`.
4. `test_duplicate_action_id_raises`.
5. `test_missing_file_raises_simdataerror`.
6. `test_apex_potency_curve` — 20 -> 140, 60 -> 420, 80 -> 560, 100 -> 700 (helper lives in
   `tables.py` as `apex_potency(gauge: float, job: Mapping) -> int`).
7. `test_gcd_haste_rounding` — helper `gcd_recast(base, haste_pct, rounding_ms)`:
   `(2.5, 0) -> 2.50`, `(2.5, 4) -> 2.40`, `(2.5, 16) -> 2.10`.
8. `test_radiant_encore_and_coda_tables_indexable_by_coda_count`.

`test_damage.py`
1. `test_roll_is_deterministic_for_seed` — same seed, same 100-roll sequence.
2. `test_crit_rate_observed_matches_profile` — 100 000 rolls, crit fraction within 0.5 pp.
3. `test_buff_snapshot_multiplies` — `damage_mult=1.15` yields exactly 1.15x with
   `damage_variance=0` and forced crit/DH rates of 0.
4. `test_expected_matches_mean_of_rolls` — within 1 % over 200 000 rolls.
5. `test_zero_variance_consumes_no_variance_stream` — the variance stream's state is
   unchanged after 10 rolls.
6. `test_independent_streams` — drawing 1000 crit rolls does not change the `dh` stream.
7. `test_crit_add_clamped_to_unit_interval`.

---

## 5. Module B — fake MMOMinion client

**Owns:** `sim/client.py`, `tests/test_client.py`. **Imports:** `lupa` only (no `sim.*`).

The client is a *mirror*, not a simulator. It holds no game rules. It exposes exactly the
globals and fields the engine touches, reflects whatever the core writes into it, and
captures what the engine asks for.

### 5.1 Responsibilities

1. Create `LuaRuntime(unpack_returned_tuples=True)`; load `CielBard_Data.lua` then
   `CielBard_Rotation.lua` from a given repo root.
2. Build a Lua config table = deep copy of `CielBardData.Defaults` + caller overrides, and
   call `CielBardEngine.Init(config)`.
3. Publish the globals of §3.1 backed by Python objects (scalars) and Lua tables
   (containers, per §3.2).
4. Expose setters the core calls each pulse; they must be cheap (write changed scalars into
   pre-allocated Lua tables, never rebuild a table unless its cardinality changed).
5. `step()` -> call `CielBardEngine.Step(False)`.
6. Capture `Cast` calls into a request list; capture client-side refusals.

### 5.2 Public API — literal definitions

```python
class LuaBridgeError(RuntimeError):
    """Raised when the Lua files cannot be loaded or the engine raises out of Step."""


@dataclass(frozen=True)
class ActionSpec:
    """The static shape of one action as the client must present it."""
    action_id: int
    name: str
    is_gcd: bool
    self_target: bool
    recast_s: float
    max_charges: int = 1
    status_gained_id: int = 0


@dataclass
class ActionView:
    """Per-pulse mutable action state written by the core, read by the engine.

    `ready` is the core's verdict for `IsReady` *ignoring* targeting; the client applies
    the self-target rule of §3.5 on top of it.
    """
    cd: float = 0.0
    cdmax: float = 0.0
    isoncd: bool = False
    usable: bool = True
    ready: bool = False
    highlighted: bool = False


@dataclass(frozen=True)
class BuffView:
    id: int
    ownerid: int
    duration: float


@dataclass
class EntityView:
    id: int
    name: str
    alive: bool = True
    targetable: bool = True
    incombat: bool = True
    los: bool = True
    distance2d: float = 3.0
    hp_current: float = 1.0e9
    hp_max: float = 1.0e9
    hp_percent: float = 100.0
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    buffs: tuple[BuffView, ...] = ()


@dataclass
class PlayerView:
    id: int = 100
    job: int = 23
    alive: bool = True
    incombat: bool = True
    hp_percent: float = 100.0
    gauge: tuple[float, float, float, float, float] = (0, 0, 0, 0, 0)
    buffs: tuple[BuffView, ...] = ()
    locked: bool = False       # -> MIsLocked()
    casting: bool = False      # -> MIsCasting() and ActionList:IsCasting()
    loading: bool = False      # -> MIsLoading()


@dataclass(frozen=True)
class PotionView:
    """One inventory potion, addressed by MMOMinion's hqid."""
    hqid: int
    action_id: int
    ready: bool
    cd: float = 0.0
    cdmax: float = 270.0


@dataclass(frozen=True)
class CastRequest:
    """One `action:Cast(target)` or `item:Cast(player)` the engine issued."""
    action_id: int
    target_id: int
    is_item: bool
    request_ms: int
    hqid: int = 0            # item requests only


@dataclass(frozen=True)
class ClientRejection:
    """A Cast the client refused (returned false to Lua)."""
    action_id: int
    target_id: int
    reason: str              # "not-ready" | "self-target-mismatch" | "unknown-action"
    request_ms: int


class FakeClient:
    """A minimal, faithful stand-in for the MMOMinion Lua API.

    Owns the LuaRuntime and the Lua-side mirror of game state. Holds no game rules:
    every value it reports is one the core wrote.
    """

    def __init__(
        self,
        repo_root: Path,
        specs: Sequence[ActionSpec],
        *,
        player_id: int = 100,
        target_id: int = 200,
        debug_sink: Callable[[str], None] | None = None,
    ) -> None:
        """Create the runtime, load the shipped Lua, publish globals.

        Raises LuaBridgeError if either Lua file is missing or fails to load.
        """

    # --- lifecycle -------------------------------------------------------
    def init_engine(self, config_overrides: Mapping[str, Any] | None = None) -> None:
        """Deep-copy CielBardData.Defaults, apply overrides, call CielBardEngine.Init.

        Override keys use dotted paths for nested tables, matching the shipped GUI's
        flat persistence format: `"abilities.ApexArrow"`, `"aoeTargets.Ladonsbite"`.
        A key that does not exist in Defaults raises KeyError (typo protection); pass
        `"_allow_new": True` in the mapping to bypass that for forward compatibility.
        """

    def warnings(self) -> list[str]:
        """CielBardEngine.GetConfigurationWarnings() as a Python list."""

    def close(self) -> None:
        """Drop the Lua runtime. Idempotent."""

    # --- per-pulse writes (called by the core) ---------------------------
    def set_time(self, now_ms: int) -> None:
        """Set the value `Now()` returns. Must be monotonic non-decreasing."""

    def set_player(self, view: PlayerView) -> None: ...
    def set_target(self, view: EntityView | None) -> None:
        """None makes Player:GetTarget() return nil."""
    def set_entities(self, views: Sequence[EntityView]) -> None:
        """The EntityList(filter) result. Two clauses of the filter string are
        honoured: `incombat` drops entities with `incombat=False`, and
        `maxdistance=N` drops entities whose `distance2d` exceeds N. The rest
        (`alive`, `attackable`, ...) is the caller's responsibility."""
    def set_action(self, action_id: int, view: ActionView) -> None: ...
    def set_actions(self, views: Mapping[int, ActionView]) -> None:
        """Bulk form; preferred on the hot path."""
    def set_last_cast(self, action_id: int, time_since_ms: int) -> None: ...
    def set_potions(self, potions: Sequence[PotionView]) -> None:
        """Publishes GetItem(hqid, bags). An empty sequence removes every potion but
        keeps GetItem defined (the engine checks `type(GetItem) == "function"`)."""

    # --- pulse -----------------------------------------------------------
    def step(self) -> bool:
        """Call CielBardEngine.Step(false). Returns the engine's boolean.

        Any Lua error is wrapped in LuaBridgeError, with the Lua traceback in the
        message and the pulse's `now_ms` appended.
        """

    def take_requests(self) -> list[CastRequest]:
        """Drain and return the requests issued since the last drain."""

    def take_rejections(self) -> list[ClientRejection]: ...

    # --- diagnostics -----------------------------------------------------
    def engine_state(self) -> dict[str, Any]:
        """Scalar fields of CielBardEngine.state, as plain Python.

        Includes at least: lastDecision, lastActionName, weavesSinceGCD, currentSong,
        songRemaining, charges, chargeRemaining, ttk, ttkBand, gcdRemaining,
        gcdsSinceRaging, codaCount (computed via CielBardEngine.CodaCount()).
        """

    @property
    def errors(self) -> list[str]:
        """Exceptions raised inside client callbacks and swallowed by Lua's pcall."""
```

### 5.3 Lua surface the client must publish

```
Now()                        -> integer ms, from set_time
MIsLoading() MIsLocked() MIsCasting()  -> PlayerView.loading/locked/casting
EntityList(filter)           -> Lua table keyed by entity id (pairs-iterable, may be empty)
Player                       -> Python object: id, job, alive, incombat,
                                hp (obj with .current/.max/.percent),
                                gauge (LUA TABLE 1..5), buffs (LUA TABLE of LUA TABLES),
                                castinginfo (obj: lastcastid, timesincecast),
                                GetTarget() -> entity object or nil
ActionList                   -> Python object with Get(type, id) and IsCasting()
GetItem(hqid, bags)          -> (item, action) or (nil, nil)
d(msg)                       -> debug_sink or no-op
```

Action objects returned by `ActionList:Get(1, id)` must carry:
`id, name, cd, cdmax, isoncd, usable, recasttime, highlighted, statusgainedid,
IsReady(targetID), Cast(targetID)`.

`ActionList:Get` for an **unknown** id must still return an object (the engine asks for
ids it may not have specs for, e.g. `Bloodletter` when disabled): return a permanently
unusable stub with `usable=False, ready=False, cd=0, cdmax=0, isoncd=False,
recasttime=0`, and record the id in `FakeClient.unknown_action_ids` (a `set[int]`, exposed
for tests). The stub is created once and cached — `Get` is called dozens of times per
pulse and must be O(1) with no allocation.

`item` objects (potions) carry `hqid, IsReady(targetID), Cast(targetID), GetAction()` and
the action object carries `id, isoncd, cd, cdmax`.

### 5.4 `IsReady` and `Cast` semantics

```python
def IsReady(self, target_id):
    if not self.view.usable:            return False
    if self.spec.self_target and target_id != client.player_id:  return False
    return bool(self.view.ready)

def Cast(self, target_id):
    if not self.IsReady(target_id):
        client._reject(self.spec.action_id, target_id, "not-ready")   # or the precise reason
        return False
    client._requests.append(CastRequest(self.spec.action_id, target_id, False, client._now_ms))
    return True
```

`Cast` **must not** mutate cooldowns, the GCD, or `castinginfo`. The core owns all of that
and writes it back on the next pulse. This keeps the client rule-free.

### 5.5 Potions

The engine calls `GetItem(hqid, {0,1,2,3})` and expects `(item, itemAction)`. It tries
`potion.id + 1000000` (HQ) before `potion.id`, newest grade first, over
`CielBardData.Potions`. `PotionView.hqid` is the full addressed id (already including the
HQ offset when appropriate). The client returns `(None, None)` for an unlisted hqid.

`item:Cast(playerId)` records `CastRequest(action_id=view.action_id, target_id=player_id,
is_item=True, hqid=view.hqid)`.

### 5.6 `engine_state`

Read `CielBardEngine.state` field by field (never bulk-convert: it contains Lua tables and
possibly Python objects). Convert numbers to float/int, strings to `str`, `nil` to `None`.

### 5.7 Performance requirements

- `ActionList:Get` returns a cached per-id object. No dict rebuild per call.
- `set_actions` writes only fields that changed (keep the previous `ActionView` per id and
  compare). Writing an attribute on a Python object exposed to Lua is a plain `setattr`.
- `Player.gauge` and every buff table are **allocated once** and mutated in place. When the
  buff count changes, grow the Lua table and set the surplus slots to `nil`.
- No `lua.eval` / `lua.execute` on the hot path. Resolve `CielBardEngine.Step` to a Python
  callable once in `init_engine` and store it.
- Target: `step()` including all setters costs **< 120 µs** for a typical pulse. Module B's
  test suite includes a timing smoke test (asserts < 2 ms so it is not flaky on a loaded
  machine, and prints the measured median).

### 5.8 Error handling

- Missing Lua file / syntax error -> `LuaBridgeError` from `__init__`.
- Lua error escaping `Step` -> `LuaBridgeError` from `step()`.
- Exception inside an `IsReady`/`Cast`/`GetTarget` callback: append
  `f"{type(e).__name__}: {e} @ {now_ms}ms in {where}"` to `self._errors`, then re-raise so
  Lua's `pcall` sees it (the engine then treats the action as not ready). `Simulation`
  raises `SimulationError` at the end of the fight if `client.errors` is non-empty.
- `set_time` going backwards -> `ValueError`.
- `init_engine` with an unknown dotted key -> `KeyError`.

### 5.9 Tests — `tests/test_client.py`

1. `test_loads_shipped_lua_and_inits` — engine initialised, `CielBardData.Version ==
   "0.5.0"`, no warnings beyond the expected set.
2. `test_config_overrides_flat_and_nested` — `{"enabled": True, "abilities.ApexArrow":
   False, "aoeTargets.Ladonsbite": 3}` land in the Lua config; unknown key raises.
3. `test_containers_are_lua_tables` — inside Lua, `type(Player.gauge) == "table"`,
   `type(Player.buffs) == "table"`, `type(EntityList("x")) == "table"`, and
   `next(Player.buffs) ~= nil` after `set_player` with one buff.
4. `test_gauge_indices_visible_to_engine` — set gauge `(1, 2, 30, 85, 0)`;
   `CielBardEngine.GetSoulVoice() == 85` and `GetRepertoire() == 2`.
5. `test_charge_reading_matches_live_layout` — Heartbreak `recasttime=15, cdmax=45,
   cd=30.5` -> `E.UpdateCharges()` gives `charges == 2`, `chargeRemaining ≈ 14.5`; then
   `cd=7.7 -> 0 charges`; then `cdmax=0, cd=0, isoncd=False -> 3 charges`. (Mirrors
   `tests/run_mock_tests.py:607`.)
6. `test_self_target_actions_reject_enemy_id` — `IsReady(target_id)` False and
   `IsReady(player_id)` True for Raging Strikes / each song.
7. `test_cast_records_request_and_returns_true`, and
   `test_cast_when_not_ready_records_rejection_and_returns_false`.
8. `test_song_status_detection` — action 3559 with `statusgainedid=865` plus a player buff
   `{id: 865, ownerid: 100, duration: 40}` makes `E.GetSong()` return `("WM", 40)`.
9. `test_dot_ownership_respected` — a target buff with `ownerid != player_id` yields
   `E.GetDotState(target) == (0, 0)`.
10. `test_last_cast_observation_counts_weaves` — two Empyreal casts in a row with
    `timesincecast` reset are both observed (`weavesSinceGCD == 2`).
11. `test_unknown_action_returns_unusable_stub` and is recorded.
12. `test_getitem_hq_preference` — HQ hqid resolves, NQ also resolves, unknown returns nil.
13. `test_step_wraps_lua_error` — inject a callback that raises; `LuaBridgeError`.
14. `test_set_time_monotonic_enforced`.
15. `test_pulse_cost_smoke` — 2000 pulses, median < 2 ms, prints the median.

Module B's tests construct their own `ActionSpec` list from
`CielBard/CielBard_Data.lua`-derived literals; they must not import `sim.tables`.

---

## 6. Module C — discrete-event game core

**Owns:** `sim/core.py`, `sim/events.py`, `sim/runconfig.py`, `tests/test_core.py`.
**Imports:** `sim.tables`, `sim.damage`, `sim.rng` (A) and `sim.client` (B).

### 6.1 Clock

Integer microseconds. `Simulation._us: int`. `now_ms() -> self._us // 1000`. Pulses are
scheduled on exact multiples of `pulse_us = pulseMs * 1000`, so `Now()` returns
0, 30, 60, ... with no float drift. All public times are seconds (`float`), derived as
`us / 1_000_000`.

### 6.2 Event model — `sim/events.py`

```python
@dataclass(order=True)
class Event:
    """A scheduled state change. Ordering is (time, priority, seq) — never by payload."""
    t_us: int
    priority: int
    seq: int
    kind: str = field(compare=False)
    payload: dict = field(compare=False, default_factory=dict)


class EventQueue:
    """A deterministic min-heap. Ties break by `priority` then insertion order."""
    def push(self, t_us: int, kind: str, priority: int = 100, **payload) -> None: ...
    def pop_due(self, t_us: int) -> Iterator[Event]:
        """Yield every event with `e.t_us <= t_us`, in order, including events pushed
        by handlers during iteration."""
    def peek_us(self) -> int | None: ...
    def __len__(self) -> int: ...
```

Event kinds and priorities (lower runs first at equal time):

| kind | priority | effect |
|---|---:|---|
| `"lock_end"` | 10 | animation lock expires |
| `"gcd_ready"` | 10 | GCD recast completes |
| `"cooldown_ready"` | 10 | an action's cooldown or one charge completes |
| `"status_expire"` | 20 | a buff/debuff falls off |
| `"server_tick"` | 30 | 3 s tick: DoT damage, song repertoire proc, song timer |
| `"action_execute"` | 40 | a requested action lands: damage, statuses, resources |
| `"downtime_start"` / `"downtime_end"` | 50 | target becomes un/targetable |
| `"fight_end"` | 90 | stop |

`"server_tick"` before `"action_execute"` at the same microsecond means a DoT applied on
this exact tick does not tick immediately — matching the game.

### 6.3 `sim/runconfig.py`

```python
class SimConfigError(ValueError):
    """Raised for an impossible or contradictory fight configuration."""


@dataclass(frozen=True)
class DowntimeWindow:
    start_s: float
    end_s: float
    def __post_init__(self) -> None:
        """Raises SimConfigError when end <= start or start < 0."""


@dataclass(frozen=True)
class FightConfig:
    """Everything needed to reproduce one fight exactly."""
    seconds: float = 510.0
    seed: int = 1
    ping_ms: float = 0.0
    pulse_ms: int = 30                    # also written into the engine config
    engine_config: Mapping[str, Any] = field(default_factory=dict)
    downtime: tuple[DowntimeWindow, ...] = ()
    enemies: int = 1                      # striking dummies; 1 is the engine's target
    enemy_spread_yalms: float = 2.0       # ring radius the clones stand on around it
    stat_overrides: Mapping[str, float] = field(default_factory=dict)
    job_overrides: Mapping[str, Any] = field(default_factory=dict)
    use_potion: bool = False
    deterministic_damage: bool = False    # damage_variance -> 0
    tick_offset_s: float | None = None    # None -> drawn from the "tick_offset" stream
    fast_skip_locked: bool = True
    trace: bool = False
    repo_root: Path | None = None         # default: parents of this file

    def validate(self) -> None:
        """Raises SimConfigError for: seconds <= 0, pulse_ms <= 0 or > 1000,
        ping_ms < 0, overlapping downtime windows, downtime beyond `seconds`,
        enemies < 1, enemy_spread_yalms < 0."""

    def engine_overrides(self) -> dict[str, Any]:
        """The full override mapping handed to FakeClient.init_engine: the caller's
        `engine_config` plus the forced values
        {"enabled": True, "debug": False, "pulseMs": self.pulse_ms,
         "usePotion": self.use_potion, "requireCombat": True, "requireLOS": False}.
        Caller keys win over the forced ones EXCEPT `enabled` and `debug`.
        """
```

### 6.4 Game state the core owns

Not a public API, but these must exist and be unit-testable:

- `gcd_ready_us`, `anim_lock_until_us`, `current_gcd_s`
- per-action `cooldown`: for charged actions a single `charge_progress_s` float shared by
  Heartbreak / Bloodletter / Rain of Death; for others `ready_at_us`
- `statuses`: player statuses and per-entity statuses, each
  `StatusInstance(key, expires_us, stacks, snapshot: BuffSnapshot | None, next_tick_us)`
- `soul_voice`, `repertoire` (song-specific meaning, §4.5), `paeon_stacks`, `codas: set[str]`
- `song: str | None`, `song_ends_us`, `coda_count_for_finale`
- `target: EntityView`, `entities`
- counters: `casts`, `damage_events`, `rejections`, `wasted_procs`

### 6.5 The pulse / event loop — the authoritative contract

```
run():
  validate config; build tables, rng, damage model, client; init engine
  schedule: first "server_tick" at tick_offset, each downtime window, "fight_end"
  pulse_us = pulse_ms * 1000
  t = 0
  while t <= end_us:
      # 1. everything scheduled up to and including t has already happened
      for ev in queue.pop_due(t): handle(ev)          # handlers may push more events
      # 2. decide whether to pulse the engine
      if not fight_over:
          locked = anim_lock_until_us > t
          if not (fast_skip_locked and locked):
              sync_client(t)                           # write every mirror field
              client.step()
              for req in client.take_requests(): resolve(req, t)
              record client.take_rejections()
      t += pulse_us
  for ev in queue.pop_due(end_us): handle(ev)          # drain the tail
  return build_result()
```

Rules that make this unambiguous:

- **Time is advanced only by the `t += pulse_us` line.** Handlers never advance it.
- An event scheduled exactly at a pulse boundary is handled **before** the pulse, so the
  engine always sees post-event state.
- Events strictly between two pulses are handled at the *next* pulse boundary but their
  effects are timestamped with `ev.t_us`, so damage and uptime accounting are exact even
  though decisions are quantised to the pulse grid. This is the same quantisation the real
  client has.
- **At most one request per pulse is honoured.** The engine returns after its first
  successful `Cast`, so `take_requests()` normally has 0 or 1 entry. If it has more, honour
  the first and record `CoreRejection(reason="multiple-requests-per-pulse")` for the rest.
- `fast_skip_locked=True` is provably equivalent to `False`: while `MIsLocked()` is true the
  engine's `Step` returns before any state mutation other than `s.lastPulse`, which is only
  compared against `c.pulseMs` and is therefore behaviour-neutral. `test_core` asserts the
  equivalence on a 60 s fight (identical cast log).

### 6.6 `sync_client(t)` — exactly what the core writes each pulse

1. `client.set_time(t // 1000)`.
2. `PlayerView`: `locked = anim_lock_until_us > t`, `casting = False`,
   `loading = False`, `incombat = True`, `hp_percent = 100`,
   `gauge = (song_index, repertoire, int(song_remaining), soul_voice, coda_mask)`,
   `buffs = tuple(BuffView(status_id, player_id, remaining) ...)` for every **player**
   status whose status id is non-zero.
3. Target: during a downtime window, `set_target(None)`. Otherwise an `EntityView` with
   `hp_percent` from the **kill-time model**:
   `hp_percent = max(0.0, 100.0 * (1.0 - elapsed_s / seconds))` — a linear dummy whose
   death coincides with `seconds`. This is what feeds the engine's TTK estimator, which is
   what selects the terminal/ideal-finish bands the merged report cares about. `hp_current
   = hp_max * hp_percent / 100`. Buffs = our DoTs and any other target status.
4. `set_entities([...])` — the primary target at the origin plus `enemies - 1` clones
   with distinct ids (300, 301, ...), evenly spaced on a ring of `enemy_spread_yalms`
   around it. The engine never reads `enemies`: `E.CountEnemiesNear` counts the entities
   whose `pos` is within 5 yalms of its target's out of
   `EntityList("alive,attackable,maxdistance=30")`, and `E.FindMultiDotTarget` scans
   `EntityList("alive,attackable,incombat,maxdistance=25")`, so the ring radius is what
   decides whether the pack is an AoE group at all. `FakeClient` enforces the
   `maxdistance` clause of both filters against each entity's `distance2d`
   (`_PRIMARY_DISTANCE_YALMS + enemy_spread_yalms` for a clone), so a spread wide enough
   to push the clones past 25/30 yalms removes them from the lists outright, exactly as
   it would live.
5. `set_actions(...)` for **every** action in the spec list, computed by §6.7.
6. `set_last_cast(last_cast_id, t_us - last_cast_us in ms)`.
7. `set_potions(...)` when `use_potion`.

To hit the performance budget, steps 2-6 mutate cached view objects in place; only fields
that changed are pushed into Lua (Module B's `set_actions` already diffs).

### 6.7 Action availability (`ActionView`) — the rules table

For each action key, per pulse:

| field | rule |
|---|---|
| `usable` | `False` for level-synced fallbacks (`HeavyShot`, `Windbite`, `VenomousBite`, `QuickNock`, `Bloodletter`); `False` for an action whose `requires` status is absent; otherwise `True` |
| `ready` | `usable and cooldown_remaining <= 0 and resource_ok` — **not** gated on the GCD: `IsReady` does not reflect the recast on live clients (`CielBard/CielBard_Rotation.lua:1006-1007`). `cd`/`cdmax`/`isoncd` still carry it, which is what `E.GCDRemaining` reads. |
| `cd`,`cdmax`,`isoncd` | per §3.4; GCD actions report the **GCD** timer, charged actions the charge layout |
| `highlighted` | `True` for `RefulgentArrow` while `HawksEye` is up, for `Shadowbite` likewise, for `BlastArrow`/`ResonantArrow`/`RadiantEncore` while their ready-status is up; else `False` |
| `recasttime` | `ActionData.recast_s` (15 for the charge pool); for GCDs the **current, hasted** GCD recast, republished by `_sync_client` on every haste change (§3.4) |
| `statusgainedid` | songs only |

`resource_ok` details:
- `ApexArrow`: `soul_voice >= 20`
- `PitchPerfect`: `song == "WM" and repertoire >= 1`
- `BlastArrow` / `ResonantArrow` / `RadiantEncore` / `RefulgentArrow` / `Shadowbite`:
  their `requires` status present
- `IronJaws`: always ready off the GCD (the engine gates it on DoT state)
- songs: their own 120 s cooldown; the three songs have **independent** cooldowns

**Charge pool.** Heartbreak Shot, Bloodletter and Rain of Death share one pool:
`charge_progress_s in [0, 45]`, `charges = floor(progress / 15)`. Spending: `progress -=
15`. Regeneration: `progress` advances with time, capped at 45. Mage's Ballad repertoire:
`progress = min(45, progress + 7.5)`. All three actions report the same `cd`/`cdmax` derived
from `progress`: `cd = progress`, `cdmax = 45`, unless `progress >= 45` in which case
`cd = cdmax = 0, isoncd = False`.

### 6.8 Resolving a request

```
resolve(req, t):
  if req.is_item: spec = potion
  else: spec = tables.by_id(req.action_id)   # None -> CoreRejection("unknown-action")
  if anim_lock_until_us > t:                 -> CoreRejection("locked")
  t_eff = t
  if spec.is_gcd and gcd_ready_us > t:       # the client action queue, section 3.4
    if gcd_ready_us - t > queue_window_us:   -> CoreRejection("gcd-not-ready")
    t_eff = gcd_ready_us                     # queued: it fires when the recast ends
  if not available(spec, t_eff):             -> CoreRejection("unavailable")
  # accept, and compute everything from t_eff rather than t
  anim_lock_until_us = t_eff + lock_us(spec) ;  push "lock_end"
  if spec.is_gcd: gcd_ready_us = t_eff + current_gcd_us ; push "gcd_ready"
  start cooldown / spend a charge                        (at t_eff)
  last_cast_id = req.action_id ; last_cast_us = t_eff
  push "action_execute" at t_eff + damage_delay_us  (damage_delay_us = 0 by default)
  append CastRecord(t_s = t_eff)
```

`queue_window_us = job.gcd_queue_window_s * 1e6`. A queued weaponskill leaves
`last_cast_us` in the future until it fires, so `set_last_cast` clamps the published
`timesincecast` at 0 rather than reporting a negative age.

`lock_us(spec) = (anim_lock_gcd_s if spec.is_gcd else anim_lock_ogcd_s) + ping_ms/1000`.
Items use the oGCD lock.

`"action_execute"` handler:
- compute `BuffSnapshot` from current player statuses (§6.10)
- direct damage: `damage_model.roll(potency, snap)`; `potency` from the tables, except
  Apex (gauge curve), Pitch Perfect (stack table) and Radiant Encore (coda table)
- apply `grants` (roll chance from the `"hawks_eye"` stream where `chance < 1`)
- consume `requires` statuses
- resource changes: Apex zeroes Soul Voice and grants `BlastArrowReady` at >= 80;
  Pitch Perfect zeroes WM repertoire; Empyreal Arrow fires a guaranteed repertoire proc;
  a song sets `song`, `song_ends_us`, adds the coda, and applies the song status;
  Radiant Finale snapshots `len(codas)`, clears them, applies its buff at the matching
  multiplier and grants `RadiantEncoreReady` carrying that coda count
- DoTs: apply/refresh the status on the **request's target entity** with the snapshot taken
  now; Iron Jaws refreshes both to full duration with the *current* snapshot

### 6.9 Results — literal definitions (Module D codes against these)

```python
class SimulationError(RuntimeError):
    """Raised when the fight cannot be completed (Lua error, client callback error)."""


@dataclass(frozen=True)
class CastRecord:
    t_s: float
    action_id: int
    key: str                 # "" for unmapped ids
    name: str
    is_gcd: bool
    target_id: int
    potency: int
    decision: str            # CielBardEngine.state.lastDecision at the pulse


@dataclass(frozen=True)
class DamageRecord:
    t_s: float
    action_id: int
    key: str
    source: str              # "direct" | "dot" | "auto"
    potency: int
    amount: float
    crit: bool
    direct_hit: bool
    multiplier: float


@dataclass(frozen=True)
class CoreRejection:
    t_s: float
    action_id: int
    reason: str              # locked | gcd-not-ready | unavailable | unknown-action |
                             # multiple-requests-per-pulse
    decision: str


@dataclass(frozen=True)
class FightResult:
    config: FightConfig
    duration_s: float
    total_damage: float
    dps: float
    total_potency: int
    potency_per_second: float
    gcd_count: int
    ogcd_count: int
    gcd_uptime: float             # fraction of `duration_s` the GCD was rolling
    clipped_s: float              # sum of (gcd gap - recast) over all GCD pairs
    action_counts: dict[str, int] # by ability key, sorted by key
    damage_by_action: dict[str, float]
    dot_uptime: dict[str, float]  # key -> fraction of the fight the DoT was on the target
    song_seconds: dict[str, float]
    song_casts: dict[str, int]
    wasted: dict[str, int]        # "repertoire_overcap", "soul_voice_overcap",
                                  # "hawks_eye_overwritten", "charge_overcap"
    casts: tuple[CastRecord, ...]
    damage: tuple[DamageRecord, ...]
    rejections: tuple[CoreRejection, ...]
    client_rejections: tuple[ClientRejection, ...]
    warnings: tuple[str, ...]     # engine configuration warnings
    engine_state: dict[str, Any]  # final CielBardEngine.state snapshot

    def to_dict(self, *, include_events: bool = False) -> dict:
        """JSON-ready. `include_events=False` (default) drops `casts` and `damage` so a
        batch of 1000 fights stays small. Floats are rounded to 6 decimals so the JSON
        is byte-stable."""


class Simulation:
    """One fight: owns the clock, the event queue, the game state and the Lua client."""

    def __init__(self, config: FightConfig, tables: Tables | None = None) -> None:
        """`tables` may be shared across fights (it is read-only)."""

    def run(self) -> FightResult:
        """Run to completion and return the result. Always closes the client."""


def run_fight(config: FightConfig, tables: Tables | None = None) -> FightResult:
    """Convenience wrapper around `Simulation(config).run()`."""
```

### 6.10 Snapshotting

`BuffSnapshot` at cast time = product/sum over active **player** statuses:
- `damage_mult` *= `RagingStrikes` 1.15, `MagesBallad` 1.01, `RadiantFinale`
  `coda_damage_mult[n]`, `Medicated` `potion_damage_mult`
- `crit_add` += `WanderersMinuet` 0.02
- `dh_add` += `ArmysPaeon` 0.03, `BattleVoice` 0.20

DoTs store the snapshot taken when applied or refreshed and use it for every tick until the
next refresh. Direct damage uses the live snapshot. The `"server_tick"` handler rolls each
DoT tick through `DamageModel.roll(dot_potency, dot.snapshot)`.

### 6.11 Errors

- `SimConfigError` from `FightConfig.validate()`.
- `SimulationError` when: `client.errors` is non-empty at the end; the engine issues more
  than `max_requests_per_pulse = 4` in one pulse (runaway); the fight produces zero casts;
  or more than 5 % of pulses produced a `CoreRejection`.
- `LuaBridgeError` propagates unchanged (it is already precise).
- Never catch a bare `Exception` around `client.step()`.

### 6.12 Tests — `tests/test_core.py`

1. `test_clock_is_exact_ms` — 17 000 pulses at 30 ms end on `Now() == 510000`.
2. `test_events_ordered_deterministically` — equal-time events pop in priority then
   insertion order.
3. `test_gcd_recast_and_haste` — 0 stacks 2.50 s, 4 Paeon stacks 2.10 s; GCD count over
   60 s matches `floor(60 / recast)` +/- 1.
4. `test_animation_lock_blocks_requests` — a request while locked is rejected with
   `"locked"` and no `CastRecord` is created.
5. `test_ping_extends_lock` — `ping_ms=100` gives a 0.7 s lock; the achievable weave count
   per GCD drops as expected.
6. `test_charge_pool_semantics` — spend 3, verify `cd/cdmax` readings at each step; a
   Ballad proc advances progress by exactly 7.5 s and never past 45.
7. `test_dot_snapshot_frozen` — apply Stormbite under Raging Strikes, let Raging fall off,
   assert every tick still uses the 1.15 multiplier until Iron Jaws refreshes it.
8. `test_dot_ticks_every_three_seconds` — 45 s of Stormbite yields 15 ticks.
9. `test_repertoire_proc_rate` — with a fixed seed, proc count over 1000 ticks
   is within 2 pp of 80 %.
10. `test_soul_voice_caps_and_apex_scaling` — gauge never exceeds 100, Apex potency at the
    recorded gauge matches the curve.
11. `test_codas_and_radiant_finale` — three songs then Finale gives the 1.06 multiplier and
    a 1100-potency Radiant Encore; Finale clears the coda set.
12. `test_downtime_window_stops_casting` — no `CastRecord` inside a window; cooldowns still
    advance.
13. `test_fast_skip_locked_equivalence` — identical `casts` tuple with the flag on and off.
14. `test_determinism` — two runs, identical `to_dict(include_events=True)`.
15. `test_rejections_are_reported_not_swallowed`.
16. `test_result_totals_consistent` — `total_damage == sum(d.amount for d in damage)`,
    `dps == total_damage / duration_s`.
17. `test_no_level_sync_fallbacks_cast` — zero Heavy Shot / Quick Nock / Bloodletter.
18. `test_60s_fight_perf` — one 60 s fight in under 0.5 s (prints the measured time).

---

## 7. Module D — runner, batch, sweep, calibration

**Owns:** `sim/run.py`, `sim/batch.py`, `sim/sweep.py`, `sim/calibrate.py`,
`sim/report.py`, `tests/test_cli.py`. **Imports:** `sim.core`, `sim.tables`.

### 7.1 Fixed run contract

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m sim.run --seconds 510 --seed 1 --ping 0
```

must exit 0 and print exactly this shape to stdout (values vary, layout does not):

```
CielBard sim 1.0.0 | engine 0.5.0
fight    510.0s  seed=1  ping=0ms  pulse=30ms  gcd=2.50s  enemies=1
damage   17662830   dps 34633.0   potency 104215 (204.3/s)
gcds     205 (24.12/min)   ogcds 288   weaves/gcd 1.40
uptime   gcd 98.7%   clipped 0.42s   rejections 0
dots     Stormbite 99.1%   CausticBite 98.8%
songs    WM 4x 43.9s   MB 4x 42.4s   AP 3x 35.0s
waste    repertoire 2   soulvoice 0   charges 1   barrage 0
counts   ApexArrow 8  Barrage 4  BattleVoice 5  BurstShot 63  ...
```

Rules:
- Line 1 is `f"CielBard sim {__version__} | engine {ENGINE_VERSION}"`.
- Field labels are left-aligned in an 8-character column.
- `counts` lists every action with count >= 1, sorted by ability key, `key count` pairs
  separated by two spaces, wrapped at 100 columns with a 9-space continuation indent.
- No trailing whitespace; `\n` line endings.

Full flag set for `sim.run`:

| flag | default | meaning |
|---|---|---|
| `--seconds FLOAT` | 510.0 | fight length (also the dummy's linear death time) |
| `--seed INT` | 1 | RNG seed |
| `--ping FLOAT` | 0 | ms added to every animation lock |
| `--pulse INT` | 30 | pulse period in ms, written into the engine config |
| `--enemies INT` | 1 | striking dummies, including the engine's target |
| `--enemy-spread YALMS` | 2.0 | ring radius the extra dummies stand on; above 5 the engine stops counting them as one pack |
| `--downtime A:B` | none | repeatable, seconds |
| `--set KEY=VALUE` | none | repeatable engine config override, dotted keys allowed; values parse as int, float, bool (`true`/`false`) or string |
| `--stat KEY=VALUE` | none | repeatable `stats.json` override |
| `--potion` | off | enable `usePotion` |
| `--deterministic` | off | `damage_variance = 0` |
| `--json PATH` | none | write `FightResult.to_dict(include_events=True)` |
| `--trace` | off | print one line per cast: `t, key, decision` |
| `--quiet` | off | suppress the summary (use with `--json`) |
| `--strict` | off | exit 4 if any rejection or engine warning occurred |

Exit codes: `0` ok, `2` `SimConfigError` or bad CLI input, `3` `LuaBridgeError` /
`SimulationError`, `4` `--strict` violation. Errors go to stderr as
`sim.run: <message>` with no traceback unless `--trace`.

### 7.2 `sim/batch.py`

```python
@dataclass(frozen=True)
class BatchSummary:
    n: int
    seconds: float
    dps_mean: float
    dps_stdev: float
    dps_p05: float
    dps_p50: float
    dps_p95: float
    gcd_mean: float
    action_counts_mean: dict[str, float]
    dot_uptime_mean: dict[str, float]
    rejections_total: int
    def to_dict(self) -> dict: ...


def run_batch(
    base: FightConfig,
    *,
    seeds: Sequence[int],
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[BatchSummary, list[FightResult]]:
    """Run one fight per seed and aggregate.

    `workers=None` uses `min(os.cpu_count(), len(seeds))` processes via
    `concurrent.futures.ProcessPoolExecutor`; `workers=1` runs in-process (needed for
    coverage and for debugging). Results are re-sorted by seed before aggregation so the
    summary does not depend on completion order. Each worker builds its own `Tables` and
    `FakeClient` — a LuaRuntime cannot cross a process boundary.
    """
```

CLI: `python -m sim.batch --seconds 510 --seeds 1-200 [--workers N] [--json PATH]`.
`--seeds` accepts `1-200`, `1,5,9` or a mix. Prints the `BatchSummary` in the §7.1 style.

### 7.3 `sim/sweep.py`

```python
def sweep(
    base: FightConfig,
    axes: Mapping[str, Sequence[Any]],
    *,
    seeds: Sequence[int],
    workers: int | None = None,
) -> list[tuple[dict[str, Any], BatchSummary]]:
    """Cartesian product over `axes`, a batch of `seeds` per point.

    Axis keys are engine config paths (`"apexBurstGauge"`, `"abilities.Barrage"`,
    `"maxWeaves"`) or the reserved names `"ping_ms"`, `"pulse_ms"`, `"seconds"`.
    Points are evaluated in sorted-key, input-order fashion so the output list order is
    deterministic. Raises SimConfigError for an empty axis.
    """
```

CLI: `python -m sim.sweep --axis apexBurstGauge=60,70,80,90 --axis maxWeaves=1,2
--seeds 1-25 --csv sim/output/sweep.csv`. CSV columns: one per axis, then `n, dps_mean,
dps_stdev, gcd_mean`, then `count_<key>` for every action seen at any point (missing = 0).

### 7.4 `sim/calibrate.py` — the calibration contract

```
python -m sim.calibrate [--seeds 1-25] [--out sim/output/calibration.md] [--write-scalar]
```

1. Read `bard-analysis/output/killtime/killtime.csv` (40 rows). Required columns:
   `rank, name, aDPS, rDPS, nDPS, duration_s, death_after_final_anchor_s`. A missing column
   or fewer than 10 rows raises `CalibrationDataError` (defined in `calibrate.py`).
2. Bucket the parses by `death_after_final_anchor_s`: `<20`, `20-30`, `31-60`, `>60`
   (the merged report's bands), and also by `duration_s` rounded to the nearest 10 s.
3. For each distinct simulated duration — by default the **five** durations
   `[502, 510, 520, 532, 550]` (covering the observed 496-569 s range) — run a batch over
   `--seeds` and record mean sim DPS and mean per-action counts.
4. Fit the single scalar:
   `potency_to_damage_fitted = current * (sum_parses(aDPS) / sum_parses(sim_dps_at_that_duration))`
   using each parse's own `duration_s` matched to the nearest simulated duration. Report
   the fit as a weighted least-squares ratio and the residual spread.
5. Write `sim/output/calibration.md` and `sim/output/calibration.json`.
6. `--write-scalar` additionally writes `sim/output/stats.override.json`
   (`{"potency_to_damage": <fitted>}`) which `sim.run --stat` users can feed back in.
   **It must never edit `sim/data/stats.json`** — that file belongs to Module A.

`sim/output/calibration.md` layout (fixed):

```markdown
# CielBard sim calibration

- generated: 2026-09-17T14:02:11Z
- sim 1.0.0, engine 0.5.0, seeds 1-25, pulse 30ms, ping 0ms
- source: bard-analysis/output/killtime/killtime.csv (40 parses, 496.1-568.6s)
- fitted potency_to_damage: 173.4821 (from 100.0, x1.734821)
- residual: mean absolute error 1.83%, max 4.61%

## Fit by fight length

| duration_s | parses | mean actual aDPS | sim DPS (fitted) | ratio | err % |
|---:|---:|---:|---:|---:|---:|

## Fit by kill-window band

| death after final anchor | parses | mean actual aDPS | sim DPS (fitted) | err % |
|---|---:|---:|---:|---:|

## Per-action counts at 509.9s

| action | sim mean | top-10 mean (report) | delta | delta % |
|---|---:|---:|---:|---:|

## Per-parse residuals

| rank | duration_s | actual aDPS | sim DPS | err % |
|---:|---:|---:|---:|---:|

## Unverified assumptions

(one bullet per item from the list in section 7.4 of SPEC.md)

## Known limitations

- aDPS includes external raid buffs; the single scalar absorbs them, so
  `potency_to_damage` is not a pure stat conversion factor.
- ...
```

The **"Per-action counts"** table compares against these reference values from
`bard-analysis/output/merged-report.md` (top-10 means at ~8.5 min), hard-coded in
`calibrate.py` as `REPORT_COUNTS`:

```python
REPORT_COUNTS = {
    "RagingStrikes": 5.0, "BattleVoice": 5.0, "RadiantFinale": 5.0,
    "RadiantEncore": 5.0, "Barrage": 5.0,
    "EmpyrealArrow": 34.0, "ApexArrow": 8.4, "BlastArrow": 8.2,
    "HeartbreakShot": 56.6, "IronJaws": 11.3, "PitchPerfect": 24.3,
}
REPORT_GCDS_PER_MIN = 25.311
REPORT_ADPS_TOP10 = 34633.0
```

The **"Unverified assumptions"** section must list every item flagged in this spec:
Army's Muse/Ethos haste table, the linear shape of the Apex curve between its two
documented endpoints, non-DoT status ids, Radiant Encore 700/800/1100, Bloodletter 130 vs
the level-100 Heartbreak upgrade, the 0.6 s oGCD lock, the linear dummy HP model used to
drive the engine's TTK estimator, the Repertoire DoT independence of
MECHANICS_CORRECTIONS.md item 1 (`job.repertoire_independent_of_dots`, default `true`),
the guaranteed Barrage Hawk's Eye against the 35 % rate every other source rolls,
Barrage's two per-weaponskill effects and the rule that an ineligible weaponskill leaves
the buff intact (`weaponskill_hits` / `multi_hit_eligible` / `barrage_potency`, §4.2),
the AoE model for Apex Arrow, Blast Arrow, Resonant Arrow and Radiant Encore on a
geometry-free clustered pack, the 30 s transform windows and 20 s burst-buff durations,
and the crit/DH base-rate deconvolution of §7.2.

`sim/README.md`'s "Modelling assumptions" section covers the same set in the README's own
words; the two are not word-for-word identical and the README says so. `UNVERIFIED` is the
list a reader of the generated report gets, so an assumption added to the README must be
added here too.

### 7.5 `sim/report.py`

Pure formatting, no I/O beyond returning strings:

```python
def format_fight(result: FightResult) -> str: ...
def format_batch(summary: BatchSummary) -> str: ...
def format_counts(counts: Mapping[str, float], *, width: int = 100, indent: int = 9) -> str: ...
def format_table(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                 aligns: str = "") -> str:
    """GitHub-flavoured markdown table. `aligns` is one char per column: l, c or r."""
```

### 7.6 Tests — `tests/test_cli.py`

1. `test_run_smoke_60s` — `sim.run --seconds 60 --seed 1 --ping 0` via `subprocess`, exit
   0, stdout line 1 matches `CielBard sim \d+\.\d+\.\d+ \| engine 0\.5\.0`.
2. `test_run_output_layout` — every labelled line present, labels in the 8-char column.
3. `test_run_deterministic` — two identical invocations produce identical stdout.
4. `test_run_json_roundtrip` — `--json` output loads and has the documented keys.
5. `test_bad_flag_exits_2`, `test_downtime_overlap_exits_2`.
6. `test_strict_exit_4_on_warning` — force a warning via `--set abilities.Stormbite=false
   --set abilities.CausticBite=false --set advancedEnabled=true --set multiDot=true`.
7. `test_batch_summary_stats` — 5 seeds, `n == 5`, `dps_p05 <= dps_p50 <= dps_p95`.
8. `test_batch_worker_equivalence` — `workers=1` and `workers=2` give the same summary.
9. `test_sweep_shape_and_order` — 2x2 axes give 4 points in a documented order.
10. `test_calibrate_writes_report` — into a temp dir with a 3-row CSV fixture; asserts the
    fitted scalar is positive, the markdown contains every required `##` heading, and the
    JSON parses.
11. `test_calibrate_missing_column_raises`.
12. `test_calibrate_never_touches_data_dir` — mtime of `sim/data/stats.json` unchanged.

Tests that run a full 510 s fight are marked slow and skipped when
`CIELBARD_SIM_FAST=1` is set; the default run uses 60 s fights.

---

## 8. Module E — integration test

**Owns:** `tests/test_integration.py`, `tests/run_sim_tests.py`, `sim/README.md`,
`sim/output/.gitkeep`.

### 8.1 `tests/run_sim_tests.py`

Mirrors the style of `tests/run_mock_tests.py`: no pytest dependency, prints one summary
line, exits non-zero on failure.

```python
"""Run the simulator's unit and integration tests with plain unittest."""
# discovery: start_dir = repo_root/"tests", pattern "test_*.py", top_level_dir = repo_root
# exit(0) on success, print "CielBard sim tests passed (N tests)."
```

### 8.2 `tests/test_integration.py` — the 60 s end-to-end fight

One fixture: `run_fight(FightConfig(seconds=60, seed=7, ping_ms=0, deterministic_damage=True))`,
executed once per test class via `setUpClass`.

Invariants (each its own test method, each with a message naming the observed value):

| # | invariant | bound |
|---:|---|---|
| 1 | fight completes without `SimulationError` | — |
| 2 | GCD count | `22 <= n <= 25` (60 s / 2.5 s = 24, Paeon haste and the opener give slack) |
| 3 | no two consecutive GCDs closer than the recast | `gap >= current_gcd - 0.01` |
| 4 | total clipping | `clipped_s <= 1.5` |
| 5 | GCD uptime | `>= 0.95` |
| 6 | no cast while locked | zero `CoreRejection(reason="locked")` and no `CastRecord` whose `t_s` lies inside a previous cast's lock window |
| 7 | DoT uptime after first application | Stormbite and Caustic Bite each `>= 0.90` |
| 8 | songs | at least one song active from the first 3 s onward; `song_seconds` total `>= 55` |
| 9 | Soul Voice never exceeds 100, WM repertoire never exceeds 3 | — |
| 10 | no level-sync fallbacks | `HeavyShot == QuickNock == Bloodletter == Windbite == VenomousBite == 0` |
| 11 | every `CastRecord` maps to a known ability key | no empty `key` |
| 12 | rejections | `len(rejections) == 0` |
| 13 | engine warnings | `warnings == ()` with the default config |
| 14 | determinism | a second identical run gives an identical `to_dict(include_events=True)` |
| 15 | weaves | `1 <= ogcd_count / gcd_count <= 2.0` |
| 16 | damage accounting | `abs(total_damage - sum(damage amounts)) < 1e-6` and `dps > 0` |
| 17 | runtime | the 60 s fight completes in `< 3.0` s wall clock |
| 18 | shipped Lua untouched | the sha256 of `CielBard/CielBard_Rotation.lua` and `CielBard/CielBard_Data.lua` match the values recorded in the test at authoring time; a mismatch fails with "the engine changed — re-baseline deliberately" |

Additional scenario tests in the same file:

19. `test_downtime_window` — a 10 s window in a 60 s fight: zero casts inside it, and the
    fight still finishes with DoTs reapplied within 3 s after it ends.
20. `test_ping_reduces_weaves` — `ping_ms=150` yields strictly fewer oGCDs than
    `ping_ms=0` at the same seed.
    **The shipped engine cannot satisfy this**, so `test_20_ping_reduces_ogcd_count` is
    marked `@unittest.expectedFailure`: the suite is green while the invariant fails, and
    an *unexpected success* is itself a failure, which is how an engine change that does
    satisfy it gets reported. The arithmetic (a weave costs 0.75 s at 150 ms, clipping
    starts above ~233 ms, the oGCD count only falls above ~350 ms) is in the "Known
    mechanic mismatches" section of `sim/README.md`.
21. `test_gcd_only_mode` — `--set executionMode=GCD_ONLY --set advancedEnabled=true`
    produces `ogcd_count == 0`.
22. `test_potion_used_once_in_60s` — with `--potion`, exactly one potion cast, immediately
    before Raging Strikes.
    **The shipped engine cannot satisfy the second half**, so the "immediately before
    Raging Strikes" pair lives in `test_22_potion_used_once_before_raging_strikes`, marked
    `@unittest.expectedFailure` (an unexpected success is a failure, as in #20); the
    engine takes the potion only as the first weave of a window and the opener spends
    that slot on the song, so the potion slips to the Battle Voice slot. The satisfiable
    half — exactly one potion, and it is not the last off-GCD cast — is enforced live by
    `test_22c_exactly_one_potion`, because an `expectedFailure` method stops enforcing
    every assertion before the one that fails. See "Known mechanic mismatches" in
    `sim/README.md`.

### 8.3 `sim/README.md`

Half a page: what the simulator is, the three commands (run, batch, calibrate), where the
data tables live, how to add a new action (edit `actions.json`, add the availability rule
in §6.7's table if it needs a resource), and the pointer to this spec.

---

## 9. Cross-module checklist before you land

- [ ] `tests/run_mock_tests.py` and `tests/run_gui_tests.py` still pass.
- [ ] `tests/run_sim_tests.py` passes.
- [ ] `git status` shows no modification under `CielBard/`.
- [ ] No file outside your module's ownership list in §2 was created or edited.
- [ ] Every public function you added has the docstring this spec requires.
- [ ] No mechanic constant is a literal outside `sim/data/`.
- [ ] `python -m sim.run --seconds 510 --seed 1 --ping 0` exits 0 (once C and D are in).

## 10. Numbers this spec takes from the brief without repo cross-check

Recorded here and reproduced in `calibration.md` so nothing is chosen silently:

| item | value used | status |
|---|---|---|
| Radiant Encore potency | 700 / 800 / 1100 by codas | brief only; commonly documented as 500/600/900 pre-7.2 — **flag** |
| Bloodletter potency 130 | in tables, action disabled at 100 | conflicts with the level-100 Heartbreak upgrade — **flag** |
| Apex Arrow curve | 140 potency at 20 gauge, linear to 700 at 100 | both endpoints are official job guide values; the linear shape between them is the **assumption** |
| Army's Muse haste table | 1 / 2 / 4 / 12 % by stacks | not in the brief or the repo — **assumption** |
| Repertoire on the song timer, DoT independent | 80 % every 3 s from 42 s to 3 s remaining; `repertoire_independent_of_dots` default `true` | corrections item 1; the guides describe the proc on the song timer alone — **assumption** |
| Army's Ethos 30 s carry-over | modelled | not in the brief or the repo — **assumption** |
| Barrage triple hit | `weaponskill_hits = 3` on the `Barrage` status; 10 s window; Refulgent Arrow only | tooltip value — **verified** |
| Barrage eligibility | `multi_hit_eligible`: Refulgent Arrow only; `barrage_potency`: Shadowbite 300 (Wide Volley 220, unmodelled); anything else neither benefits nor consumes it | the potencies are tooltip values — **verified**; that an ineligible weaponskill leaves the buff intact is the **assumption** |
| Barrage's Hawk's Eye is guaranteed | every other source rolls `hawks_eye_proc_chance` (35 %) | corrections item 7 — **assumption about the knob's scope** |
| 30 s transform windows / 20 s burst buffs | `ResonantArrowReady`, `RadiantEncoreReady` 30 s; Battle Voice, Radiant Finale, Raging Strikes 20 s | corrections items 8, 9, 12 — **flag** |
| oGCD animation lock 0.6 s | default, configurable | brief says 0.6; measured MMOMinion gaps in `HANDOFF.md` were 640-719 ms including client overhead — **flag** |
| Non-DoT status ids | self-consistent internal ids | engine never hard-codes them — **safe but unverified** |
| Crit 25.4 % / DH 28.6 % | from `merged-report.md` top-10 event rates | event rates, not damage-weighted — **flag** |
| Linear dummy HP | `hp% = 100 * (1 - t / seconds)` | a modelling choice that drives the engine's TTK bands — **assumption** |
| Ladonsbite 140, Shadowbite 200 | from `CielBard_Data.lua` + `HANDOFF.md` | **verified in repo** |
| Burst 220 / Refulgent 280 / Heartbreak 180 / RoD 100 | brief and repo agree | **verified in repo** |
| Radiant Finale +2/4/6 % | brief and `CielBard_Data.lua` comment agree | **verified in repo** |
| Charged recast layout (cdmax 45, recast 15) | brief and `tests/run_mock_tests.py` agree | **verified in repo** |
