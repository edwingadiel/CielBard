"""Formatting for every human-readable surface of the simulator.

This module is pure: it returns strings and performs no I/O. Every stdout layout the
CLI promises (SPEC.md section 7.1) is produced here so that the runners stay free of
formatting decisions and the layout can be unit-tested without running a fight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence

try:  # pragma: no cover - exercised only while module A has not landed
    from . import ENGINE_VERSION, __version__
except ImportError:  # the package is still a namespace package
    __version__ = "1.0.0"
    ENGINE_VERSION = "0.5.2"

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a hard import cycle
    from .batch import BatchSummary
    from .core import FightResult

LABEL_WIDTH = 8
"""Width of the left-hand label column; the value column starts at LABEL_WIDTH + 1."""

COUNTS_INDENT = LABEL_WIDTH + 1
COUNTS_WIDTH = 100


def header_line() -> str:
    """Line 1 of every report: the simulator version and the engine it drives."""
    return f"CielBard sim {__version__} | engine {ENGINE_VERSION}"


def labelled(label: str, content: str) -> str:
    """One `label` + `content` line with the label left-aligned in the 8-char column."""
    return f"{label:<{LABEL_WIDTH}} {content}".rstrip()


def _num(value: Any) -> str:
    """Render a number without a pointless trailing `.0` (used for ping, pulse, ...)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


format_number = _num
"""Public alias of the compact number formatter, shared with `sim.calibrate`."""


def _count_value(value: Any) -> str:
    """Integer counts print bare; means (floats) print with two decimals."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return f"{float(value):.2f}"


def format_counts(counts: Mapping[str, float], *, width: int = COUNTS_WIDTH,
                  indent: int = COUNTS_INDENT) -> str:
    """Wrap `key value` pairs, sorted by key, into an indented block.

    Pairs are separated by two spaces and wrapped at `width` columns. The first line
    assumes the caller already consumed `indent` columns (the label column), every
    continuation line is prefixed with `indent` spaces. Returns "none" when empty.
    """
    pairs = [f"{key} {_count_value(counts[key])}" for key in sorted(counts)]
    if not pairs:
        return "none"
    lines: list[str] = []
    current = ""
    budget = max(width - indent, 20)
    for pair in pairs:
        candidate = pair if not current else f"{current}  {pair}"
        if len(candidate) > budget and current:
            lines.append(current)
            current = pair
        else:
            current = candidate
    lines.append(current)
    pad = " " * indent
    return ("\n" + pad).join(lines)


def _pairs(items: Sequence[tuple[str, str]]) -> str:
    """Join `name value` groups with the three-space separator the layout uses."""
    return "   ".join(f"{name} {value}" for name, value in items) if items else "none"


def average_gcd_s(result: "FightResult") -> float:
    """Mean GCD recast actually observed: rolling seconds divided by GCD count.

    Derived from the result rather than read from the tables so that this module holds
    no mechanic constants (SPEC.md section 0.1 rule 3).
    """
    if result.gcd_count <= 0:
        return 0.0
    return (result.duration_s * result.gcd_uptime) / result.gcd_count


def rejection_count(result: "FightResult") -> int:
    """Core rejections plus client-side refusals: the number the `uptime` line shows."""
    return len(result.rejections) + len(result.client_rejections)


def format_fight(result: "FightResult") -> str:
    """The fixed single-fight summary of SPEC.md section 7.1, without a trailing newline."""
    config = result.config
    duration = result.duration_s
    minutes = duration / 60.0 if duration > 0 else 0.0
    per_min = result.gcd_count / minutes if minutes > 0 else 0.0
    weaves = result.ogcd_count / result.gcd_count if result.gcd_count else 0.0
    lines = [header_line()]
    lines.append(labelled("fight", "  ".join([
        f"{duration:.1f}s",
        f"seed={config.seed}",
        f"ping={_num(config.ping_ms)}ms",
        f"pulse={_num(config.pulse_ms)}ms",
        f"gcd={average_gcd_s(result):.2f}s",
        f"enemies={config.enemies}"
        + (f"@{config.enemy_spread_yalms:g}y" if config.enemies > 1 else ""),
    ])))
    lines.append(labelled("damage", "   ".join([
        f"{result.total_damage:.0f}",
        f"dps {result.dps:.1f}",
        f"potency {result.total_potency} ({result.potency_per_second:.1f}/s)",
    ])))
    lines.append(labelled("gcds", "   ".join([
        f"{result.gcd_count} ({per_min:.2f}/min)",
        f"ogcds {result.ogcd_count}",
        f"weaves/gcd {weaves:.2f}",
    ])))
    lines.append(labelled("uptime", "   ".join([
        f"gcd {result.gcd_uptime * 100.0:.1f}%",
        f"clipped {result.clipped_s:.2f}s",
        f"rejections {rejection_count(result)}",
    ])))
    lines.append(labelled("dots", _pairs(
        [(key, f"{value * 100.0:.1f}%") for key, value in result.dot_uptime.items()])))
    songs: list[tuple[str, str]] = []
    for key, seconds in result.song_seconds.items():
        casts = result.song_casts.get(key, 0)
        # `song_seconds` is the total; the line shows seconds per cast so it can be read
        # against the merged report's per-song allocation (about 43.8 / 42.3 / 34.9 s).
        per_cast = seconds / casts if casts else seconds
        songs.append((key, f"{casts}x {per_cast:.1f}s"))
    for key, casts in result.song_casts.items():
        if key not in result.song_seconds:
            songs.append((key, f"{casts}x 0.0s"))
    lines.append(labelled("songs", _pairs(songs)))
    wasted = result.wasted
    lines.append(labelled("waste", _pairs([
        ("repertoire", _num(wasted.get("repertoire_overcap", 0))),
        ("soulvoice", _num(wasted.get("soul_voice_overcap", 0))),
        ("charges", _num(wasted.get("charge_overcap", 0))),
        ("barrage", _num(wasted.get("barrage_expired", 0))),
    ])))
    counts = {key: value for key, value in result.action_counts.items() if value >= 1}
    lines.append(labelled("counts", format_counts(counts)))
    # Realized crit / direct-hit rates. The stat model's base rates were read off a
    # parse report, so the number to check them against is this one, not the input.
    events = int(getattr(result, "damage_event_count", 0) or len(result.damage))
    if events:
        lines.append(labelled("rates", "   ".join([
            f"crit {float(getattr(result, 'crit_rate', 0.0)) * 100.0:.2f}%",
            f"dh {float(getattr(result, 'dh_rate', 0.0)) * 100.0:.2f}%",
            f"events {events}",
        ])))
    return "\n".join(lines)


def format_trace(result: "FightResult") -> str:
    """One `trace` line per cast: time, ability key and the engine's decision string."""
    lines = []
    for cast in result.casts:
        key = cast.key or f"id:{cast.action_id}"
        lines.append(labelled("trace", f"{cast.t_s:7.3f}  {key}  {cast.decision}"))
    return "\n".join(lines)


def format_seeds(seeds: Sequence[int]) -> str:
    """Compress a seed list to `1-25` / `1,5,9` form for report headers."""
    ordered = sorted(set(int(seed) for seed in seeds))
    if not ordered:
        return "none"
    runs: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for seed in ordered[1:]:
        if seed == previous + 1:
            previous = seed
            continue
        runs.append((start, previous))
        start = previous = seed
    runs.append((start, previous))
    return ",".join(str(lo) if lo == hi else f"{lo}-{hi}" for lo, hi in runs)


def format_batch(summary: "BatchSummary") -> str:
    """The multi-seed summary, in the same label/column style as `format_fight`."""
    lines = [header_line()]
    lines.append(labelled("batch", "  ".join([
        f"{summary.n} seeds",
        f"{summary.seconds:.1f}s",
    ])))
    lines.append(labelled("dps", "   ".join([
        f"mean {summary.dps_mean:.1f}",
        f"sd {summary.dps_stdev:.1f}",
        f"p05 {summary.dps_p05:.1f}",
        f"p50 {summary.dps_p50:.1f}",
        f"p95 {summary.dps_p95:.1f}",
    ])))
    lines.append(labelled("gcds", "   ".join([
        f"mean {summary.gcd_mean:.2f}",
        f"rejections {summary.rejections_total}",
    ])))
    lines.append(labelled("dots", _pairs(
        [(key, f"{value * 100.0:.1f}%") for key, value in summary.dot_uptime_mean.items()])))
    counts = {key: value for key, value in summary.action_counts_mean.items() if value > 0}
    lines.append(labelled("counts", format_counts(counts)))
    # Realized crit / direct-hit rates, so the stat model's base rates can be read
    # against the parse rates they were taken from instead of being invisible.
    lines.append(labelled("rates", "   ".join([
        f"crit {float(getattr(summary, 'crit_rate_mean', 0.0)) * 100.0:.2f}%",
        f"dh {float(getattr(summary, 'dh_rate_mean', 0.0)) * 100.0:.2f}%",
    ])))
    return "\n".join(lines)


def format_table(headers: Sequence[str], rows: Sequence[Sequence[Any]],
                 aligns: str = "") -> str:
    """GitHub-flavoured markdown table. `aligns` is one char per column: l, c or r."""
    columns = len(headers)
    spec = (aligns + "l" * columns)[:columns]
    separators = []
    for char in spec:
        if char == "r":
            separators.append("---:")
        elif char == "c":
            separators.append(":---:")
        else:
            separators.append("---")
    lines = ["| " + " | ".join(str(head) for head in headers) + " |",
             "|" + "|".join(separators) + "|"]
    for row in rows:
        cells = [str(cell) for cell in row]
        cells += [""] * (columns - len(cells))
        lines.append("| " + " | ".join(cells[:columns]) + " |")
    return "\n".join(lines)
