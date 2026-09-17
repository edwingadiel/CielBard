# Mechanics corrections (from The Balance and the official job guide)

Apply these on top of SPEC.md. Where SPEC.md or the code disagrees, these win.
Sources: thebalanceffxiv.com/jobs/ranged/bard/basic-guide/, /skills-overview/,
icy-veins Bard job changes (7.0+), and the official job guide tooltips.

1. **Repertoire timing.** Procs roll every 3 seconds on the *song timer*
   (at 42, 39, 36 ... 3 s remaining) with an 80% chance. No proc can occur in
   the final 3 seconds of a song. Dawntrail songs need no target and the
   guides describe the proc purely on the song timer, so model Repertoire as
   independent of DoTs. Flag this as an assumption in the calibration report.
2. **Empyreal Arrow** grants one guaranteed Repertoire proc on use.
3. **Soul Voice**: every Repertoire proc gives 5 Soul Voice, in every song.
4. **Mage's Ballad proc**: half a Heartbreak Shot charge, i.e. 7.5 s of recast.
5. **Army's Paeon proc**: haste stack, 4% each, up to 4 stacks (16%). Army's
   Muse: the song used after Army's Paeon keeps a smaller haste buff, 12% at
   full stacks, for 10 seconds.
6. **Pitch Perfect**: spend at 3 stacks by default, or earlier if Wanderer's
   Minuet or a buff window is about to expire. Repertoire stacks cap at 3.
7. **Hawk's Eye** (35% chance, 30 s) is granted by Burst Shot, Stormbite,
   Caustic Bite, Iron Jaws, and Ladonsbite. Barrage grants a guaranteed use.
   It enables Refulgent Arrow (280) or Shadowbite.
8. **Barrage** lasts 30 s and turns into Resonant Arrow (600 potency, AoE with
   55% falloff) for that window.
   *Simulator note (not a source claim):* the 30 s is modelled as the
   `ResonantArrowReady` window. The `Barrage` buff itself is the live 10 s
   triple-hit window - `statuses.json` gives it `weaponskill_hits: 3`, spent on
   the next `multi_hit_eligible` weaponskill (Refulgent Arrow 280 -> 840). The
   triple hit is not recorded above, so it is flagged as an assumption in
   `sim/README.md` and `sim/output/calibration.md`.
9. **Radiant Finale** turns into Radiant Encore for 30 s. Encore potency by
   coda: the official job guide lists 700 / 800 / 1100 (1 / 2 / 3 codas);
   Icy Veins' 7.0 changelog listed 500-900. Use the job guide values and note
   the discrepancy in the report.
10. **Iron Jaws** behaves exactly like applying both DoTs fresh, including
    snapshotting current buffs and debuffs.
11. **Heartbreak Shot**: 3 charges, 15 s each; recast layout cdmax 45.
12. **Buff durations**: Battle Voice and Radiant Finale last 20 s (Dawntrail
    change from 15). Raging Strikes 20 s.
13. **Song allocation** used by the engine: ~43.8 s WM, ~42.3 s MB, ~34.9 s AP
    (empirical top-10); the Balance basic guide recommends ~43 / ~43 / ~34.
14. **Apex/Blast** off-cycle timing per the Balance: around halfway through
    Mage's Ballad (about 21-19 s on its timer), Apex at 80+ so Blast follows.
    This is a candidate sweep, not a fixed rule in the engine.
15. **Burst GCDs** the guide expects inside buffs: Apex Arrow, Blast Arrow, a
    Barrage-buffed Refulgent Arrow, Resonant Arrow, Radiant Encore, Iron Jaws.
    Use these as an invariant check for the 2-minute window in the sim.

## Research-derived guidance (top-40 parse study, Luna/Sol reports)

Source: bard-analysis/output/luna/luna-report.md and merged-report.md.

16. **Apex timing.** Top-10 rates: Apex Arrow 0.973/min, Blast Arrow 0.950/min
    (8.4 Apex over ~8.5 min). Gauge income is roughly 100 Soul Voice per
    minute (5 per Repertoire proc at 80% every 3 s, plus Empyreal's proc), so
    ~1 Apex/min means top players fired Apex at 80 as soon as it was available
    and almost always got the Blast follow-up. They did NOT hold for 100 or for
    the mid-Mage's-Ballad position the Balance guide describes. Treat "Apex at
    80 whenever available, prefer more casts over placement" as the leading
    hypothesis. The engine currently uses apexOffcycleGauge = 90 and an
    apexHoldForBurstSeconds = 35 pre-burst hold (skipped only above 95 gauge);
    both are suspects. Sweep: apexOffcycleGauge in {80, 90, 100} x
    apexHoldForBurstSeconds in {0, 15, 35}, and report casts of Apex+Blast per
    fight alongside DPS. Do not edit the engine; the sim tests the shipped Lua
    and the sweep results decide the change.
17. **Song relaunch gaps**: median 42.06 s (top 10) vs 41.33 s; every parse has
    exactly five Raging/Battle Voice/Radiant Finale; Barrage 5 (one 4 outlier).
    Use these as calibration targets for a 510 s fight.
18. Event exports carry no gauge or Repertoire state, so any gauge claim from
    the parse study is a rate-based inference; the sim is the tool that can
    test it.
