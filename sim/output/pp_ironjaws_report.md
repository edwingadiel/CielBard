# Pitch Perfect and Iron Jaws: where the count gaps come from

- generated: 2026-09-17, sim 1.0.0, engine 0.5.0 (unmodified)
- pulse 30 ms, ping 0 ms, one enemy, no downtime, no potion
- `--stat potency_to_damage=132.401588` everywhere, so DPS is on the fitted scale
  of `sim/output/calibration.md`
- instrumentation: `sim/output/diag_pp_ij.py` (beside this report) monkeypatches
  `sim.core.Simulation` only. Nothing under `CielBard/` was modified; `tests/run_sim_tests.py`,
  `tests/run_mock_tests.py` and `tests/run_gui_tests.py` were green before and after.

The two gaps this report was opened on, from `sim/output/calibration.md`
(generated at 520 s with **no kill window**):

| action | sim /min | top-10 /min | delta % |
|---|---:|---:|---:|
| PitchPerfect | 2.678 | 2.814 | -4.8 |
| IronJaws | 1.232 | 1.308 | -5.8 |

## Summary

1. **Pitch Perfect is not a defect, and the sign of the gap depends on the kill
   window.** Repertoire stacks are never lost at song end (0.000 per fight over 40
   seeds), overcap at the 3-stack cap is 0.475 procs per fight (0.7 % of income,
   worth 57 potency), and the whole stack budget is accounted for. The rate gap is
   an income ceiling, not a scheduling loss - and once the kill window is modelled
   (which is what the parses are) the engine casts **3.06 Pitch Perfect per minute,
   8.8 % *above* the top-10 rate**, not below it.
2. **Iron Jaws is a real defect with no measurable DPS cost.** The DoTs genuinely
   fall off 1.45 times per fight and are re-applied as two hard casts. The cause is
   priority, not the threshold: four proc-consumers sit ahead of the Iron Jaws
   refresh in `E.TryGCD`, and `dotRefreshSeconds = 3.0` is only 1.2 GCDs wide.
3. **Neither engine-config knob moves DPS.** Over 150 seeds every point of
   `dotRefreshSeconds` x `snapshotIronJaws` lands inside 112 DPS (0.33 %) with a
   standard error of 45, and the ordering is not stable between the kill-window and
   no-kill-window runs. `dotRefreshSeconds = 6` or `7` reproduces the parses' Iron
   Jaws shape for free; it does not pay for itself.
4. The one Lua change worth making is a one-line urgency pre-empt for Iron Jaws
   (section 5). Expected value is about +0.16 %, which is below what 150 seeds can
   resolve - it is a correctness fix, not a DPS opportunity.

---

## 1. Pitch Perfect: the stack budget balances

40 seeds, 510 s, no kill window (the setting `sim.calibrate` uses).

| quantity | per fight |
|---|---:|
| Repertoire procs inside Wanderer's Minuet | **64.375** |
| - from the song timer (80 % every 3 s) | 50.375 |
| - guaranteed, from Empyreal Arrow | 14.000 |
| stacks spent by Pitch Perfect | **62.825** |
| **lost to the 3-stack cap** | **0.475** |
| **lost at song end (WM -> MB swap)** | **0.000** |
| left unspent when the fight clock ran out | 1.075 |
| Pitch Perfect casts | 22.300 (2.624 /min) |
| Wanderer's Minuet uptime | 199.29 s (39.1 %) |

`0.475 + 0.000 + 1.075 = 1.550 = 64.375 - 62.825`, so every stack the simulator
generates is accounted for. Both hypotheses this report was asked to test come back
negative:

**"Repertoire stacks lost at 3."** 0.475 procs per fight arrive on a full gauge -
0.74 % of income, worth `0.475 x 120 = 57` potency against a fight total of about
99,800, i.e. 0.06 %. There is nothing to recover.

**"Pitch Perfect lost at song end."** Zero, in all 40 seeds. The engine's
`CielBard_Rotation.lua:954-956` branch

```lua
if E.AbilityEnabled("PitchPerfect") and ctx.song == "WM" and
    (ctx.repertoire >= 3 or ctx.songRemaining <= 3) and
    E.TryCast(A.PitchPerfect, target, "Pitch Perfect before overcap/song end") then return true end
```

fires 3.65 times per fight inside the last 3 s of Wanderer's Minuet, against the four
Wanderer's Minuet songs that complete inside a 510 s fight (a fifth is cast at about
488 s and is still running when the clock stops). The remaining ~0.35 had already
emptied the gauge at 3 stacks and had nothing to dump. The seed-7 trace shows the pattern plainly (`songrem` is Wanderer's Minuet
time remaining):

```
  10.68 stacks=3   18.66 stacks=3   25.68 stacks=3   33.66 stacks=3
  40.68 stacks=3   43.17 stacks=1 songrem=2.49      <- song-end dump
 130.17 stacks=3  138.96 stacks=3  150.09 stacks=3
 158.97 stacks=3  165.09 stacks=2 songrem=3.00      <- song-end dump
```

The dump window is not tight, either. The last Repertoire roll of a song is at 3.0 s
remaining (`repertoire_skip_final_tick`), the dump branch opens at
`songRemaining <= 3`, and `wmSwapRemaining = 1.2` ends the song 1.8 s later - one
weave slot, which is all a 0-recast off-GCD needs.

### Why the count is nevertheless below the parses

The ceiling is income, and the engine has no knob that raises it:

- Wanderer's Minuet holds 36.1 % of the sim's song cycle (43.8 / 42.5 / 34.9 s
  measured from the seed-7 song casts), against the top-10 empirical 43.84 / 42.27 /
  34.91 = 36.2 %. **Song allocation already matches the parses**, so there is no
  Wanderer's Minuet uptime to win back.
- At 0.323 stacks per second of Wanderer's Minuet and 2.817 stacks per cast, 2.624
  casts/min is what the gauge supports. Reaching 2.814 /min at the same stack mix
  would need 0.338 stacks/s, +4.6 % of income.
- The spend policy cannot make up the difference without losing potency: Pitch
  Perfect is 100 / 220 / 360 for 1 / 2 / 3 stacks, so a 3-stack dump is 120 potency
  per stack against 110 and 100. Casting *more often* at lower stacks raises the
  count and lowers the output. That is exactly what the top-10 rate would require.

The two simulator assumptions that set income were tested directly:

| assumption | change | Pitch Perfect casts | note |
|---|---|---:|---|
| baseline | - | 22.300 | |
| `repertoire_skip_final_tick` | `true -> false` | **22.300** | no effect at all |

`repertoire_skip_final_tick = false` is unreachable in practice: the extra roll would
land at 0 s remaining on the song timer, and `wmSwapRemaining = 1.2` has already
swapped the song 1.2 s earlier (and when a song does expire naturally, `status_expire`
sorts ahead of `server_tick`, so the song ends first and the tick is epoch-invalidated).
The only assumption left that could close the gap is
`job.repertoire_proc_chance = 0.80` itself, which is a job-guide number, not
something the engine can be blamed for.

### The kill window flips the sign

`sim.calibrate` sets no `kill_time_s` - a documented limitation of the report. The
parses it compares against are all kills. With the kill window modelled
(`--kill-time 510`), `ctx.terminal` at `CielBard_Rotation.lua:932` and `:658` opens
the Pitch Perfect dump unconditionally for the last 20 s, and the count moves:

| run (40 seeds) | PP casts | /min | vs top-10 2.814 | stacks spent | PP potency | 1-stack casts |
|---|---:|---:|---:|---:|---:|---:|
| no kill window | 22.300 | 2.624 | **-6.8 %** | 62.825 | 7,485 | 1.40 |
| `--kill-time 510` | 26.025 | **3.062** | **+8.8 %** | 62.625 | 7,344 | 6.88 |
| `--kill-time 510 --set terminalDumping=false` | 21.950 | 2.582 | -8.2 % | 61.775 | 7,360 | 1.40 |

The same 62.6 stacks are fragmented into four extra 1-stack casts. **The Pitch
Perfect rate is therefore not evidence about the engine at all** - it is a readout of
whether the kill window is modelled, and the shipped engine brackets the parse rate
from both sides depending on that one switch.

---

## 2. Iron Jaws: the refresh loses a race it should not be in

40 seeds, 510 s, no kill window, shipped configuration.

| quantity | per fight |
|---|---:|
| Iron Jaws casts | 10.700 (1.259 /min) |
| - "Refresh both DoTs" branch (`:766`) | 8.275 |
| - "Late-buff Iron Jaws snapshot" branch (`:762`) | 2.425 |
| hard Stormbite casts | 2.300 (1 is the opener) |
| hard Caustic Bite casts | 2.300 (1 is the opener) |
| **DoT fall-off events** | **1.450** (2.575 individual DoT expiries) |
| DoT duration discarded by early refresh | 36.6 s |
| Stormbite / Caustic Bite uptime | 99.67 % / 98.65 % |

1.45 times per fight both DoTs expire and the engine spends **two** GCDs
(`CielBard_Rotation.lua:727-734`) re-applying them instead of one Iron Jaws. That is
the whole of the Iron Jaws count gap and the whole of the 1.3 % Caustic Bite uptime
loss.

### The mechanism, cast by cast

The refresh arms at `math.min(ctx.storm, ctx.caustic) <= c.dotRefreshSeconds`
(`:766-768`), i.e. a 3.0 s window. The simulated GCD averages 2.37 s, so the window
is **1.2 GCDs wide**. Four actions are ordered *ahead* of it in `E.TryGCD` and every
one of them is taken on sight:

| line | action | gate |
|---|---|---|
| 737 | Blast Arrow | `ready()` |
| 739 | Resonant Arrow | `ready()` |
| 741 | Radiant Encore | `ready()` and in buffs |
| 745 | Apex Arrow | gauge threshold |
| **762** | Iron Jaws snapshot | burst, `min(dot) < 22` |
| **766** | **Iron Jaws refresh** | `min(dot) <= 3.0` |

Seed 7, the fall-off at 173.96 s (the previous Iron Jaws was at 128.96 s, +45 s):

```
 170.86 GCD ApexArrow      Apex Arrow at 90 gauge        (DoTs at 3.10 s - window not yet open)
 172.38 ogcd EmpyrealArrow
 173.36 GCD BlastArrow     Consume Blast Arrow           (DoTs at 0.60 s - window open, lost)
 173.96      *** Stormbite and Caustic Bite expire ***
 175.86 GCD Stormbite      Apply Stormbite
 178.36 GCD CausticBite    Apply Caustic Bite
```

Apex Arrow fires 0.1 s before the window opens, and Blast Arrow - which Apex itself
just granted - takes the only GCD inside it. Across 40 seeds the GCDs occupying a
refresh window that ended in a fall-off are:

| blocker | per fight |
|---|---:|
| Blast Arrow | 0.625 |
| Resonant Arrow | 0.550 |
| Apex Arrow | 0.400 |
| Radiant Encore | 0.375 |
| (Stormbite re-application) | 0.075 |

1.95 blocking GCDs across 1.45 fall-off events - so the losing chains are frequently
**two** proc-consumers deep, which is 4.7-5.0 s at the simulated GCD. That is the
number that matters for any threshold fix.

### Where the fall-offs stop

40 seeds each, no kill window, `snapshotIronJaws` at its default `true`:

| `dotRefreshSeconds` | Iron Jaws | /min | Stormbite | Caustic | fall-off events | Caustic uptime | DoT s discarded | DPS | +/- sem |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **3.0 (shipped)** | 10.700 | 1.259 | 2.300 | 2.300 | **1.450** | 98.65 % | 36.6 | 34,187 | 91 |
| 4.0 | 10.775 | 1.268 | 2.225 | 2.225 | 1.350 | 98.72 % | 36.4 | 34,209 | 100 |
| 5.0 | 10.825 | 1.274 | 2.175 | 2.150 | 1.250 | 98.76 % | 36.4 | 34,227 | 98 |
| 6.0 | 12.250 | 1.441 | 1.275 | 1.250 | **0.300** | 99.35 % | 66.0 | 34,173 | 100 |
| 7.0 | 12.850 | 1.512 | 1.150 | 1.150 | **0.150** | 99.43 % | 83.5 | 34,182 | 90 |

4 s and 5 s barely help, because a 5 s window is still only two GCDs and the losing
chains are two GCDs long. The cliff is at **6 s**, where the window finally outlasts
any pair of proc-consumers. The report's 1.308 Iron Jaws/min sits between the 5 s and
6 s rows.

Note what 6 s and 7 s cost to buy that: the discarded DoT duration nearly doubles
(36.6 s -> 66.0/83.5 s per fight), and the *total* number of GCDs spent on DoTs is
unchanged - 10.70 + 2.30 + 2.30 = 15.30 at 3 s against 12.85 + 1.15 + 1.15 = 15.15 at
7 s. The threshold trades two hard casts for two extra refreshes. That is why the DPS
column is flat.

### The snapshot rule

`snapshotIronJaws` (`:762-765`) re-applies both DoTs 15-20.5 s into a burst window,
when `min(storm, caustic) < 22`, so the 45 s DoT carries Raging Strikes, Battle Voice
and Radiant Finale for its whole life. It fires 2.425 times per fight out of five
bursts - the other bursts have DoTs with more than 22 s left.

| run (40 seeds) | Iron Jaws | snapshot casts | fall-off events | Caustic uptime | DPS | +/- sem |
|---|---:|---:|---:|---:|---:|---:|
| `dotRefreshSeconds=3`, snapshot **on** | 10.700 | 2.425 | 1.450 | 98.65 % | 34,187 | 91 |
| `dotRefreshSeconds=3`, snapshot **off** | 9.575 | 0.000 | 1.550 | 98.57 % | 34,196 | 93 |
| `dotRefreshSeconds=7`, snapshot **on** | 12.850 | 2.475 | 0.150 | 99.43 % | 34,182 | 90 |
| `dotRefreshSeconds=7`, snapshot **off** | 11.900 | 0.000 | 0.100 | 99.45 % | 34,168 | 98 |

Turning it off does not simply delete 2.425 casts: the ordinary refresh branch picks
up 1.300 of them (8.275 -> 9.575), so the net Iron Jaws loss is 1.125 and the rest of
the rotation is untouched. It is *not* the cause of the fall-offs - they get
marginally worse without it (1.450 -> 1.550), because a snapshot refresh happens to
reset the DoT clock off its collision course with the next proc-consumer chain.

---

## 3. The engine-config sweeps

### `dotRefreshSeconds` x `snapshotIronJaws`, 150 seeds, kill window on

```
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-150 --workers 11 \
  --stat potency_to_damage=132.401588 \
  --axis "dotRefreshSeconds=3,4,5,7" --axis "snapshotIronJaws=true,false" \
  --csv sim/output/sweep_dots.csv
```

| dotRefreshSeconds | snapshotIronJaws | n | dps_mean | dps_sem | IronJaws | Stormbite | Caustic | delta | sigma vs best |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | true | 150 | 33,817.4 | 45.5 | 9.78 | 2.22 | 2.22 | +0.0 | - |
| 4 | false | 150 | 33,810.2 | 46.1 | 9.67 | 2.33 | 2.33 | -7.2 | 0.1 |
| 7 | true | 150 | 33,807.2 | 45.7 | **11.85** | **1.15** | **1.15** | -10.1 | 0.2 |
| 5 | true | 150 | 33,805.8 | 43.8 | 9.82 | 2.18 | 2.18 | -11.6 | 0.2 |
| 5 | false | 150 | 33,801.6 | 44.4 | 9.75 | 2.25 | 2.25 | -15.8 | 0.2 |
| **3 (shipped)** | **true** | 150 | 33,793.6 | 43.5 | 9.68 | 2.32 | 2.32 | -23.7 | 0.4 |
| 3 | false | 150 | 33,742.7 | 45.1 | 9.54 | 2.46 | 2.46 | -74.7 | 1.2 |
| 7 | false | 150 | 33,705.3 | 47.7 | 11.88 | 1.12 | 1.12 | -112.1 | 1.7 |

The whole grid spans 112 DPS, 0.33 %, against a standard error of 45 per point; the
widest separation in the table is 1.7 sigma. **There is no DPS signal in either
knob.** The only durable statement the sweep supports is the count one: at 7 s the
Iron Jaws / hard-cast shape snaps onto the parses (11.85 Iron Jaws, and the only
hard-cast DoTs left are the opener's) and DPS does not move.

### `dotRefreshSeconds` x `snapshotIronJaws`, 150 seeds, kill window off

The same grid with no kill window, which is the setting `sim.calibrate` uses, so these
DPS numbers are the ones comparable to `calibration.md`.

```
python -m sim.sweep --seconds 510 --seeds 1-150 --workers 11 \
  --stat potency_to_damage=132.401588 \
  --axis "dotRefreshSeconds=3,5,6,7" --axis "snapshotIronJaws=true,false" \
  --csv sim/output/sweep_dots_nokill.csv
```

| dotRefreshSeconds | snapshotIronJaws | n | dps_mean | dps_sem | IronJaws | Stormbite | Caustic | delta |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | false | 150 | 34,189.9 | 46.1 | 10.17 | 2.25 | 2.25 | +0.0 |
| 5 | true | 150 | 34,174.0 | 46.3 | 10.81 | 2.19 | 2.18 | -16.0 |
| 3 | false | 150 | 34,172.0 | 47.7 | 9.63 | 2.37 | 2.37 | -17.9 |
| **3 (shipped)** | **true** | 150 | 34,171.4 | 45.0 | 10.68 | 2.32 | 2.32 | -18.6 |
| 6 | false | 150 | 34,145.6 | 48.1 | 11.75 | 1.25 | 1.25 | -44.4 |
| 7 | true | 150 | 34,145.0 | 46.1 | **12.84** | **1.16** | **1.16** | -44.9 |
| 6 | true | 150 | 34,115.1 | 46.6 | 12.40 | 1.17 | 1.15 | -74.8 |
| 7 | false | 150 | 34,091.6 | 46.5 | 11.92 | 1.08 | 1.08 | -98.3 |

98 DPS of spread, 0.29 %, against a standard error of 46 - and the **ordering is not
the same as the kill-window grid above**: `7 / true` is third there and sixth here,
`3 / true` sixth there and fourth here. Two grids that disagree on rank while agreeing
that the whole span is under 0.35 % is what a null result looks like. The counts, by
contrast, are stable to within 0.2 casts between the two grids and between 40 and 150
seeds: the 6 s cliff in the fall-off rate is real, the DPS ordering is not.


### Where the kill window matters

The kill window suppresses DoT refreshes for the last `dotMinimumTTK = 18` s, so the
kill-window Iron Jaws counts run about 1.0 lower than the no-kill ones (9.68 against
10.70 at the shipped settings). Both are below the parses' 1.308 /min for the same
reason, and the fall-off count (1.45 per fight) is identical in both - the terminal
band is not where the DoTs are dropped.

### The one real DPS result this investigation turned up, and it is not Pitch Perfect

Chasing the kill-window Pitch Perfect inflation of section 1 leads to
`terminalDumping`, which is what sets `ctx.terminal` (`CielBard_Rotation.lua:658`:
`terminal = c.terminalDumping and ttk <= c.terminalTTK`). 400 seeds, kill window on:

```
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-400 --workers 11 \
  --stat potency_to_damage=132.401588 --axis "terminalDumping=true,false" \
  --csv sim/output/sweep_terminaldump400.csv
```

| terminalDumping | n | dps_mean | dps_sem | PitchPerfect | ApexArrow | BlastArrow | BurstShot | RefulgentArrow | delta | sigma |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| false | 400 | **33,924.5** | 28.9 | 22.01 | 8.22 | 8.20 | 122.70 | 51.41 | +0.0 | - |
| **true (shipped)** | 400 | 33,820.2 | 28.2 | 25.87 | 9.79 | 8.06 | 121.62 | 51.06 | **-104.4** | **2.6** |

+104.4 DPS, **+0.31 %, 2.6 sigma** - the only result in this whole investigation that
clears the noise floor. But it is **not** the Pitch Perfect fragmentation: Pitch
Perfect is an off-GCD spent from free weave slots, and splitting the same 62.6 stacks
into four more casts moves its output by 16 potency per fight (7,344 -> 7,360, measured
over 40 seeds). The DPS is in the Apex column. `CielBard_Rotation.lua:748` drops the
Apex threshold to 20 gauge inside the terminal band, and those 1.57 extra Apex casts
fire near the 100-potency floor, displacing filler GCDs worth about 237 each.

That belongs to `calibration.md` section F candidate 3 (terminal-window policy:
`terminalTTK` x `idealKillMax` x `terminalDumping`), not to this report - the number is
recorded here because this investigation is what surfaced it, and because it is the
reason the kill-window Pitch Perfect rate overshoots. Do not act on it from this
report alone: `terminalDumping` also governs charge and Soul Voice dumping, and a
single-axis 2-point sweep cannot separate the Apex effect from the rest.


---

## 4. Does any of this explain the calibration gap?

No, and the arithmetic says so.

| item | potency per fight | share of ~99,800 |
|---|---:|---:|
| Repertoire procs lost to the 3-stack cap (0.475 x 120) | 57 | 0.06 % |
| 1.45 fall-offs: 1.15 GCDs returned to filler, net of the Iron Jaws / hard-cast potency swap | ~93 | 0.09 % |
| DoT ticks missed while both DoTs are down (~1.9 s Stormbite, ~4.4 s Caustic Bite per event) | ~65 | 0.07 % |
| **total recoverable** | **~215** | **~0.22 %** |

Against the 1.4 % gap to the top-10 mean recorded in `calibration.md` section A, and
the 0.80 % that section C1 attributes to the Empyreal Arrow pre-burst hold, Pitch
Perfect and Iron Jaws together are worth about a fifth of what Empyreal is. They are
correctness items.

---

## 5. The Lua change, described and not made

Nothing under `CielBard/` was modified. The change below is what the measurements
point at; the simulator can verify it once someone else lands it.

**Problem.** `E.TryGCD` (`CielBard_Rotation.lua:722`) puts Blast Arrow (737),
Resonant Arrow (739), Radiant Encore (741) and Apex Arrow (745) ahead of the Iron
Jaws refresh (766). The refresh only arms inside `dotRefreshSeconds = 3.0` s, which
is 1.2 GCDs, and the measured blocking chains are up to two proc-consumers - 4.7 to
5.0 s - so the DoTs fall off 1.45 times per fight and cost two GCDs to restore.

**Wrong fix.** Raising `dotRefreshSeconds` to 6 or 7. It works (fall-offs 1.45 ->
0.30 / 0.15) but pays for it by discarding 30-47 extra seconds of DoT duration per
fight, which is why the DPS is flat. It also makes every refresh early, including the
ones that were never in danger.

**Right fix.** Keep the 3.0 s threshold for the ordinary refresh and add a narrow
urgency pre-empt *ahead* of the proc-consumers - directly after the
"establish missing DoTs" block that ends at line 734:

```lua
-- Iron Jaws outranks the proc consumers only when a DoT is inside one GCD of
-- falling off; the ordinary refresh at dotRefreshSeconds stays where it is.
local ironJawsEnabled = E.AbilityEnabled("IronJaws") and
    E.AbilityEnabled("Stormbite") and E.AbilityEnabled("CausticBite")
local soonest = math.min(ctx.storm, ctx.caustic)
if ironJawsEnabled and ctx.ttk > c.dotMinimumTTK and
    soonest > 0.2 and soonest <= (tonumber(c.dotUrgentSeconds) or 1.5) and
    E.TryCast(A.IronJaws, target, "Iron Jaws before fall-off") then return true end
```

with `dotUrgentSeconds = 1.5` added to `CielBardData.DefaultConfig` beside
`dotRefreshSeconds` (`CielBard_Data.lua:173`). `ironJawsEnabled` is currently computed
at line 760 and would move up to this block, with line 760 deleted.

Why 1.5 s: it is below the 2.37 s GCD, so the pre-empt only ever costs a proc-consumer
its slot when that consumer would have killed the DoT outright, and it cannot fire in
the ordinary 3 s refresh window unless that window has already been lost once.

Why the `soonest > 0.2` guard: it mirrors the threshold the "establish missing DoTs"
block above uses, so a target that has no DoTs at all never reaches this line. Iron
Jaws applies nothing on a clean target - it is a bare 100-potency weaponskill - and
without the guard `math.min(0, 0) <= 1.5` would be true and would throw a GCD away in
exactly the situation the block above is there to handle.

**Expected effect**, from the measured counts: Iron Jaws about 12.1 per fight (against
10.70), hard Stormbite and Caustic Bite back to the opener's one each (against 2.30),
1.1 GCDs per fight returned to filler, and Caustic Bite uptime from 98.65 % to about
99.9 % - **without** the 47 extra seconds of discarded DoT duration that
`dotRefreshSeconds = 7` costs. In potency that is roughly +158 per fight, +0.16 %,
which is below what 150 seeds resolve (sem 45-46 DPS, i.e. 0.13 %). Verify it with
counts, not with DPS:

```
python -m sim.sweep --seconds 510 --seeds 1-150 --workers 11 \
  --stat potency_to_damage=132.401588 --axis "dotUrgentSeconds=0,1.5" \
  --csv sim/output/sweep_urgent.csv
```

`dotUrgentSeconds = 0` must reproduce today's 10.70 / 2.30 / 2.30 exactly, which is
the regression test that the change is inert when switched off.

**No Lua change is warranted for Pitch Perfect.** The spend threshold
(`ctx.repertoire >= 3`, lines 932 and 955) and the song-end dump window
(`ctx.songRemaining <= 3`, line 955) are both hard-coded with no config key, and both
measure correct: 0.475 stacks per fight overcapped, 0.000 lost at song end. Giving
them config keys would only let a user make them worse.

---

## 6. Reproducing this report

```
# instrumented fights (prints the summary; --json writes the per-fight detail)
python sim/output/diag_pp_ij.py --seeds 1-40 --dump-seed 7 --json <path>
python sim/output/diag_pp_ij.py --seeds 1-40 --kill-time 510
python sim/output/diag_pp_ij.py --seeds 1-40 --kill-time 510 --set terminalDumping=false
python sim/output/diag_pp_ij.py --seeds 1-40 --job repertoire_skip_final_tick=false
python sim/output/diag_pp_ij.py --seeds 1-40 --set dotRefreshSeconds=4      # and 5, 6, 7
python sim/output/diag_pp_ij.py --seeds 1-40 --set snapshotIronJaws=false
python -m sim.run --seconds 510 --seed 7 --quiet --json <path>              # the 173.96 s trace

# sweeps
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-150 --workers 11 \
  --stat potency_to_damage=132.401588 \
  --axis "dotRefreshSeconds=3,4,5,7" --axis "snapshotIronJaws=true,false" \
  --csv sim/output/sweep_dots.csv
python -m sim.sweep --seconds 510 --seeds 1-150 --workers 11 \
  --stat potency_to_damage=132.401588 \
  --axis "dotRefreshSeconds=3,5,6,7" --axis "snapshotIronJaws=true,false" \
  --csv sim/output/sweep_dots_nokill.csv
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-400 --workers 11 \
  --stat potency_to_damage=132.401588 --axis "terminalDumping=true,false" \
  --csv sim/output/sweep_terminaldump400.csv
```
