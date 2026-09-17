"""Cartesian parameter sweeps over engine config and fight settings.

    python -m sim.sweep --axis apexBurstGauge=60,70,80,90 --axis maxWeaves=1,2 \
        --seeds 1-25 --csv sim/output/sweep.csv

Every sweep point is a batch over the same seed list, so points are comparable.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import report
from .batch import BatchSummary, parse_seeds, run_batch
from .core import SimulationError
from .run import EXIT_CONFIG, EXIT_ENGINE, EXIT_OK, add_fight_flags, config_from_args, fail
from .run import parse_assignment, parse_value
from .runconfig import FightConfig, SimConfigError

try:  # pragma: no cover - only while module B has not landed
    from .client import LuaBridgeError
except ImportError:  # pragma: no cover
    class LuaBridgeError(RuntimeError):  # type: ignore[no-redef]
        """Placeholder used when `sim.client` is not importable."""

RESERVED_AXES = ("ping_ms", "pulse_ms", "seconds")
"""Axis names that change the `FightConfig` itself rather than the engine config."""

SweepPoint = tuple[dict[str, Any], BatchSummary]


def apply_point(base: FightConfig, point: Mapping[str, Any]) -> FightConfig:
    """Return a copy of `base` with one sweep point applied.

    Reserved axis names map onto `FightConfig` fields; every other name is an engine
    configuration path handed to `CielBardEngine.Init`.
    """
    engine = dict(base.engine_config)
    fields: dict[str, Any] = {}
    for key, value in point.items():
        if key == "seconds":
            # The kill time travels with the duration. Leaving it behind would let the
            # dummy die part-way through the longer points, and the dead tail is still
            # divided into DPS (`Simulation._target_hp_percent` clamps HP at 0).
            fields["seconds"] = float(value)
            if base.kill_time_s is not None:
                fields["kill_time_s"] = float(value)
        elif key == "ping_ms":
            fields["ping_ms"] = float(value)
        elif key == "pulse_ms":
            fields["pulse_ms"] = int(value)
        else:
            engine[key] = value
    return replace(base, engine_config=engine, **fields)


def expand_points(axes: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of `axes`, keys sorted, values in input order.

    The first sorted key varies slowest, so the output order is stable across runs.
    Raises SimConfigError when an axis has no values.
    """
    keys = sorted(axes)
    for key in keys:
        if not list(axes[key]):
            raise SimConfigError(f"axis {key!r} has no values")
    if not keys:
        return [{}]
    combos = itertools.product(*[list(axes[key]) for key in keys])
    return [dict(zip(keys, combo)) for combo in combos]


def sweep(
    base: FightConfig,
    axes: Mapping[str, Sequence[Any]],
    *,
    seeds: Sequence[int],
    workers: int | None = None,
) -> list[SweepPoint]:
    """Cartesian product over `axes`, a batch of `seeds` per point.

    Axis keys are engine config paths (`"apexBurstGauge"`, `"abilities.Barrage"`,
    `"maxWeaves"`) or the reserved names `"ping_ms"`, `"pulse_ms"`, `"seconds"`.
    Points are evaluated in sorted-key, input-order fashion so the output list order is
    deterministic. Raises SimConfigError for an empty axis.
    """
    points = expand_points(axes)
    out: list[SweepPoint] = []
    for point in points:
        config = apply_point(base, point)
        summary, _results = run_batch(config, seeds=seeds, workers=workers)
        out.append((point, summary))
    return out


def sweep_columns(points: Sequence[SweepPoint]) -> tuple[list[str], list[str]]:
    """Return `(axis_names, action_keys)` for the CSV, both sorted."""
    axis_names: list[str] = sorted({key for point, _ in points for key in point})
    action_keys = sorted({key for _, summary in points
                          for key in summary.action_counts_mean})
    return axis_names, action_keys


def write_csv(points: Sequence[SweepPoint], path: str | Path) -> Path:
    """Write one row per sweep point. Columns: axes, n, dps_mean, dps_stdev, gcd_mean,
    then `count_<key>` for every action seen at any point (missing counts are 0)."""
    axis_names, action_keys = sweep_columns(points)
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    header = list(axis_names) + ["n", "dps_mean", "dps_stdev", "gcd_mean"]
    header += [f"count_{key}" for key in action_keys]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for point, summary in points:
            row: list[Any] = [point.get(name, "") for name in axis_names]
            row += [summary.n, f"{summary.dps_mean:.6f}", f"{summary.dps_stdev:.6f}",
                    f"{summary.gcd_mean:.6f}"]
            row += [f"{summary.action_counts_mean.get(key, 0.0):.6f}" for key in action_keys]
            writer.writerow(row)
    return target


def format_sweep(points: Sequence[SweepPoint]) -> str:
    """A markdown table of the sweep, best mean DPS first.

    Rows are sorted by `dps_mean` descending, as `sim/README.md` documents, so the
    first row is the winning point rather than whichever value happened to be typed
    first. `dps_sem` is `dps_stdev / sqrt(n)` and `delta` is the gap to the best row:
    a point whose `delta` is inside a couple of `dps_sem` is inside the noise floor
    and is not a real difference. `write_csv` keeps the deterministic evaluation
    order instead, so sweep CSVs stay diffable.
    """
    axis_names, _ = sweep_columns(points)
    headers = list(axis_names) + ["n", "dps_mean", "dps_sem", "dps_stdev", "gcd_mean",
                                  "delta", "delta %"]
    ordered = sorted(points, key=lambda pair: -pair[1].dps_mean)
    best = ordered[0][1].dps_mean if ordered else 0.0
    rows = []
    for point, summary in ordered:
        sem = summary.dps_stdev / math.sqrt(summary.n) if summary.n > 0 else 0.0
        delta = summary.dps_mean - best
        delta_pct = (delta / best * 100.0) if best else 0.0
        row: list[Any] = [point.get(name, "") for name in axis_names]
        row += [summary.n, f"{summary.dps_mean:.1f}", f"{sem:.1f}",
                f"{summary.dps_stdev:.1f}", f"{summary.gcd_mean:.2f}",
                f"{delta:+.1f}", f"{delta_pct:+.2f}"]
        rows.append(row)
    aligns = "l" * len(axis_names) + "rrrrrrr"
    return report.format_table(headers, rows, aligns)


def parse_axis(text: str) -> tuple[str, list[Any]]:
    """Parse `--axis KEY=v1,v2,v3` into a name and its parsed value list."""
    key, raw = parse_assignment(text)
    values = [parse_value(chunk) for chunk in raw.split(",") if chunk.strip() != ""]
    if not values:
        raise SimConfigError(f"axis {key!r} has no values")
    return key, values


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for `python -m sim.sweep`."""
    parser = argparse.ArgumentParser(prog="sim.sweep",
                                     description="Sweep engine parameters over a seed batch.")
    add_fight_flags(parser)
    parser.add_argument("--axis", action="append", dest="axes", metavar="KEY=V1,V2",
                        default=[], help="repeatable sweep axis")
    parser.add_argument("--seeds", default="1-10", help="seed list, e.g. 1-25 or 1,5,9")
    parser.add_argument("--workers", type=int, default=None, help="process count per batch")
    parser.add_argument("--csv", dest="csv_path", metavar="PATH", help="write the sweep CSV")
    parser.add_argument("--quiet", action="store_true", help="suppress the table")
    parser.add_argument("--trace", action="store_true", help="print tracebacks on error")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `python -m sim.sweep`. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        seeds = parse_seeds(args.seeds)
        base = config_from_args(args, seed=seeds[0])
        axes: dict[str, list[Any]] = {}
        for item in args.axes:
            key, values = parse_axis(item)
            axes[key] = values
    except SimConfigError as exc:
        return fail("sim.sweep", exc, EXIT_CONFIG, show_traceback=args.trace)
    try:
        points = sweep(base, axes, seeds=seeds, workers=args.workers)
    except (SimulationError, LuaBridgeError) as exc:
        return fail("sim.sweep", exc, EXIT_ENGINE, show_traceback=args.trace)
    except SimConfigError as exc:
        return fail("sim.sweep", exc, EXIT_CONFIG, show_traceback=args.trace)
    if args.csv_path:
        write_csv(points, args.csv_path)
    if not args.quiet:
        sys.stdout.write(report.header_line() + "\n")
        sys.stdout.write(format_sweep(points) + "\n")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
