# CielBard simulator

A level-100 Bard training-dummy simulator that **drives the shipped CielBard Lua engine**.
`sim/client.py` publishes a fake MMOMinion API into a `lupa` `LuaRuntime`, loads
`CielBard/CielBard_Data.lua` and `CielBard/CielBard_Rotation.lua` verbatim, and calls
`CielBardEngine.Step(false)` once per pulse. `sim/core.py` owns the clock, the event queue
and every game rule; the engine's decisions are the thing under test, so nothing under
`CielBard/` is ever modified (the integration suite pins both files by sha256).

Everything is deterministic given a seed: two runs of the same `FightConfig` produce
byte-identical JSON, in the same process or in different ones.

## Install

There is nothing to build. The simulator is standard library plus `lupa`, and it is run
from the repository root so that `import sim` and the relative path to `CielBard/` both
resolve.

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m pip install lupa
cd C:\dev\CielBard
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -c "import lupa, sim; print(lupa.__version__, sim.__version__)"
```

Use that interpreter for everything - a bare `python` on this machine is the Microsoft
Store stub. No virtualenv, no new `tests/requirements.txt` entry, no other dependency.

## Commands

All four entry points are modules, so they are run with `-m` from the repository root.

### Run one fight

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m sim.run --seconds 510 --seed 1 --ping 0
```

```
CielBard sim 1.0.0 | engine 0.5.2
fight    510.0s  seed=1  ping=0ms  pulse=30ms  gcd=2.38s  enemies=1
damage   13597833   dps 26662.4   potency 102310 (200.6/s)
gcds     214 (25.18/min)   ogcds 157   weaves/gcd 0.73
uptime   gcd 100.0%   clipped 0.00s   rejections 0
dots     CausticBite 98.6%   Stormbite 99.9%
songs    WM 5x 39.8s   MB 4x 42.4s   AP 4x 35.3s
waste    repertoire 30   soulvoice 0   charges 0   barrage 0
counts   ApexArrow 9  ArmysPaeon 4  Barrage 5  BattleVoice 5  BlastArrow 9  BurstShot 119
         CausticBite 3  EmpyrealArrow 33  HeartbreakShot 62  IronJaws 10  MagesBallad 4
         PitchPerfect 24  RadiantEncore 5  RadiantFinale 5  RagingStrikes 5  RefulgentArrow 51
         ResonantArrow 5  Sidewinder 5  Stormbite 3  WanderersMinuet 5
rates    crit 27.01%   dh 26.72%   events 685
```

Flags: `--seed`, `--ping`, `--pulse`, `--enemies`, `--enemy-spread`, `--potion`,
`--deterministic`, `--downtime A:B` (repeatable), `--kill-time SECONDS`,
`--set key=value` (engine config, dotted keys allowed), `--stat key=value`,
`--json PATH`, `--trace`, `--quiet`, `--strict`.
Exit codes: 0 ok, 2 bad config, 3 Lua or simulation error, 4 `--strict` with rejections or
engine warnings.

### Multi-target packs

`--enemies N` puts N striking dummies in the fight. Dummy 1 is the engine's target and
stands at the origin; the other N-1 are identical clones on a ring of `--enemy-spread`
yalms (default 2.0) around it.

The engine is never told the number. It counts the pack itself, out of the fake client's
entity list, exactly as it does live (`CielBard_Rotation.lua`):

| engine call | query | filter it applies | what it drives |
|---|---|---|---|
| `E.CountEnemiesNear` | `EntityList("alive,attackable,maxdistance=30")` | `entity.pos` within 5 yalms of the target's | `ctx.enemies`, hence every `AoETargetsFor` threshold (Ladonsbite 2, Shadowbite 2, Shadowbite under Barrage 3, Rain of Death 2) |
| `E.FindMultiDotTarget` | `EntityList("alive,attackable,incombat,maxdistance=25")` | in combat, targetable, in LOS, above `multiDotMinHPPercent` | the secondary DoT target, when `multiDot` is on |

`FakeClient.set_entities` applies both filter clauses the engine depends on: it drops
`incombat=False` entities from the `incombat` filter, and it drops entities whose
`distance2d` exceeds the filter's `maxdistance`. The second one matters because
`E.FindMultiDotTarget` trusts the filter and never re-checks the distance itself. So the
spread is a real lever, not
decoration: `--enemies 3 --enemy-spread 12` leaves every clone outside the 5-yalm
cluster test, the engine counts one enemy, and the fight is decision-for-decision
identical to a lone dummy. `tests/test_integration.py`'s `TestMultiTargetScenarios`
runs 1, 2, 3 and 5 dummies, prints the per-action cast counts side by side, and pins
both behaviours.

AoE damage is resolved per target from `actions.json`: an action with `aoe` and no
`falloff` (Ladonsbite 140, Shadowbite 200, Rain of Death 100, Apex Arrow) deals its
full potency to every dummy, and one with `falloff: 0.5` (Blast Arrow, Resonant Arrow,
Radiant Encore) deals full potency to the first and half to each of the others.

A dummy is only splashed when the ring radius is within `job.aoe_cluster_radius_yalms`
(5.0), which is the same 5-yalm test `E.CountEnemiesNear` applies. So the damage model
and the engine always agree about who is in the pack: at `--enemy-spread 12` the engine
counts one enemy *and* nothing splashes, and the fight is identical to a lone dummy in
both decisions and damage.

The simulator has no geometry beyond that single ring, so a cone (Ladonsbite), a
straight line (Apex Arrow, Blast Arrow) and a circle around the target (Shadowbite,
Rain of Death, Radiant Encore) all hit the same set of dummies, and there is no
per-action radius. A clustered pack is the best case for every one of them; do not read
a multi-target DPS number as an encounter result.

`--kill-time` is the one flag worth explaining. By default the target is a striking dummy
that never dies, so the engine's TTK estimator never reaches its terminal band. Passing
`--kill-time 510` restores the linear dummy of SPEC section 6.6, whose HP hits zero at that
time; the engine then stops refreshing DoTs for the last `dotMinimumTTK` (18 s) of the
fight, exactly as it would on a real kill. Use it when comparing against kill parses, leave
it off for dummy-style sustained DPS.

### Batch a seed range

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m sim.batch --seconds 510 --seeds 1-200 --json sim/output/batch.json
```

One fight per seed across a process pool (`--workers N`, or `--in-process` to stay single
threaded), aggregated into mean / sd / p05 / p50 / p95 DPS plus mean per-action counts. It
accepts the whole `sim.run` fight-flag set.

### Sweep a configuration axis

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m sim.sweep --seconds 510 --seeds 1-25 --axis "maxWeaves=1,2" --axis "dotRefreshSeconds=2,3,4" --csv sim/output/sweep.csv
```

Runs one batch per point of the cartesian product of the `--axis` values and prints a
markdown table sorted by mean DPS, best first. An axis name is an engine config key
(dotted keys such as `abilities.ApexArrow` work) or one of the reserved `ping_ms`,
`pulse_ms`, `seconds`; `seconds` carries `--kill-time` with it, so a swept duration never
leaves the dummy dead part-way through the fight.

Read the table with its `dps_sem` column (`dps_stdev / sqrt(n)`) next to `delta`: at 510 s
neighbouring points routinely differ by less than the batch standard error, so a `delta`
inside a couple of `dps_sem` is noise, not a winner. The CSV keeps the deterministic
evaluation order instead of the sorted one, so sweep CSVs stay diffable.

### Calibrate against the real parses

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" -m sim.calibrate --seeds 1-25 --out sim/output/calibration.md
```

Fits the single `potency_to_damage` scalar in `stats.json` so simulated DPS matches the 40
Vamp Fatale parses in `bard-analysis/output/killtime/killtime.csv`, banded by kill time,
and writes a markdown report with the residuals and the per-action count comparison. It
never edits `sim/data/stats.json`; `--write-scalar` emits `sim/output/stats.override.json`
beside the report, for you to copy in deliberately. The checked-in report was fitted over
seeds 1-150 at `potency_to_damage 132.4016` (from the uncalibrated 100.0), residual mean
0.99 %, max 2.73 %. **That fit predates the Patch 7.5 potency corrections** (Apex
140-700, Blast Arrow 700, Resonant Arrow 640), which raise single-target potency by
about 1.9 % on the 510 s seed-1 reference fight (100408 -> 102310), so it has to be
re-run before the
scalar or any DPS number taken from it is quoted again. Regenerating overwrites everything above the `# Analysis` marker, so
re-append the hand-written analysis afterwards - the report says so at the marker.

### Repository output policy

Everything the four entry points write lands in `sim/output/`. Two kinds of file live
there and they are versioned differently.

**Versioned (canonical evidence).** A file a reviewer reads, cites, or diffs between
releases. Each carries its own generation stamp, and a report generated before a
potency or engine change carries a staleness banner at the top until it is re-run -
`sweep_apex.md`, `empyreal_report.md`, `pp_ironjaws_report.md` and `FINDINGS.md` all
predate the Patch 7.5 corrections and say so:

- every `.md` report - `calibration.md`, `sweep_apex.md`, `empyreal_report.md`,
  `pp_ironjaws_report.md`, `FINDINGS.md`;
- `calibration.json`, the machine-readable head of the calibration report;
- summary `.csv` - one row per swept configuration or per diagnostic band, small,
  diffable and stable across runs (`sweep_*.csv`, `diag_*.csv`, `killband*.csv`,
  `empyreal_*.csv`).

**Not versioned (run artifacts).** Per-seed and intermediate JSON: it is large, it is
regenerated by a single command, and it changes wholesale whenever a potency or the
engine changes, so it makes diffs unreadable without telling anyone anything a report
does not. These patterns are in the repository `.gitignore`:

```
sim/output/ab_*.json
sim/output/sweep_*_confirm*.json
sim/output/sweep_apex.json
sim/output/batch.json
```

Five files matching them were committed before this policy existed
(`ab_before.json`, `ab_after.json`, `sweep_apex.json`, `sweep_apex_confirm.json`,
`sweep_apex_confirm2.json`) and are removed in the next commit; the `.gitignore` entries
keep them from coming back. `stats.override.json` stays tracked deliberately - it is not
a report but a proposed `stats.json` edit, and it is the one file whose whole purpose is
to be read and copied by hand.

A per-fight `--json PATH` dump is a working file. Write it outside the repository, or to
a path already covered above.

## Tests

```
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" tests/run_sim_tests.py
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" tests/run_mock_tests.py
"C:\Users\xemna\AppData\Local\Programs\Python\Python312\python.exe" tests/run_gui_tests.py
```

Plain `unittest` discovery over `tests/test_*.py`, no pytest needed.
`tests/test_mechanics_corrections.py` holds one test per numbered item of
`sim/MECHANICS_CORRECTIONS.md` (items 1-12); item 15, the composition of the 2-minute buff
window, is asserted end to end by `TestBurstWindowContents` in `tests/test_integration.py`
over a 300 s fight.
`tests/test_integration.py` runs one deterministic 60 s fight and asserts the 18 end-to-end
invariants of SPEC section 8 (GCD count and spacing, clipping, uptime, DoT and song
coverage, no overcaps, no level-sync fallbacks, no rejections or engine warnings,
determinism, weave ratio, damage accounting, wall-clock budget, and the engine sha256
guard) plus the downtime, ping, `GCD_ONLY` and potion scenarios. The `run_mock_tests.py`
and `run_gui_tests.py` suites predate the simulator, are untouched by it, and must stay
green.

## Data tables

No mechanic constant lives in code. Everything is JSON under `sim/data/`:

| file | contents |
|---|---|
| `actions.json` | one record per CielBard ability key: id, kind, potency, recast, cooldown, charges, `aoe` / `falloff`, `grants`, `requires`, `multi_hit_eligible`, `barrage_potency` |
| `statuses.json` | buff/debuff ids, durations, DoT tick potencies, the damage/crit/direct-hit modifiers they contribute, and `weaponskill_hits` (Barrage's triple hit) |
| `job.json` | GCD base and haste rounding, animation locks, Repertoire and Soul Voice rules, coda and Apex curves, the AoE cluster radius |
| `stats.json` | crit and direct-hit rates and multipliers, damage variance, and `potency_to_damage` (the calibration scalar) |

`Tables.verify_against_lua()` cross-checks every action and DoT id against
`CielBard/CielBard_Data.lua`; `tests/test_tables.py` fails on any drift.

## Adding an action

1. Add its record to `sim/data/actions.json` under the same key `CielBardData.Actions`
   uses, with the id taken from the Lua. Name any status it applies in `grants` and any
   status it needs in `requires`; add the status to `statuses.json` if it is new.
2. If it needs a resource the tables cannot express (a gauge threshold, a stack count),
   add the rule to the `resource_ok` list in SPEC section 6.7 and implement it in
   `sim/core.py`'s availability pass - that is the only place a new mechanic may need code.
3. If its potency scales, put the curve in `job.json` and read it where Apex, Pitch Perfect
   and Radiant Encore are read.
4. Re-run `tests/run_sim_tests.py`.

## Things that will look like bugs and are not

- **The Lua garbage collector is switched off and driven by hand.** lupa 2.8 embeds Lua
  5.5, and a collection that runs inside a Lua-to-Python call can leave a Python-object
  wrapper pointing at the wrong object - `Player.castinginfo` starts reading back as a
  cached action proxy, the engine stops observing its own casts, and identical fights
  diverge. `FakeClient._install_gc_guard` stops the automatic collector and `step()` runs a
  full collection every 64 pulses, between pulses, when no Lua call is in flight. Lua heap
  usage over a 510 s fight stays flat at 140-200 KB. Do not remove this without
  re-checking determinism over a full 510 s fight.
- **`pairs` is replaced with a key-sorted version** before the engine is loaded, for the
  same reason: Lua 5.5 seeds its string hash from the wall clock, so `pairs()` over
  `D.Songs` or `E.state.codas` iterates differently in every `LuaRuntime`. Array-only
  tables take the cheap path. It costs about 7 % of the pulse budget.
- **Repeat fights in one long-lived process get about 3x slower** after roughly 20 000
  pulses of cumulative work. This is the operating system throttling the process, not the
  simulator: a pure-Python benchmark in the same process slows by the same factor at the
  same moment, and the fights do identical work (same pulse count, byte-identical result).
  A cold process runs the 510 s fight in 1.4-1.8 s, inside the 2.0 s budget.

## Modelling assumptions

`sim/MECHANICS_CORRECTIONS.md` is applied in full to the data tables and, where a table
could not express it, to `sim/core.py`. These are the parts of it that are assumptions
rather than verified facts, plus the flags that turn them off. `sim/calibrate.py`'s
`UNVERIFIED` tuple prints the same set, in its own words, under "Unverified assumptions"
in `sim/output/calibration.md`; SPEC section 7.4 makes that report the place every flagged
item must appear, so an assumption added here has to be added there too.

- **Repertoire is rolled on the song timer, not on the world tick.** One roll every
  `job.server_tick_s` (3 s) from 42 s remaining down to 3 s remaining, at
  `job.repertoire_proc_chance` (80 %), and never in the song's final 3 s. The flags are
  `repertoire_on_song_timer` and `repertoire_skip_final_tick`, both `true`.
- **Repertoire is independent of the DoTs.** Dawntrail songs need no target and the
  guides describe the proc purely on the song timer, so a roll does not check whether a
  DoT is ticking. This is the assumption most likely to be wrong, so it is a flag:
  `job.repertoire_independent_of_dots`, default `true`. Set it to `false` (through
  `sim/data/job.json` or `FightConfig.job_overrides`) to make a proc require one of our
  DoTs on the primary target. The superseded key `repertoire_requires_dot` is still read
  as its inverse when the new key is absent, and `Tables.load()` accepts a `job.json`
  carrying either spelling. `job_overrides` keys are validated against `job.json` and the
  merged table is re-checked, so a typo raises `SimConfigError` rather than quietly
  leaving the default in place; a `None` value deletes a key.
- **Army's Muse is 1 / 2 / 4 / 12 % haste by Army's Paeon stack count, for 10 s**, carried
  to the next song through a 30 s Army's Ethos. The 12 % at four stacks is the documented
  number; the three lower steps and the Ethos carry-over are the simulator's model.
- **Radiant Encore is 700 / 800 / 1100 by coda count.** These are the official job guide's
  values; Icy Veins' 7.0 changelog listed a lower 500-900 curve. The discrepancy is
  flagged, not resolved.
- **Barrage's Hawk's Eye is guaranteed; every other source rolls 35 %.** Burst Shot,
  Stormbite, Caustic Bite, Iron Jaws and Ladonsbite all roll `job.hawks_eye_proc_chance`,
  which is the single knob for the rate; Barrage's grant is written as certain in
  `actions.json` and the knob does not gate it.
- **Barrage does two different things, and which one is per weaponskill.** For 10 s
  (`statuses.json` `Barrage`) it either makes the next weaponskill land
  `weaponskill_hits` (3) times or raises its potency, never both:
  - `actions.json` `multi_hit_eligible` marks the triple hit and, per the job guide,
    **only Refulgent Arrow** carries it (280 -> 840);
  - `actions.json` `barrage_potency` marks the flat increase the AoE Hawk's Eye
    weaponskills get instead - Shadowbite 200 -> 300 per target (Wide Volley's
    140 -> 220 is the same rule below level 72, but Wide Volley is absent from
    `CielBardData.Actions` so the simulator has no record for it);
  - everything else - Heavy Shot, Burst Shot, Ladonsbite, Quick Nock, Resonant Arrow,
    Apex, the DoTs, Radiant Encore, every off-GCD - neither benefits from the buff nor
    consumes it, which is what lets the engine's Barrage -> Resonant Arrow -> Refulgent
    Arrow ordering produce the "Barrage-buffed Refulgent Arrow" of corrections item 15.

  The hit count, the potency override and the eligibility list all come from the
  tooltips; what remains the simulator's model is that an ineligible weaponskill leaves
  the buff untouched rather than wasting it.
- **The Barrage and Radiant Finale transform windows are 30 s** (`ResonantArrowReady`,
  `RadiantEncoreReady`), and Battle Voice, Radiant Finale and Raging Strikes last 20 s.
- **Bloodletter's 130 potency** is kept in the tables although the action is disabled at
  level 100, where it is trait-upgraded to Heartbreak Shot (180).
- **The base crit and direct-hit rates** are the merged report's top-10 *event* rates
  (25.366 % / 28.587 %) with the simulator's own buff uptimes deconvolved out, because
  those observed rates already contain Wanderer's Minuet, Army's Paeon and Battle Voice.
  They are still event rates rather than damage-weighted rates, and the parses' external
  raid buffs are not separable.
- **Apex Arrow's endpoints are documented**: 140 potency at 20 gauge and 700 at 100
  (official job guide, Patch 7.5). What remains the simulator's model is that the curve
  between them is linear.
- **Apex Arrow, Blast Arrow, Resonant Arrow and Radiant Encore are AoE.** Apex Arrow
  deals its full potency to every enemy it hits; the other three deal full potency to
  the first and half to each of the rest (`falloff: 0.5`). Since the simulator has no
  geometry, all four hit the whole pack, which is their best case - see "Multi-target
  packs".
- **Non-DoT status ids are internal to the simulator.** The engine only compares
  `action.statusgainedid` to `buff.id`, so they are self-consistent but unverified.
- **The 0.6 s oGCD animation lock** is the brief's number; measured MMOMinion gaps in
  `HANDOFF.md` were 640-719 ms including client overhead.
- **The linear dummy HP model** (`hp% = 100 * (1 - t / seconds)`) is what drives the
  engine's TTK bands under `--kill-time`.

Items 13 and 14 of the corrections (song allocation, Apex placement) are engine
configuration, not simulator mechanics: the simulator never edits `CielBard/`, so they are
sweep inputs. Items 16-18 are open investigations and are deliberately not implemented.
The generated head of `sim/output/calibration.md` was re-run after this pass
(`potency_to_damage 132.4016`); the hand-written analysis below its `# Analysis` marker
was measured on the previous 136.7979 scale and carries a notice saying so.

## Known mechanic mismatches

Two scenarios in SPEC section 8.2 cannot be satisfied by the shipped engine. They are
documented rather than papered over, and their tests are marked
`@unittest.expectedFailure`, so the suite is green while an engine change that *does*
satisfy them is reported as an unexpected success (which fails the run):

- **8.2 #20, "ping 150 ms yields strictly fewer oGCDs".** Unreachable arithmetically. A
  weave costs `anim_lock_ogcd_s + ping` = 0.75 s at 150 ms, and the engine only weaves
  while `weaveMinGcdRemaining` (0.65 s) of the GCD is left, so a 2.5 s GCD still fits two
  weaves: clipping begins only above about 233 ms of ping, and the oGCD count only falls
  above about 350 ms. That matches the game, where double weaving at 150 ms ping is free.
- **8.2 #22, "the potion is used immediately before Raging Strikes".** The engine only
  takes the potion when it is the *first* weave of the window
  (`weavesSinceGCD + 1 < maxWeaves`, and `maxWeaves` is 2). On the opener `E.TrySong` runs
  before the burst block and spends that slot on Wanderer's Minuet, so Raging Strikes goes
  in the second slot and the potion slips to the next window, landing before Battle Voice
  instead. Reproducing the real opener would need a pre-pull window, where a player casts
  the song and drinks the potion before the target exists. Only the "immediately before
  Raging Strikes" pair is expected to fail: "exactly one potion, and it is not the last
  off-GCD cast" *is* satisfied today and is enforced live by `test_22c_exactly_one_potion`,
  because `unittest` stops checking a method's remaining assertions once one fails, so an
  `expectedFailure` method enforces nothing after its first failure.

## Further reading

`sim/SPEC.md` is the complete contract: module ownership, the literal public signatures,
the pulse loop, cooldown and charge semantics observed on the live client, and the
calibration procedure. `sim/MECHANICS_CORRECTIONS.md` records the job-guide corrections
that override the spec where they disagree.
