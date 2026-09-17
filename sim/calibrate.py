"""Calibrate the simulator against the 40 observed Vamp Fatale parses.

    python -m sim.calibrate [--seeds 1-25] [--out sim/output/calibration.md] [--write-scalar]

Reads `bard-analysis/output/killtime/killtime.csv`, runs a batch at each of a handful of
fight lengths, fits the single `potency_to_damage` scalar that maps simulated potency DPS
onto the observed aDPS, and writes `sim/output/calibration.md` plus `calibration.json`.

This module never writes inside `sim/data/` - those tables belong to module A.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _datetime
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import report
from .batch import BatchSummary, parse_seeds, run_batch
from .core import SimulationError
from .run import EXIT_CONFIG, EXIT_ENGINE, EXIT_OK, add_fight_flags, config_from_args, fail
from .run import write_json
from .runconfig import FightConfig, SimConfigError

try:  # pragma: no cover - only while module B has not landed
    from .client import LuaBridgeError
except ImportError:  # pragma: no cover
    class LuaBridgeError(RuntimeError):  # type: ignore[no-redef]
        """Placeholder used when `sim.client` is not importable."""


class CalibrationDataError(ValueError):
    """Raised when the parse CSV is missing, malformed or too small to fit against."""


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = Path("bard-analysis") / "output" / "killtime" / "killtime.csv"
DEFAULT_OUT = Path("sim") / "output" / "calibration.md"
DATA_DIR_NAME = "data"

REQUIRED_COLUMNS = ("rank", "name", "aDPS", "rDPS", "nDPS", "duration_s",
                    "death_after_final_anchor_s")
MIN_PARSES = 10
DEFAULT_DURATIONS: tuple[float, ...] = (502.0, 510.0, 520.0, 532.0, 550.0)
BAND_ORDER = ("<20", "20-30", "31-60", ">60")

REPORT_COUNTS = {
    "RagingStrikes": 5.0, "BattleVoice": 5.0, "RadiantFinale": 5.0,
    "RadiantEncore": 5.0, "Barrage": 5.0,
    "EmpyrealArrow": 34.0, "ApexArrow": 8.4, "BlastArrow": 8.2,
    "HeartbreakShot": 56.6, "IronJaws": 11.3, "PitchPerfect": 24.3,
}
"""The merged report's absolute top-10 mean counts, exactly as it prints them."""

REPORT_COUNTS_DURATION_S = 518.2
"""The fight length those absolute counts were taken over.

The report gives Heartbreak Shot both ways - 56.6 casts and 6.553/min - so the duration
behind its count column is 56.6 / 6.553 * 60 = 518.2 s. Counts are converted to rates
with it before being differenced, because the simulator runs at whatever `--seconds`
asks for and an absolute-count comparison silently carries that duration ratio.
"""

REPORT_RATES_PER_MIN: dict[str, float] = {
    key: value * 60.0 / REPORT_COUNTS_DURATION_S for key, value in REPORT_COUNTS.items()
}
REPORT_RATES_PER_MIN["RainOfDeath"] = 0.831

CHARGE_SPENDERS = ("HeartbreakShot", "RainOfDeath", "Bloodletter")
"""Actions that share the one Heartbreak/Bloodletter/Rain of Death charge pool.

They must be compared as a group: the report's top 10 spent 6.553 charges/min on
Heartbreak Shot and 0.831 on Rain of Death, and says in so many words that the split is
about *where* the charge was converted, not about charge underuse. The simulator fights
one target, so it converts every charge into Heartbreak Shot; differencing that against
the Heartbreak-only number reports a large overuse where the pool is in fact slightly
underused.
"""
REPORT_CHARGE_SPENDERS_PER_MIN = 7.384
REPORT_CASTS_PER_MIN = 45.270
REPORT_GCDS_PER_MIN = 25.311
REPORT_ADPS_TOP10 = 34633.0

UNVERIFIED = (
    "Army's Muse / Army's Ethos haste table (1 / 2 / 4 / 12 % by stacks, 30 s Ethos "
    "carry-over): not in the brief or the repository - simulator assumption.",
    "Apex Arrow potency floor of 100 at 20 gauge, linear to 600 at 100: the brief fixes "
    "only the 600 endpoint - simulator assumption.",
    "Non-DoT status ids (Hawk's Eye, the buffs, the ready markers, the song statuses) are "
    "internal to the simulator; the engine only compares action.statusgainedid to buff.id, "
    "so they are self-consistent but unverified against the live client.",
    "Radiant Encore potency 700 / 800 / 1100 by coda count: taken from the official job "
    "guide; Icy Veins' 7.0 changelog listed 500 / 600 / 900 - flagged, not resolved.",
    "Barrage's Hawk's Eye is guaranteed while every other source rolls "
    "job.hawks_eye_proc_chance (35 %): Burst Shot, Stormbite, Caustic Bite, Iron Jaws and "
    "Ladonsbite all move together with that one knob, and Barrage's grant is written as "
    "certain in actions.json so the knob does not gate it (MECHANICS_CORRECTIONS.md "
    "item 7) - the scope of the knob is the assumption.",
    "Barrage makes the next eligible weaponskill land three times (statuses.json "
    "weaponskill_hits = 3, a 10 s window; Refulgent Arrow 280 -> 840). Eligibility is the "
    "actions.json flag multi_hit_eligible - Burst Shot, Refulgent Arrow, Ladonsbite, "
    "Shadowbite and their level-sync precursors - and anything else (Resonant Arrow, Apex, "
    "the DoTs, Radiant Encore, every off-GCD) neither benefits nor consumes the buff. "
    "MECHANICS_CORRECTIONS.md item 8 records only the 30 s Resonant Arrow transform, so "
    "both the hit count and the eligibility list are the simulator's model.",
    "The Barrage and Radiant Finale transform windows are 30 s (ResonantArrowReady, "
    "RadiantEncoreReady) and Battle Voice, Radiant Finale and Raging Strikes last 20 s "
    "(MECHANICS_CORRECTIONS.md items 8, 9 and 12) - taken from the guides, not measured "
    "on the live client.",
    "Bloodletter 130 potency: kept in the tables but the action is disabled at level 100, "
    "where it is trait-upgraded to Heartbreak Shot (180) - brief/game discrepancy.",
    "oGCD animation lock of 0.6 s: the brief says 0.6, while measured MMOMinion gaps in "
    "HANDOFF.md were 640-719 ms including client overhead - flagged, configurable.",
    "Linear dummy HP model (hp% = 100 * (1 - t / seconds)) used to drive the engine's TTK "
    "estimator and therefore its terminal and ideal-finish bands - modelling choice.",
    "Repertoire procs are modelled on the song timer alone (80 % every 3 s from 42 s "
    "remaining down to 3 s, none in the final 3 s) and independent of DoT presence "
    "(sim/MECHANICS_CORRECTIONS.md item 1) - assumption, not verified in the client. "
    "The DoT independence is the job-table flag repertoire_independent_of_dots, which "
    "defaults to true; set it to false to make a proc require a DoT on the target.",
    "Base crit / DH are the merged report's top-10 event rates (25.366 % / 28.587 %) "
    "with the simulator's own buff uptimes deconvolved out, because those observed "
    "rates already contain Wanderer's Minuet, Army's Paeon and Battle Voice. They are "
    "still event rates rather than damage-weighted rates, and the parses' external "
    "raid buffs are not separable - flagged. Check the realized rates the fight and "
    "batch reports print against 25.366 % / 28.587 %.",
)

LIMITATIONS = (
    "aDPS includes external raid buffs; the single scalar absorbs them, so "
    "`potency_to_damage` is not a pure stat conversion factor.",
    "The 40 parses come from one encounter (Vamp Fatale) with real movement, targeting and "
    "downtime; the simulator fights a stationary dummy, so the scalar also absorbs the "
    "average uptime difference.",
    "Raw combat events are not on disk, so per-action counts can only be compared against "
    "the merged report's top-10 means, not against a per-parse distribution.",
    "The fit is a single multiplicative scalar. It cannot correct a rotation-shape error: "
    "check the per-action count table before trusting the DPS number.",
    "Kill-window bands are derived from `death_after_final_anchor_s`, which is a proxy for "
    "how much of the final burst landed before the boss died.",
    "The kill-window band table cannot discriminate between bands: `calibrate` sets no "
    "`kill_time_s`, so the simulator does not model the kill window at all and the sim "
    "DPS in that table varies only through the duration matching. Read it as a grouping "
    "of the parses, not as a test of the model.",
    "A one-parameter multiplicative fit constrains the DPS *level* only. It carries no "
    "information about rotation shape, and because the scalar is fitted as "
    "sum(aDPS) / sum(sim DPS) the mean residual is zero by construction. The honest "
    "check is the R^2 against the constant-mean null printed in the header, plus the "
    "per-action rate table.",
    "Bard auto attacks are ~7-10 % of real aDPS. `stats.auto_attack_dps` ships at 0.0, "
    "so they are not modelled and the single scalar absorbs them; that makes them scale "
    "with potency output rather than with time, which biases any experiment that moves "
    "GCD count or uptime without moving potency (the ping sweep, downtime windows, "
    "GCD_ONLY). Set `auto_attack_dps` to model them explicitly.",
)


@dataclass(frozen=True)
class Parse:
    """One row of `killtime.csv`: a single logged parse."""

    rank: int
    name: str
    adps: float
    rdps: float
    ndps: float
    duration_s: float
    death_after_s: float


def load_parses(csv_path: str | Path, *, min_parses: int = MIN_PARSES) -> list[Parse]:
    """Read `killtime.csv`. Raises CalibrationDataError on a missing column or short file.

    `min_parses` defaults to the 10 rows SPEC.md section 7.4 requires; tests that fit
    against a small fixture lower it explicitly.
    """
    path = Path(csv_path)
    if not path.exists():
        raise CalibrationDataError(f"parse CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or ())
        missing = [name for name in REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise CalibrationDataError(
                f"{path.name} is missing required column(s): {', '.join(missing)}")
        parses: list[Parse] = []
        for row in reader:
            try:
                parses.append(Parse(
                    rank=int(float(row["rank"])),
                    name=str(row["name"]),
                    adps=float(row["aDPS"]),
                    rdps=float(row["rDPS"]),
                    ndps=float(row["nDPS"]),
                    duration_s=float(row["duration_s"]),
                    death_after_s=float(row["death_after_final_anchor_s"]),
                ))
            except (TypeError, ValueError) as exc:
                raise CalibrationDataError(f"{path.name}: unreadable row {row!r}: {exc}") from exc
    if len(parses) < min_parses:
        raise CalibrationDataError(
            f"{path.name} has {len(parses)} parses, at least {min_parses} are required")
    return parses


def band_for(death_after_s: float) -> str:
    """Bucket a parse by seconds between the final party buff anchor and the kill.

    Bands are the merged report's: `<20`, `20-30`, `31-60`, `>60`. The 30-to-31 gap in the
    labels is closed by treating `30 < x <= 60` as the `31-60` band.
    """
    if death_after_s < 20.0:
        return "<20"
    if death_after_s <= 30.0:
        return "20-30"
    if death_after_s <= 60.0:
        return "31-60"
    return ">60"


def nearest(value: float, options: Sequence[float]) -> float:
    """The element of `options` closest to `value`; ties go to the smaller option."""
    if not options:
        raise CalibrationDataError("no simulated durations to match against")
    return min(sorted(options), key=lambda option: (abs(option - value), option))


def duration_bucket(duration_s: float) -> int:
    """`duration_s` rounded to the nearest 10 s, as the report's secondary bucketing."""
    return int(round(duration_s / 10.0) * 10)


def make_runner(base: FightConfig, *, workers: int | None = None,
                progress: Callable[[int, int], None] | None = None
                ) -> Callable[[float, Sequence[int]], BatchSummary]:
    """Return the default batch runner: one `run_batch` per simulated fight length."""

    def run(seconds: float, seeds: Sequence[int]) -> BatchSummary:
        # The kill time travels with the duration. `--kill-time` is one number but the
        # fit runs five fight lengths, so leaving it behind kills the dummy part-way
        # through the longer batches; `Simulation._target_hp_percent` then clamps HP at
        # zero, the engine stops acting, and the dead tail is still divided into DPS.
        config = replace(
            base,
            seconds=float(seconds),
            kill_time_s=(float(seconds) if base.kill_time_s is not None else None),
        )
        summary, _results = run_batch(config, seeds=seeds, workers=workers,
                                      progress=progress)
        return summary

    return run


def current_scalar_from_tables(repo_root: Path) -> float:
    """Read `potency_to_damage` from module A's `stats.json`, if it is available."""
    try:
        from .tables import Tables  # local import: module A may not have landed
    except ImportError as exc:  # pragma: no cover - only before module A lands
        raise CalibrationDataError(f"sim.tables is unavailable: {exc}") from exc
    tables = Tables.load(repo_root / "sim" / DATA_DIR_NAME)
    try:
        return float(tables.stats["potency_to_damage"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationDataError(f"stats.json has no usable potency_to_damage: {exc}") from exc


def _guard_output_dir(out_dir: Path, repo_root: Path) -> None:
    """Refuse to write anywhere inside `sim/data`, which belongs to module A."""
    data_dir = (repo_root / "sim" / DATA_DIR_NAME).resolve()
    resolved = out_dir.resolve()
    if resolved == data_dir or data_dir in resolved.parents:
        raise CalibrationDataError(f"refusing to write calibration output into {data_dir}")


def _relative_source(source: Path, repo_root: Path) -> str:
    """The CSV path as the report quotes it: repo-relative with forward slashes."""
    try:
        return source.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return source.as_posix()


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def calibrate(
    *,
    seeds: Sequence[int],
    repo_root: Path | None = None,
    csv_path: str | Path | None = None,
    out_path: str | Path | None = None,
    durations: Sequence[float] = DEFAULT_DURATIONS,
    base: FightConfig | None = None,
    current_scalar: float | None = None,
    runner: Callable[[float, Sequence[int]], BatchSummary] | None = None,
    workers: int | None = None,
    write_scalar: bool = False,
    write_files: bool = True,
    min_parses: int = MIN_PARSES,
) -> dict[str, Any]:
    """Fit `potency_to_damage` against the logged parses and write the calibration report.

    `runner` is injectable so the fit can be tested without running fights. It is called
    once per entry in `durations` and must return that batch's `BatchSummary`.
    Returns the calibration payload, the same object written to `calibration.json`.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    seed_list = [int(seed) for seed in seeds]
    if not seed_list:
        raise CalibrationDataError("calibration needs at least one seed")
    if not durations:
        raise CalibrationDataError("calibration needs at least one simulated duration")
    source = Path(csv_path) if csv_path is not None else root / DEFAULT_CSV
    parses = load_parses(source, min_parses=min_parses)
    md_path = Path(out_path) if out_path is not None else root / DEFAULT_OUT
    out_dir = md_path.parent
    _guard_output_dir(out_dir, root)

    fight = base if base is not None else FightConfig(seconds=float(durations[0]),
                                                      seed=seed_list[0])
    fight.validate()
    run = runner if runner is not None else make_runner(fight, workers=workers)
    if current_scalar is None:
        current_scalar = current_scalar_from_tables(root)
    current = float(current_scalar)

    sim_durations = [float(value) for value in durations]
    summaries: dict[float, BatchSummary] = {}
    for seconds in sim_durations:
        summaries[seconds] = run(seconds, seed_list)

    matched = [(parse, nearest(parse.duration_s, sim_durations)) for parse in parses]
    actual_total = sum(parse.adps for parse, _ in matched)
    sim_total = sum(summaries[duration].dps_mean for _, duration in matched)
    if sim_total <= 0.0:
        raise CalibrationDataError("simulated DPS is zero; cannot fit potency_to_damage")
    scale = actual_total / sim_total
    fitted = current * scale
    ls_numerator = sum(summaries[d].dps_mean * p.adps for p, d in matched)
    ls_denominator = sum(summaries[d].dps_mean ** 2 for _, d in matched)
    ls_ratio = (ls_numerator / ls_denominator) if ls_denominator > 0 else 0.0

    residuals = []
    for parse, duration in matched:
        sim_fitted = summaries[duration].dps_mean * scale
        err_pct = (sim_fitted - parse.adps) / parse.adps * 100.0 if parse.adps else 0.0
        residuals.append({
            "rank": parse.rank,
            "name": parse.name,
            "duration_s": round(parse.duration_s, 3),
            "duration_bucket_s": duration_bucket(parse.duration_s),
            "matched_sim_duration_s": duration,
            "band": band_for(parse.death_after_s),
            "actual_adps": round(parse.adps, 3),
            "sim_dps": round(sim_fitted, 3),
            "err_pct": round(err_pct, 4),
        })
    abs_errors = [abs(row["err_pct"]) for row in residuals]

    # A one-parameter multiplicative fit sets the level and nothing else, and the
    # scalar above is sum(aDPS) / sum(sim DPS), so the mean residual is zero by
    # construction. Compare it against the only null that matters: predicting every
    # parse with the mean aDPS. If the two error columns agree, the residual table is
    # measuring parse-to-parse scatter rather than the model.
    actual_values = [parse.adps for parse, _ in matched]
    fitted_values = [summaries[duration].dps_mean * scale for _, duration in matched]
    null_prediction = _mean(actual_values)
    null_abs_errors = [
        abs(null_prediction - actual) / actual * 100.0 if actual else 0.0
        for actual in actual_values
    ]
    ss_model = sum((fit - actual) ** 2 for fit, actual in zip(fitted_values, actual_values))
    ss_null = sum((null_prediction - actual) ** 2 for actual in actual_values)
    r_squared = (1.0 - ss_model / ss_null) if ss_null > 0 else 0.0

    by_duration = []
    for duration in sim_durations:
        group = [parse for parse, matched_duration in matched if matched_duration == duration]
        sim_fitted = summaries[duration].dps_mean * scale
        mean_actual = _mean([parse.adps for parse in group])
        ratio = (sim_fitted / mean_actual) if mean_actual else 0.0
        by_duration.append({
            "duration_s": duration,
            "parses": len(group),
            "mean_actual_adps": round(mean_actual, 3),
            "sim_dps_raw": round(summaries[duration].dps_mean, 3),
            "sim_dps_fitted": round(sim_fitted, 3),
            "ratio": round(ratio, 6),
            "err_pct": round((ratio - 1.0) * 100.0, 4) if mean_actual else 0.0,
        })

    by_band = []
    for band in BAND_ORDER:
        group = [(parse, duration) for parse, duration in matched
                 if band_for(parse.death_after_s) == band]
        if not group:
            by_band.append({"band": band, "parses": 0, "mean_actual_adps": 0.0,
                            "sim_dps_fitted": 0.0, "err_pct": 0.0})
            continue
        mean_actual = _mean([parse.adps for parse, _ in group])
        mean_sim = _mean([summaries[duration].dps_mean * scale for _, duration in group])
        err = (mean_sim - mean_actual) / mean_actual * 100.0 if mean_actual else 0.0
        by_band.append({
            "band": band,
            "parses": len(group),
            "mean_actual_adps": round(mean_actual, 3),
            "sim_dps_fitted": round(mean_sim, 3),
            "err_pct": round(err, 4),
        })

    top10 = [parse for parse in sorted(parses, key=lambda item: item.rank)[:10]]
    counts_duration = nearest(_mean([parse.duration_s for parse in top10]), sim_durations)
    counts_summary = summaries[counts_duration]
    minutes = counts_duration / 60.0 if counts_duration > 0 else 0.0

    def per_min(value: float) -> float:
        """Casts per minute, so a sim duration and the report's can be differenced."""
        return (float(value) / minutes) if minutes > 0 else 0.0

    def count_row(action: str, sim_rate: float, reference: float | None) -> dict[str, Any]:
        row: dict[str, Any] = {"action": action, "sim_per_min": round(sim_rate, 3)}
        if reference is None:
            row.update({"report_per_min": None, "delta": None, "delta_pct": None})
        else:
            delta = sim_rate - reference
            row.update({
                "report_per_min": round(reference, 3),
                "delta": round(delta, 3),
                "delta_pct": round(delta / reference * 100.0, 3) if reference else None,
            })
        return row

    count_keys = sorted(set(REPORT_RATES_PER_MIN) | {
        key for key, value in counts_summary.action_counts_mean.items() if value >= 1.0})
    count_rows = [
        count_row(key,
                  per_min(counts_summary.action_counts_mean.get(key, 0.0)),
                  REPORT_RATES_PER_MIN.get(key))
        for key in count_keys
    ]
    # Heartbreak Shot, Rain of Death and Bloodletter are one charge pool. The
    # simulator is single-target so it spends every charge on Heartbreak Shot;
    # only the combined rate is comparable with the parses.
    charge_sim = per_min(sum(float(counts_summary.action_counts_mean.get(key, 0.0))
                             for key in CHARGE_SPENDERS))
    count_rows.append(count_row("ChargeSpenders (combined)", charge_sim,
                                REPORT_CHARGE_SPENDERS_PER_MIN))
    count_rows.append(count_row(
        "All casts",
        per_min(sum(float(value) for value in counts_summary.action_counts_mean.values())),
        REPORT_CASTS_PER_MIN))

    payload: dict[str, Any] = {
        "generated": _datetime.datetime.now(_datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sim_version": report.__version__,
        "engine_version": report.ENGINE_VERSION,
        "seeds": seed_list,
        "seeds_label": report.format_seeds(seed_list),
        "pulse_ms": fight.pulse_ms,
        "ping_ms": fight.ping_ms,
        "source": _relative_source(source, root),
        "parse_count": len(parses),
        "duration_min_s": round(min(parse.duration_s for parse in parses), 3),
        "duration_max_s": round(max(parse.duration_s for parse in parses), 3),
        "sim_durations": sim_durations,
        "current_potency_to_damage": round(current, 6),
        "fitted_potency_to_damage": round(fitted, 6),
        "scale": round(scale, 6),
        "least_squares_ratio": round(ls_ratio * current, 6),
        "residual_mean_abs_pct": round(_mean(abs_errors), 4),
        "residual_max_pct": round(max(abs_errors) if abs_errors else 0.0, 4),
        "residual_stdev_pct": round(statistics.stdev(abs_errors) if len(abs_errors) > 1
                                    else 0.0, 4),
        "null_mean_abs_pct": round(_mean(null_abs_errors), 4),
        "null_max_pct": round(max(null_abs_errors) if null_abs_errors else 0.0, 4),
        "r_squared_vs_null": round(r_squared, 6),
        "actual_adps_mean": round(null_prediction, 3),
        "actual_adps_stdev": round(
            statistics.stdev(actual_values) if len(actual_values) > 1 else 0.0, 3),
        "sim_dps_fitted_stdev": round(
            statistics.stdev(fitted_values) if len(fitted_values) > 1 else 0.0, 3),
        "by_duration": by_duration,
        "by_band": by_band,
        "counts_duration_s": counts_duration,
        "counts": count_rows,
        "gcds_per_min_sim": round(counts_summary.gcd_mean / minutes, 3) if minutes else 0.0,
        "gcds_per_min_report": REPORT_GCDS_PER_MIN,
        "adps_top10_report": REPORT_ADPS_TOP10,
        # Realized crit / DH, so the stat model's base rates can be checked against the
        # 25.366 % / 28.587 % they were deconvolved from instead of being invisible.
        "crit_rate_sim": round(float(getattr(counts_summary, "crit_rate_mean", 0.0)), 6),
        "dh_rate_sim": round(float(getattr(counts_summary, "dh_rate_mean", 0.0)), 6),
        "crit_rate_report": 0.25366,
        "dh_rate_report": 0.28587,
        "residuals": residuals,
        "unverified": list(UNVERIFIED),
        "limitations": list(LIMITATIONS),
    }

    if write_files:
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown(payload), encoding="utf-8", newline="\n")
        write_json(out_dir / "calibration.json", payload)
        if write_scalar:
            write_json(out_dir / "stats.override.json",
                       {"potency_to_damage": payload["fitted_potency_to_damage"]})
    return payload


def _fmt(value: Any, spec: str = ".3f") -> str:
    """Format a number for a markdown cell; None becomes a dash."""
    if value is None:
        return "-"
    return format(float(value), spec)


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render `sim/output/calibration.md` in the fixed layout of SPEC.md section 7.4."""
    lines = ["# CielBard sim calibration", ""]
    lines.append(f"- generated: {payload['generated']}")
    lines.append(
        f"- sim {payload['sim_version']}, engine {payload['engine_version']}, "
        f"seeds {payload['seeds_label']}, pulse {report.format_number(payload['pulse_ms'])}ms, "
        f"ping {report.format_number(payload['ping_ms'])}ms")
    lines.append(
        f"- source: {payload['source']} ({payload['parse_count']} parses, "
        f"{_fmt(payload['duration_min_s'], '.1f')}-{_fmt(payload['duration_max_s'], '.1f')}s)")
    lines.append(
        f"- fitted potency_to_damage: {_fmt(payload['fitted_potency_to_damage'], '.4f')} "
        f"(from {_fmt(payload['current_potency_to_damage'], '.1f')}, "
        f"x{_fmt(payload['scale'], '.6f')})")
    lines.append(
        f"- least-squares ratio: {_fmt(payload['least_squares_ratio'], '.4f')}")
    lines.append(
        f"- residual: mean absolute error {_fmt(payload['residual_mean_abs_pct'], '.2f')}%, "
        f"max {_fmt(payload['residual_max_pct'], '.2f')}%")
    lines.append(
        f"- constant-mean null: mean absolute error "
        f"{_fmt(payload.get('null_mean_abs_pct'), '.2f')}%, "
        f"max {_fmt(payload.get('null_max_pct'), '.2f')}%; "
        f"model R^2 against it {_fmt(payload.get('r_squared_vs_null'), '.4f')}")
    lines.append(
        f"- spread: actual aDPS mean {_fmt(payload.get('actual_adps_mean'), '.1f')} "
        f"sd {_fmt(payload.get('actual_adps_stdev'), '.1f')}; "
        f"fitted sim DPS sd {_fmt(payload.get('sim_dps_fitted_stdev'), '.1f')}")
    lines.append(
        f"- realized rates: crit {float(payload.get('crit_rate_sim', 0.0)) * 100.0:.2f}% "
        f"(report {float(payload.get('crit_rate_report', 0.0)) * 100.0:.3f}%), "
        f"dh {float(payload.get('dh_rate_sim', 0.0)) * 100.0:.2f}% "
        f"(report {float(payload.get('dh_rate_report', 0.0)) * 100.0:.3f}%)")
    lines.append("")
    lines.append(
        "The scalar is fitted as sum(aDPS) / sum(sim DPS), so the mean residual is zero "
        "by construction and the residual tables below measure parse-to-parse scatter, "
        "not model accuracy. A one-parameter multiplicative fit constrains the DPS level "
        "only and carries no information about rotation shape: when the model's error "
        "columns match the constant-mean null's, the fit has explained nothing beyond the "
        "level. Judge the rotation from the per-action rate table instead.")
    lines.append("")

    lines.append("## Fit by fight length")
    lines.append("")
    lines.append(report.format_table(
        ["duration_s", "parses", "mean actual aDPS", "sim DPS (fitted)", "ratio", "err %"],
        [[_fmt(row["duration_s"], ".1f"), row["parses"], _fmt(row["mean_actual_adps"], ".1f"),
          _fmt(row["sim_dps_fitted"], ".1f"), _fmt(row["ratio"], ".4f"),
          _fmt(row["err_pct"], ".2f")] for row in payload["by_duration"]],
        "rrrrrr"))
    lines.append("")

    lines.append("## Fit by kill-window band")
    lines.append("")
    lines.append(
        "`calibrate` sets no `kill_time_s`, so the simulator does not model the kill "
        "window at all: the sim DPS in this table varies only through the duration "
        "matching above. The table groups the parses; its err % column cannot "
        "discriminate between bands.")
    lines.append("")
    lines.append(report.format_table(
        ["death after final anchor", "parses", "mean actual aDPS", "sim DPS (fitted)", "err %"],
        [[row["band"], row["parses"], _fmt(row["mean_actual_adps"], ".1f"),
          _fmt(row["sim_dps_fitted"], ".1f"), _fmt(row["err_pct"], ".2f")]
         for row in payload["by_band"]],
        "lrrrr"))
    lines.append("")

    lines.append(
        f"## Per-action counts at {_fmt(payload['counts_duration_s'], '.1f')}s, "
        f"as casts per minute")
    lines.append("")
    lines.append(
        "Casts per minute on both sides. The report's absolute counts were taken over "
        f"{_fmt(REPORT_COUNTS_DURATION_S, '.1f')}s fights, so differencing them against "
        "sim counts at another duration would carry that ratio silently. Heartbreak "
        "Shot, Rain of Death and Bloodletter share one charge pool and are only "
        "comparable as the combined row: the simulator is single-target, so it converts "
        "every charge into Heartbreak Shot.")
    lines.append("")
    lines.append(report.format_table(
        ["action", "sim /min", "top-10 /min (report)", "delta", "delta %"],
        [[row["action"], _fmt(row["sim_per_min"], ".3f"), _fmt(row["report_per_min"], ".3f"),
          _fmt(row["delta"], ".3f"), _fmt(row["delta_pct"], ".1f")]
         for row in payload["counts"]],
        "lrrrr"))
    lines.append("")
    lines.append(f"GCDs per minute: sim {_fmt(payload['gcds_per_min_sim'], '.3f')}, "
                 f"report {_fmt(payload['gcds_per_min_report'], '.3f')}.")
    lines.append("")

    lines.append("## Per-parse residuals")
    lines.append("")
    lines.append(report.format_table(
        ["rank", "duration_s", "actual aDPS", "sim DPS", "err %"],
        [[row["rank"], _fmt(row["duration_s"], ".1f"), _fmt(row["actual_adps"], ".1f"),
          _fmt(row["sim_dps"], ".1f"), _fmt(row["err_pct"], ".2f")]
         for row in payload["residuals"]],
        "rrrrr"))
    lines.append("")

    lines.append("## Unverified assumptions")
    lines.append("")
    for item in payload["unverified"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Known limitations")
    lines.append("")
    for item in payload["limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for `python -m sim.calibrate`."""
    parser = argparse.ArgumentParser(
        prog="sim.calibrate",
        description="Fit potency_to_damage against the logged Vamp Fatale parses.")
    add_fight_flags(parser, seconds=DEFAULT_DURATIONS[1])
    parser.add_argument("--seeds", default="1-25", help="seed list, e.g. 1-25 or 1,5,9")
    parser.add_argument("--workers", type=int, default=None, help="process count per batch")
    parser.add_argument("--out", dest="out_path", default=None,
                        help="markdown output path (calibration.json lands beside it)")
    parser.add_argument("--csv", dest="csv_path", default=None, help="override the parse CSV")
    parser.add_argument("--durations", default=None,
                        help="comma-separated simulated fight lengths")
    parser.add_argument("--current", type=float, default=None,
                        help="current potency_to_damage; default reads sim/data/stats.json")
    parser.add_argument("--write-scalar", action="store_true", dest="write_scalar",
                        help="also write sim/output/stats.override.json")
    parser.add_argument("--quiet", action="store_true", help="suppress the stdout summary")
    parser.add_argument("--trace", action="store_true", help="print tracebacks on error")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `python -m sim.calibrate`. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        seeds = parse_seeds(args.seeds)
        base = config_from_args(args, seed=seeds[0])
        durations = DEFAULT_DURATIONS
        if args.durations:
            durations = tuple(float(chunk) for chunk in args.durations.split(",")
                              if chunk.strip())
    except (SimConfigError, ValueError) as exc:
        return fail("sim.calibrate", exc, EXIT_CONFIG, show_traceback=args.trace)
    try:
        payload = calibrate(
            seeds=seeds,
            csv_path=args.csv_path,
            out_path=args.out_path,
            durations=durations,
            base=base,
            current_scalar=args.current,
            workers=args.workers,
            write_scalar=args.write_scalar,
        )
    except CalibrationDataError as exc:
        return fail("sim.calibrate", exc, EXIT_CONFIG, show_traceback=args.trace)
    except (SimulationError, LuaBridgeError) as exc:
        return fail("sim.calibrate", exc, EXIT_ENGINE, show_traceback=args.trace)
    except SimConfigError as exc:
        return fail("sim.calibrate", exc, EXIT_CONFIG, show_traceback=args.trace)
    if not args.quiet:
        out_dir = Path(args.out_path).parent if args.out_path else REPO_ROOT / DEFAULT_OUT.parent
        sys.stdout.write(report.header_line() + "\n")
        sys.stdout.write(report.labelled("fit", "   ".join([
            f"potency_to_damage {payload['fitted_potency_to_damage']:.4f}",
            f"from {payload['current_potency_to_damage']:.1f}",
            f"x{payload['scale']:.6f}",
        ])) + "\n")
        sys.stdout.write(report.labelled("residual", "   ".join([
            f"mean {payload['residual_mean_abs_pct']:.2f}%",
            f"max {payload['residual_max_pct']:.2f}%",
            f"parses {payload['parse_count']}",
        ])) + "\n")
        sys.stdout.write(report.labelled("wrote", str(out_dir)) + "\n")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
