# Why the engine loses Empyreal Arrow casts

Diagnosis of the largest per-action disagreement in `sim/output/calibration.md` section C:
Empyreal Arrow at **3.462 casts/min** in the simulator against **3.937/min** in the top-10
Vamp Fatale parses, where the 15 s recast allows **4.000/min**.

**Answer in one line.** The engine does not lose Empyreal to weave congestion, to
`maxWeaves`, to the clip guard, to the request throttle or to the pulse cadence. It loses
it to one predicate, `CielBard_Rotation.lua:958`, whose "5 second" pre-burst hold is
actually **about 15 seconds** long, because `nextBurstSeconds()` collapses to zero as soon
as *Radiant Finale* (110 s recast) is ready - roughly 7.5 s before *Raging Strikes* (120 s)
- and the engine then spends a further ~2.3 s on its own burst-start gates. A 15 s block
is exactly one Empyreal recast, so one use is lost per two-minute window, every window.

No file under `CielBard/` was created, edited or deleted for this report. The engine sha256
pair is unchanged (`CielBard_Rotation.lua`
`94980f7bafd5bbf90653cfc468beb827ca547e5880a75fac64cb303db1ff6721`, `CielBard_Data.lua`
`e66dd25cf0a1fc4f82b7c6e57b48ca78366b0474940470d71ec64c5452c6a0e4`).

---

## 1. Method

The instrumentation wraps a `sim.core.Simulation` **instance** from outside - `_sync_client`
and `_resolve` are replaced on the object, not in the module - so `sim/` is unchanged too.
At every 30 ms pulse the probe records, before the engine steps:

- whether Empyreal Arrow is off cooldown and usable (`Simulation._cooldown_remaining_s`,
  `_usable`), which is the same verdict the client publishes as `ActionView.ready`;
- `Simulation._gcd_remaining_s`, which is what `E.GCDRemaining` reads back;
- `Simulation.anim_lock_until_us` (the engine sees this as `MIsLocked()`);
- `CielBardEngine.state.weavesSinceGCD` and `.lastRequestAt`.

After the step it reads the engine's own decision context through a read-only Lua helper
that calls `CielBardEngine.BuildContext(target)` (`nextBurst`, `burstConfigured`,
`burstActive`, `terminal`), and the action the engine actually requested.

Every candidate fix is applied through the simulator's engine-config override mechanism
(`FightConfig.engine_config`, the mechanism behind `sim.sweep --axis`).

Fight settings unless stated otherwise: 510 s, `kill_time_s = 510`, ping 0 ms, pulse 30 ms,
one enemy, no potion, `potency_to_damage = 132.401588` (the fitted scalar in
`sim/output/stats.override.json`) applied with `--stat`. The scalar is a pure linear
multiplier on every damage instance, so every percentage and t statistic below is identical
at either scale.

### What "wasted" means

Empyreal has a 15 s recast and no charges, so 510 s allows 34 casts. Every second it sits
**off cooldown and uncast** is recast time that can never be recovered:

```
ready-but-uncast seconds  =  fight length  -  casts x 15 s   (modulo the trailing cooldown)
```

Measured: 61.91 s of ready-but-uncast time and 30 casts, i.e. 510 - 30 x 15 = 60 s. The two
agree, which is the check that the per-pulse classification is **complete** - no blocked
pulse is unaccounted for - rather than merely plausible.

---

## 2. Seconds of Empyreal cooldown wasted per fight, by reason

Shipped defaults, seeds 1-10. Every seed casts Empyreal exactly 30 times, so the seed
spread affects only the damage rolls, not the count.

| | shipped defaults |
|---|---:|
| Empyreal casts per fight | 30.00 |
| Empyreal per minute, over the 510 s fought | 3.529 |
| Empyreal per minute, on `calibration.md`'s 520 s normalisation | 3.462 |
| **Ready-but-uncast seconds per fight** | **61.91** |
| **Lost recasts (drift / 15 s)** | **4.13** |
| Lost potency (4.13 x 260) | 1,074 of 99,219 (1.08 %) |

Each blocked pulse is charged 30 ms to the first gate, in the order the engine evaluates
them: animation lock (the engine's `MIsLocked()` early return) -> GCD window
(`gcdRemaining <= gcdLeadSeconds`, where the GCD always wins) -> clip guard
(`gcdRemaining < weaveMinGcdRemaining`) -> weave cap (`weavesSinceGCD >= maxWeaves`) ->
request throttle (`requestThrottleMs`) -> another oGCD literally took the slot -> the
`holdEmpyreal` predicate. `[burst]` and `[open]` mark whether `ctx.burstActive` was true.
The `holdEmpyreal` row is listed first because it is the only gate specific to Empyreal;
the rest are the shared oGCD queue.

| blocking gate at the pulse | s/fight | share |
|---|---:|---:|
| **`holdEmpyreal` (the "5 s" pre-burst hold)** | **42.57** | **68.8 %** |
| anim-lock, inside burst | 14.39 | 23.2 % |
| clip guard `weaveMinGcdRemaining`, inside burst | 3.39 | 5.5 % |
| anim-lock, outside burst | 0.63 | 1.0 % |
| GCD window (the GCD wins), inside burst | 0.28 | 0.5 % |
| weave cap `maxWeaves`, inside burst | 0.23 | 0.4 % |
| another oGCD took the slot: Radiant Finale | 0.13 | 0.2 % |
| another oGCD took the slot: Raging Strikes | 0.12 | 0.2 % |
| unexplained (engine declined with no gate set) | 0.06 | 0.1 % |
| clip guard, outside burst | 0.05 | 0.1 % |
| another oGCD took the slot: Heartbreak Shot | 0.03 | 0.0 % |
| another oGCD took the slot: Battle Voice | 0.02 | 0.0 % |
| **`requestThrottleMs`** | **0.00** | **0.0 %** |
| **engine pulse cadence (`ticks - lastPulse < pulseMs`)** | **0.00** | **0.0 %** |
| **total** | **61.91** | **100 %** |

Two rows are zero for structural reasons worth stating, because they were on the suspect
list:

- **`requestThrottleMs = 60` never binds.** It is always masked by the 0.6 s animation
  lock, which is ten times longer. Lowering it to 30 ms is worth +12.9 DPS, t = +1.08
  (section 5) - noise.
- **The engine's own pulse gate never binds.** `Now()` advances in exact 30 ms steps and
  `c.pulseMs` is 30, so `ticks - s.lastPulse < c.pulseMs` is never true. Halving the pulse
  to 10 ms changes nothing (section 5).

### Grouped by gap, not by pulse

A "gap" is a maximal run of ready-but-uncast pulses, i.e. one delayed cast. This is the
same 61.91 s, sliced by what started the delay:

| gap root cause | gaps/fight | wasted s/fight |
|---|---:|---:|
| **`holdEmpyreal` hold, then the burst oGCD queue** | **5.00** | **59.49 (96.1 %)** |
| normal weave latency (gap <= 0.75 s) | 2.00 | 1.19 |
| burst oGCD queue with no hold involved | 1.00 | 1.11 |
| out-of-burst weave starvation | 0.10 | 0.12 |

There are exactly **five** hold gaps per fight - one per two-minute burst window - and they
carry 96 % of the loss. Their length distribution (seeds 1-10, rounded to 0.5 s):
`{14.5: 0.6, 15.0: 0.2, 16.0: 0.7, 16.5: 0.8, 17.0: 0.5, 18.0: 0.1, 18.5: 0.1}` plus a
shorter cluster at `{4.0-7.0}` in the windows where the terminal band (`--kill-time 510`,
`terminalTTK = 20`) switches the hold off before it can do its damage.

Every long gap is 14.5-18.5 s. **The 15 s recast fits inside it**, which is why exactly one
cast is lost per window rather than a fraction of one.

---

## 3. Root cause: the "5 second" hold is a 15 second hold

`CielBard/CielBard_Rotation.lua:958`, in the non-burst branch of `E.TryOGCD`:

```lua
local holdEmpyreal = c.resourcePooling and ctx.burstConfigured and ctx.nextBurst <= 5 and not ctx.terminal
if E.AbilityEnabled("EmpyrealArrow") and not holdEmpyreal and
    E.TryCast(A.EmpyrealArrow, target, "Empyreal Arrow on cooldown") then return true end
```

`ctx.nextBurst` comes from `nextBurstSeconds()` (`CielBard_Rotation.lua:236-252`):

```lua
for _, candidate in ipairs(candidates) do          -- RagingStrikes, BattleVoice, RadiantFinale
    if E.AbilityEnabled(candidate[1]) then
        if ready(candidate[2], Player.id) then return 0, true end
        best = math.min(best, cooldownSeconds(action(candidate[2])))
    end
end
```

**It returns 0 as soon as *any* of the three is ready, not when the burst can actually
start.** Radiant Finale's recast is 110 s; Raging Strikes' and Battle Voice's are 120 s.
So `nextBurst` is pinned at 0 for the whole stretch between "Radiant Finale is ready" and
"Raging Strikes is ready", and `nextBurst <= 5` is true for that stretch plus the intended
5 s in front of it.

Measured on seed 1 (`--seed 1`, shipped defaults):

| | value |
|---|---|
| Raging Strikes casts | 1.26, 124.77, 246.18, 368.46, 489.36 s |
| Radiant Finale casts | 3.78, 126.87, 248.16, 370.68, 480.96 s |
| Radiant Finale is ready before Raging Strikes by | ~7.5 s |
| plus the engine's own burst-start gates (`songReady`, `BurstDotGateSatisfied`) | ~2.3 s |
| plus the intended hold | 5.0 s |
| **effective `holdEmpyreal` window** | **~15 s per two-minute window** |

Of the 1,505 hold pulses in seed 1, **1,078 (71.6 %) had `nextBurst` exactly 0.0** - i.e.
Radiant Finale was already off cooldown and the burst had still not begun. That is 32.3 s
of the fight's 45.2 s of hold time.

The pulse-level trace of one window (seed 1, burst 4) shows it directly:

```
 354.78 s  Empyreal comes off cooldown (previous cast 339.78)
 355.0 -358.08 s  holdEmpyreal, nextBurst counting 3.4 -> 0.1   (the intended 5 s hold)
 358.11-368.43 s  holdEmpyreal, nextBurst = 0.0                 (Radiant Finale ready, Raging Strikes not)
 368.46 s  Raging Strikes            <- burstActive becomes true, the hold ends
 368.49-369.03 s  anim-lock
 369.06 s  Battle Voice
 369.09-369.63 s  anim-lock
 369.66-369.99 s  clip guard (weaveMinGcdRemaining)
 370.02 s  GCD window
 370.05-370.65 s  anim-lock
 370.68 s  weave cap (maxWeaves = 2)
 370.71-371.25 s  anim-lock
 371.28 s  Empyreal Arrow            <- 16.50 s after it was ready
```

The whole Empyreal interval distribution of that fight is 25 intervals of exactly 15.00 s
and seven long ones: **32.79, 31.50, 31.32** (a full recast lost in each of windows 2, 3
and 4), then 18.99, 17.10, 15.69, 15.60 in the tail, where the terminal band cuts the hold
short.

### Proof by isolation

Disable **only Radiant Finale**, leaving `resourcePooling = true` and the hold rule fully
in place (`advancedEnabled = true` is required, because `E.AbilityEnabled` ignores the
`abilities` table without it - `CielBard_Rotation.lua:135`). `nextBurst` then tracks only
the two 120 s actions:

| seeds 1-6 | Empyreal/fight | drift s/fight | `holdEmpyreal` s/fight |
|---|---:|---:|---:|
| `advancedEnabled = true` (control) | 30.00 | 62.03 | 42.16 |
| `advancedEnabled = true`, `abilities.RadiantFinale = false` | **33.67** | **13.77** | **1.33** |

The hold shrinks from 42.16 s to 1.33 s per fight and Empyreal recovers 3.67 casts, with
the hold rule untouched. That isolates the defect to `nextBurstSeconds()` returning 0 for a
*partially* ready burst. (DPS falls to 32,121 in that run because Radiant Finale and Radiant
Encore damage is gone - it is a diagnostic, not a recommendation.)

---

## 4. What the burst oGCD queue costs, separately

Once Raging Strikes lands, Empyreal is sixth in the burst priority list
(`CielBard_Rotation.lua:917-937`): pre-party-buff charge weave, Battle Voice, Radiant
Finale, Barrage, Pitch Perfect, **Empyreal**, Sidewinder, charge spender. At
`maxWeaves = 2` that is two to three GCDs of queue.

That queue costs **18.62 s/fight** (anim-lock 14.39 + clip guard 3.39 + GCD window 0.28 +
weave cap 0.23 + another oGCD 0.27 + unexplained 0.06, all inside burst), against the
hold's 42.57 s; the remaining 0.71 s is out-of-burst latency. The three add to 61.90 of the
61.91 s total.

Note that only **0.27 s/fight** is charged to "another oGCD literally took the slot": the
priority *order* is almost free, the cost is the 0.6 s animation lock on each of the oGCDs
ahead of it plus the 0.65 s clip guard. Re-ordering the burst list would therefore buy
very little; the queue only matters because the hold delivers Empyreal into it already
15 s late.

With the hold removed (`resourcePooling = false`), the residual is:

| | drift s/fight | lost recasts | Empyreal/fight |
|---|---:|---:|---:|
| shipped | 61.91 | 4.13 | 30.00 |
| `resourcePooling = false` | **14.71** | **0.98** | **33.60** |

and its composition is entirely structural: burst oGCD queue 11.04 s over 4.6 gaps,
normal weave latency 1.64 s, out-of-burst starvation 2.02 s. One cast per fight is the
irreducible cost of Empyreal being an off-GCD that has to wait for a weave window.

---

## 5. Candidate fixes tested through engine-config overrides

60 seeds per point, the **same** 60 seeds everywhere, so each row is a *paired* comparison
against the shipped default: the per-seed difference cancels the shared damage-roll and
tick-offset noise, and its standard error is much smaller than the batch standard errors
would suggest. `paired sem` is the standard error of the per-seed difference and `t` its
t statistic on 59 degrees of freedom.

| config point | DPS mean | DPS sem | Empyreal | Emp/min | Heartbreak | Apex | Blast | oGCD | paired delta | % | paired sem | t |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `resourcePooling=false` + `maxWeaves=3` | **34,120.8** | 73.1 | **33.75** | 3.971 | 64.68 | 10.20 | 8.47 | 162.4 | **+340.2** | **+1.01** | 70.5 | **+4.83** |
| `resourcePooling=false` | 34,006.3 | 75.7 | 33.63 | 3.957 | 64.13 | 10.23 | 8.42 | 161.5 | +225.8 | +0.67 | 64.0 | +3.53 |
| `resourcePooling=false`, `chargePoolSeconds=25`, `apexHoldForBurstSeconds=35` | 34,006.3 | 75.7 | 33.63 | 3.957 | 64.13 | 10.23 | 8.42 | 161.5 | +225.8 | +0.67 | 64.0 | +3.53 |
| `maxWeaves=3` + `weaveMinGcdRemaining=0.5` | 33,832.2 | 73.6 | 30.00 | 3.529 | 63.72 | 9.83 | 8.10 | 157.6 | +51.6 | +0.15 | 60.0 | +0.86 |
| `maxWeaves=3` | 33,814.0 | 70.6 | 30.00 | 3.529 | 62.90 | 9.82 | 8.13 | 156.8 | +33.4 | +0.10 | 42.7 | +0.78 |
| `requestThrottleMs=30` | 33,793.4 | 71.1 | 30.00 | 3.529 | 63.32 | 9.80 | 8.10 | 157.2 | +12.9 | +0.04 | 11.9 | +1.08 |
| **shipped default** | 33,780.6 | 69.3 | 30.00 | 3.529 | 63.32 | 9.78 | 8.10 | 157.2 | +0.0 | +0.00 | 0.0 | 0.00 |
| `weaveMinGcdRemaining=0.8` | 33,776.2 | 68.7 | 30.00 | 3.529 | 63.27 | 9.77 | 8.12 | 157.2 | -4.4 | -0.01 | 29.8 | -0.15 |
| `weaveMinGcdRemaining=0.5` | 33,774.0 | 75.6 | 30.00 | 3.529 | 63.33 | 9.85 | 8.13 | 157.2 | -6.5 | -0.02 | 53.7 | -0.12 |
| `resourcePooling=true`, `chargePoolSeconds=0`, `apexHoldForBurstSeconds=0` | 33,765.1 | 72.3 | 30.00 | 3.529 | 64.13 | 9.87 | 8.25 | 157.8 | -15.4 | -0.05 | 54.8 | -0.28 |
| `pulseMs=10` | 33,748.1 | 70.2 | 30.00 | 3.529 | 62.90 | 9.80 | 8.10 | 156.9 | -32.5 | -0.10 | 33.4 | -0.97 |

Readings:

1. **Nothing but `resourcePooling` moves the Empyreal count at all.** Every other point is
   exactly 30.00 casts. `maxWeaves`, `weaveMinGcdRemaining`, `requestThrottleMs` and
   `pulseMs` are all irrelevant to this defect, in both directions. That is the decisive
   negative result: the loss is a priority rule, not a weave-budget problem.
2. **The `resourcePooling=false` gain is entirely the Empyreal hold.** Setting
   `chargePoolSeconds = 0` and `apexHoldForBurstSeconds = 0` while leaving
   `resourcePooling = true` - which disables charge pooling and the Apex pre-burst hold but
   *keeps* the Empyreal hold - is worth **-15.4 DPS, t = -0.28**: nothing. The two other
   behaviours `resourcePooling` governs are worth zero, so all of the +225.8 DPS belongs to
   the one line at 958.
3. **`chargePoolSeconds` and `apexHoldForBurstSeconds` are inert once `resourcePooling` is
   off**, as expected from the Lua: that row is byte-identical to plain
   `resourcePooling=false`. Recorded so nobody re-runs it.
4. **`maxWeaves = 3` is not supported by the data.** On its own it is +33.4 DPS
   (t = +0.78). Stacked on `resourcePooling=false` it is worth a further **+114.4 DPS,
   paired sem 74.0, t = +1.55** (paired against `resourcePooling=false` over the same 60
   seeds, df = 59, two-sided p ~ 0.13) and lifts Empyreal from 33.63 to 33.75. That is
   inside two sigma, so it is suggestive at best - and it vanishes entirely at realistic
   ping, below.

### At realistic ping

Same 60 seeds, `ping_ms = 60`, paired against the shipped default at the same ping:

| config point, ping 60 ms | DPS mean | DPS sem | Empyreal | Emp/min | Heartbreak | Apex | oGCD | paired delta | % | paired sem | t |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `resourcePooling=false` | 34,007.1 | 76.6 | 33.38 | 3.927 | 64.25 | 10.12 | 161.1 | **+187.3** | **+0.55** | 66.6 | **+2.81** |
| `resourcePooling=false` + `maxWeaves=3` | 34,007.1 | 76.6 | 33.38 | 3.927 | 64.25 | 10.12 | 161.1 | +187.3 | +0.55 | 66.6 | +2.81 |
| shipped default | 33,819.8 | 71.9 | 30.00 | 3.529 | 63.27 | 9.77 | 157.0 | +0.0 | +0.00 | 0.0 | 0.00 |

The fix survives ping: +187.3 DPS at t = +2.81, and Empyreal still recovers 3.38 casts
(3.927/min, within 0.3 % of the top-10 parses' 3.937).

**`maxWeaves = 3` produces a result identical to the fix alone, to every digit** - the
third weave never fires at 60 ms ping. The arithmetic: a weave costs
`anim_lock_ogcd_s + ping` = 0.66 s, the engine only enters `TryOGCD` while
`gcdRemaining >= weaveMinGcdRemaining` (0.65 s), and the GCD's own 0.6 s lock eats the
front of the window. Two weaves land at 0.66 s and 1.32 s; the third would start at 1.98 s
with 0.52 s of a 2.50 s recast left and is refused by the clip guard. At 0 ms ping the
same third weave starts at 1.80 s with 0.70 s left and just fits, which is the whole of the
`maxWeaves = 3` effect measured above. It is an artefact of the zero-ping bench, not a
rotation improvement.

---

## 6. Where this leaves the calibration gap

| | Empyreal /min (calibration's 520 s normalisation) | vs top-10 3.937 |
|---|---:|---:|
| shipped engine | 3.462 | **-12.1 %** |
| `resourcePooling = false` | 3.880 | -1.4 % |
| `resourcePooling = false` + `maxWeaves = 3` | 3.894 | -1.1 % |

The residual 1.1-1.4 % is the irreducible weave latency of section 4, and the parses' own
3.937 is itself below the 4.000 ceiling by about the same margin.

Per recovered cast the simulator pays **+62 DPS** (+225.8 DPS for +3.63 casts), which is
944 potency of Empyreal plus the guaranteed Repertoire proc each cast carries (5 Soul
Voice, and a Pitch Perfect stack / Heartbreak charge progress / Army's Paeon stack
depending on the song).

---

## 7. The engine change (described, not made)

Two independent defects meet on line 958. Either one alone recovers most of the loss;
fixing both is a three-line change.

### 7a. `nextBurstSeconds()` must not report 0 for a partially ready burst

`CielBard_Rotation.lua:236-252`. The function answers "how long until the burst window
opens", and every caller uses it that way, but it returns 0 as soon as the *first* enabled
burst action is ready. Radiant Finale's 110 s recast therefore makes it lie by ~7.5 s,
once every two minutes.

The minimal correction is to take the **maximum** remaining cooldown over the enabled burst
actions instead of returning early on the first ready one:

```lua
local function nextBurstSeconds()
    if not majorBurstEnabled() then return 999, false end
    local worst = 0
    for _, candidate in ipairs(candidates) do
        if E.AbilityEnabled(candidate[1]) then
            if ready(candidate[2], Player.id) then
                worst = math.max(worst, 0)
            else
                worst = math.max(worst, cooldownSeconds(action(candidate[2])))
            end
        end
    end
    return worst, true
end
```

Expected effect, from the isolation run in section 3: the hold collapses from ~42.6 s to
~1.3 s per fight and Empyreal returns to ~33.7 casts. **This also fixes two other callers
that are silently running ~7.5 s early:** `chargePoolSeconds` (line 945) and
`apexHoldForBurstSeconds` (line 750). It explains `calibration.md` section E, where
`chargePoolSeconds = 35` overcapped the charge pool and lost 5.5 Heartbreak casts - the
effective pooling window at the shipped 25 is already ~32 s, so 35 becomes ~42 s and
outruns the 15 s recharge. Any change here must be re-swept against section E.

Note that `burstStartable` (line 904) uses `nextBurst <= 0.1` to decide when to *press*
Raging Strikes. With the maximum form, that condition becomes true only when all three are
ready, which is what the burst actually needs; but it should be checked that Radiant
Finale's 110 s recast is not being deliberately used to start the window early. The
observed cast order (Raging Strikes, then Battle Voice, then Radiant Finale, ~2 s apart) is
unchanged either way, because `tryStartBurst` casts Raging Strikes first and that is the
120 s action.

### 7b. The Empyreal hold needs its own key, and its default should be 0

Even with 7a applied, the hold is a 5 s delay on a 15 s cooldown with no way to turn it off
short of `resourcePooling = false`, which also governs charge pooling and the Apex hold.
Empyreal Arrow is 260 potency; a 20 % buff window is worth ~52 potency on it, against 260
potency for the use that the hold risks losing. The hold cannot pay for itself.

```lua
-- CielBard_Data.lua, Defaults, beside chargePoolSeconds / apexHoldForBurstSeconds:
empyrealHoldForBurstSeconds = 0, -- hold Empyreal this long before a burst; 0 = never hold

-- CielBard_Rotation.lua:958:
local empyrealHold = tonumber(c.empyrealHoldForBurstSeconds) or 0
local holdEmpyreal = empyrealHold > 0 and c.resourcePooling and ctx.burstConfigured and
    ctx.nextBurst <= empyrealHold and not ctx.terminal
```

Expected effect at the default of 0, measured here as `resourcePooling = false` minus the
(zero) contribution of charge pooling and the Apex hold: **+225.8 DPS, +0.67 %, t = +3.53
over 60 paired seeds**, and Empyreal 30.00 -> 33.63. This is the same +0.80 % the previous
calibration pass attributed to `resourcePooling` as a whole; the paired isolation here
shows it all belongs to Empyreal.

### 7c. Not recommended

- Re-ordering the burst priority list to put Empyreal ahead of Barrage or Pitch Perfect.
  Only 0.42 s/fight is charged to "another oGCD took the slot"; the cost is the animation
  locks, not the order.
- `maxWeaves = 3` as an engine default. Its apparent +114.4 DPS on top of the fix is
  t = +1.55 at 0 ms ping and **exactly zero at 60 ms ping**, where the third weave cannot
  fit behind the clip guard at all. It is an artefact of the zero-ping bench.
- Lowering `weaveMinGcdRemaining` or `requestThrottleMs`, or shortening `pulseMs`. All
  measured inside noise and none of them moves the Empyreal count by a single cast.

---

## 8. Limitations

- The simulator models a fixed 0.6 s animation lock for every oGCD and GCD, and adds ping
  on top. `HANDOFF.md` measured 640-719 ms gaps on a live client including overhead, so the
  anim-lock share of the drift (23 %) is a lower bound.
- `--kill-time 510` puts the fight in the terminal band for its last 20 s, which switches
  the hold off (`not ctx.terminal`) and is why the fifth window loses only a partial cast.
  Without `--kill-time` the engine never reaches the terminal band and the fifth window
  loses a full cast too; the shipped-default drift rises accordingly.
- Everything here is a single-target striking dummy with no downtime. Movement, target
  swaps and real downtime all interact with the weave queue and are not modelled.
- The counts are exactly deterministic (30.00 at every seed), but the DPS deltas are not:
  they are reported with paired standard errors and t statistics, and anything under about
  2 sigma in section 5 is noise.

---

## 9. Reproducing this report

Instrumentation scripts are not part of the `sim` package; they wrap it from outside. The
config points are reproducible with the shipped tools:

```
# the shipped-default and fixed DPS numbers (unpaired, sweep form)
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-60 --workers 10 \
  --stat potency_to_damage=132.401588 \
  --axis "resourcePooling=true,false" --axis "maxWeaves=2,3" \
  --csv sim/output/empyreal_fix.csv

# the isolation of the Empyreal hold from charge pooling and the Apex hold
python -m sim.sweep --seconds 510 --kill-time 510 --seeds 1-60 --workers 10 \
  --stat potency_to_damage=132.401588 \
  --axis "resourcePooling=true,false" --axis "chargePoolSeconds=0,25" \
  --axis "apexHoldForBurstSeconds=0,35" --csv sim/output/empyreal_isolate.csv

# the per-fight cast times behind section 3
python -m sim.run --seconds 510 --kill-time 510 --seed 1 \
  --stat potency_to_damage=132.401588 --json sim/output/empyreal_seed1.json
```

The paired tables in section 5 come from a per-seed driver that calls
`sim.core.run_fight` directly over a process pool and differences the same seeds across
config points; the per-pulse tables in sections 2-4 come from the instance-level probe
described in section 1. Both are checked in beside this file as data:

| file | contents |
|---|---|
| `sim/output/empyreal_reasons.csv` | the per-reason drift tables of sections 2 and 4, for the shipped engine, for `resourcePooling=false`, and for the Radiant-Finale-disabled isolation |
| `sim/output/empyreal_paired.csv` | every paired config point of section 5, at 0 ms and 60 ms ping, with `paired_delta`, `paired_sem` and `t` |
