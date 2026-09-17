"""Multi-seed batch runner and its aggregate statistics.

    python -m sim.batch --seconds 510 --seeds 1-200 --workers 8

One fight per seed is run (optionally across a process pool, because a LuaRuntime
cannot cross a process boundary), then aggregated into a `BatchSummary`.
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence

from . import report
from .core import FightResult, SimulationError, run_fight
from .run import EXIT_CONFIG, EXIT_ENGINE, EXIT_OK, add_fight_flags, config_from_args, fail
from .run import write_json
from .runconfig import FightConfig, SimConfigError

try:  # pragma: no cover - only while module B has not landed
    from .client import LuaBridgeError
except ImportError:  # pragma: no cover
    class LuaBridgeError(RuntimeError):  # type: ignore[no-redef]
        """Placeholder used when `sim.client` is not importable."""


@dataclass(frozen=True)
class BatchSummary:
    """Aggregate of one fight per seed. Every float is deterministic given the seeds."""

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
    # Realized rates, averaged over the batch: what the stat model actually produced,
    # against the parse rates its `crit_rate` / `dh_rate` inputs were read from.
    crit_rate_mean: float = 0.0
    dh_rate_mean: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form with floats rounded to 6 decimals for byte stability."""
        return {
            "n": self.n,
            "seconds": round(self.seconds, 6),
            "dps_mean": round(self.dps_mean, 6),
            "dps_stdev": round(self.dps_stdev, 6),
            "dps_p05": round(self.dps_p05, 6),
            "dps_p50": round(self.dps_p50, 6),
            "dps_p95": round(self.dps_p95, 6),
            "gcd_mean": round(self.gcd_mean, 6),
            "action_counts_mean": {key: round(value, 6)
                                   for key, value in sorted(self.action_counts_mean.items())},
            "dot_uptime_mean": {key: round(value, 6)
                                for key, value in self.dot_uptime_mean.items()},
            "rejections_total": self.rejections_total,
            "crit_rate_mean": round(self.crit_rate_mean, 6),
            "dh_rate_mean": round(self.dh_rate_mean, 6),
        }


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile, `q` in [0, 1]. Empty input returns 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = min(max(q, 0.0), 1.0) * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[low])
    weight = position - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _mean_of_maps(maps: Sequence[Mapping[str, float]], n: int,
                  ordered_keys: Sequence[str]) -> dict[str, float]:
    """Mean per key over `n` fights, treating a missing key as zero."""
    totals: dict[str, float] = {key: 0.0 for key in ordered_keys}
    for mapping in maps:
        for key, value in mapping.items():
            totals[key] = totals.get(key, 0.0) + float(value)
    return {key: totals[key] / n for key in totals}


def summarize(results: Sequence[FightResult], *, seconds: float | None = None) -> BatchSummary:
    """Aggregate a list of fight results into a `BatchSummary`."""
    if not results:
        raise SimConfigError("cannot summarize an empty batch")
    n = len(results)
    dps = [result.dps for result in results]
    count_keys: list[str] = []
    for result in results:
        for key in result.action_counts:
            if key not in count_keys:
                count_keys.append(key)
    dot_keys: list[str] = []
    for result in results:
        for key in result.dot_uptime:
            if key not in dot_keys:
                dot_keys.append(key)
    counts_mean = _mean_of_maps([result.action_counts for result in results], n,
                                sorted(count_keys))
    dot_mean = _mean_of_maps([result.dot_uptime for result in results], n, dot_keys)
    return BatchSummary(
        n=n,
        seconds=float(seconds if seconds is not None else results[0].duration_s),
        dps_mean=statistics.fmean(dps),
        dps_stdev=statistics.stdev(dps) if n > 1 else 0.0,
        dps_p05=percentile(dps, 0.05),
        dps_p50=percentile(dps, 0.50),
        dps_p95=percentile(dps, 0.95),
        gcd_mean=statistics.fmean([float(result.gcd_count) for result in results]),
        action_counts_mean={key: counts_mean[key] for key in sorted(counts_mean)},
        dot_uptime_mean={key: dot_mean[key] for key in dot_keys},
        rejections_total=sum(len(result.rejections) + len(result.client_rejections)
                             for result in results),
        crit_rate_mean=statistics.fmean(
            [float(getattr(result, "crit_rate", 0.0)) for result in results]),
        dh_rate_mean=statistics.fmean(
            [float(getattr(result, "dh_rate", 0.0)) for result in results]),
    )


def _run_seed(config: FightConfig) -> FightResult:
    """Process-pool worker: run one fight. Module level so it stays picklable."""
    return run_fight(config)


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
    `FakeClient` - a LuaRuntime cannot cross a process boundary.
    """
    seed_list = [int(seed) for seed in seeds]
    if not seed_list:
        raise SimConfigError("run_batch needs at least one seed")
    base.validate()
    configs = [replace(base, seed=seed) for seed in seed_list]
    total = len(configs)
    chosen = workers if workers is not None else min(os.cpu_count() or 1, total)
    by_index: dict[int, FightResult] = {}
    if chosen <= 1:
        for index, config in enumerate(configs):
            by_index[index] = run_fight(config)
            if progress is not None:
                progress(index + 1, total)
    else:
        with ProcessPoolExecutor(max_workers=chosen) as pool:
            futures = {pool.submit(_run_seed, config): index
                       for index, config in enumerate(configs)}
            done = 0
            for future in as_completed(futures):
                by_index[futures[future]] = future.result()
                done += 1
                if progress is not None:
                    progress(done, total)
    results = [by_index[index] for index in range(total)]
    return summarize(results, seconds=base.seconds), results


def parse_seeds(text: str) -> list[int]:
    """Parse `1-200`, `1,5,9` or a mix into an ordered, de-duplicated seed list."""
    seeds: list[int] = []
    for chunk in str(text).split(","):
        item = chunk.strip()
        if not item:
            continue
        if "-" in item[1:]:
            head, _, tail = item[1:].partition("-")
            low_text, high_text = item[0] + head, tail
            try:
                low, high = int(low_text), int(high_text)
            except ValueError as exc:
                raise SimConfigError(f"bad seed range {item!r}: {exc}") from exc
            if high < low:
                raise SimConfigError(f"seed range {item!r} runs backwards")
            seeds.extend(range(low, high + 1))
        else:
            try:
                seeds.append(int(item))
            except ValueError as exc:
                raise SimConfigError(f"bad seed {item!r}: {exc}") from exc
    if not seeds:
        raise SimConfigError("no seeds given")
    ordered: list[int] = []
    seen: set[int] = set()
    for seed in seeds:
        if seed not in seen:
            seen.add(seed)
            ordered.append(seed)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for `python -m sim.batch`."""
    parser = argparse.ArgumentParser(prog="sim.batch",
                                     description="Run one simulated fight per seed.")
    add_fight_flags(parser)
    parser.add_argument("--seeds", default="1-10", help="seed list, e.g. 1-200 or 1,5,9")
    parser.add_argument("--workers", type=int, default=None,
                        help="process count; 1 runs in-process")
    parser.add_argument("--json", dest="json_path", metavar="PATH",
                        help="write the BatchSummary as JSON")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary")
    parser.add_argument("--trace", action="store_true", help="print tracebacks on error")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `python -m sim.batch`. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        seeds = parse_seeds(args.seeds)
        base = config_from_args(args, seed=seeds[0])
    except SimConfigError as exc:
        return fail("sim.batch", exc, EXIT_CONFIG, show_traceback=args.trace)
    try:
        summary, _results = run_batch(base, seeds=seeds, workers=args.workers)
    except (SimulationError, LuaBridgeError) as exc:
        return fail("sim.batch", exc, EXIT_ENGINE, show_traceback=args.trace)
    except SimConfigError as exc:
        return fail("sim.batch", exc, EXIT_CONFIG, show_traceback=args.trace)
    if not args.quiet:
        sys.stdout.write(report.format_batch(summary) + "\n")
    if args.json_path:
        write_json(args.json_path, summary.to_dict())
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
