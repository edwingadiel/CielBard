"""Single-fight runner and command line entry point.

    python -m sim.run --seconds 510 --seed 1 --ping 0

Exit codes: 0 ok, 2 configuration or CLI error, 3 engine/simulation failure,
4 a `--strict` violation (any rejection or engine configuration warning).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import report
from .core import SimulationError, run_fight
from .runconfig import DowntimeWindow, FightConfig, SimConfigError

try:  # pragma: no cover - only while module B has not landed
    from .client import LuaBridgeError
except ImportError:  # pragma: no cover
    class LuaBridgeError(RuntimeError):  # type: ignore[no-redef]
        """Placeholder used when `sim.client` is not importable."""

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_ENGINE = 3
EXIT_STRICT = 4

DEFAULT_SECONDS = 510.0
DEFAULT_SEED = 1
DEFAULT_PULSE_MS = 30


def parse_value(text: str) -> Any:
    """Parse a `--set` / axis value as bool, int, float or string, in that order."""
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("nil", "none", "null"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_assignment(text: str) -> tuple[str, str]:
    """Split `KEY=VALUE` into its two halves. Raises SimConfigError when malformed."""
    if "=" not in text:
        raise SimConfigError(f"expected KEY=VALUE, got {text!r}")
    key, _, value = text.partition("=")
    key = key.strip()
    if not key:
        raise SimConfigError(f"empty key in {text!r}")
    return key, value


def parse_downtime(text: str) -> DowntimeWindow:
    """Parse a `START:END` downtime window in seconds. Raises SimConfigError."""
    if ":" not in text:
        raise SimConfigError(f"expected downtime as START:END, got {text!r}")
    start_text, _, end_text = text.partition(":")
    try:
        start, end = float(start_text), float(end_text)
    except ValueError as exc:
        raise SimConfigError(f"downtime {text!r} is not a pair of numbers: {exc}") from exc
    return DowntimeWindow(start_s=start, end_s=end)


def parse_overrides(assignments: Sequence[str] | None) -> dict[str, Any]:
    """Turn repeated `--set KEY=VALUE` flags into an engine override mapping."""
    overrides: dict[str, Any] = {}
    for item in assignments or ():
        key, value = parse_assignment(item)
        overrides[key] = parse_value(value)
    return overrides


def parse_stat_overrides(assignments: Sequence[str] | None) -> dict[str, float]:
    """Turn repeated `--stat KEY=VALUE` flags into a `stats.json` override mapping."""
    overrides: dict[str, float] = {}
    for item in assignments or ():
        key, value = parse_assignment(item)
        try:
            overrides[key] = float(value)
        except ValueError as exc:
            raise SimConfigError(f"--stat {key} needs a number, got {value!r}") from exc
    return overrides


def add_fight_flags(parser: argparse.ArgumentParser, *, seconds: float = DEFAULT_SECONDS) -> None:
    """Add the flags that describe one fight; shared by run, batch, sweep and calibrate."""
    parser.add_argument("--seconds", type=float, default=seconds,
                        help="fight length in seconds")
    parser.add_argument("--kill-time", dest="kill_time", type=float, default=None,
                        metavar="SECONDS",
                        help="linear death time of the dummy, feeding the engine's TTK "
                             "estimator; omit for a striking dummy that never dies")
    parser.add_argument("--ping", type=float, default=0.0,
                        help="milliseconds added to every animation lock")
    parser.add_argument("--pulse", type=int, default=DEFAULT_PULSE_MS,
                        help="pulse period in ms, also written into the engine config")
    parser.add_argument("--enemies", type=int, default=1,
                        help="number of targets in range of the primary")
    parser.add_argument("--downtime", action="append", metavar="A:B", default=[],
                        help="repeatable downtime window in seconds")
    parser.add_argument("--set", action="append", dest="engine_set", metavar="KEY=VALUE",
                        default=[], help="repeatable engine config override, dotted keys allowed")
    parser.add_argument("--stat", action="append", dest="stat_set", metavar="KEY=VALUE",
                        default=[], help="repeatable stats.json override")
    parser.add_argument("--potion", action="store_true", help="enable usePotion")
    parser.add_argument("--deterministic", action="store_true",
                        help="expected-value damage: every hit takes its closed-form "
                             "expectation, so no crit, direct-hit or variance "
                             "randomness is drawn (proc RNG still varies the rotation)")


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for `python -m sim.run`."""
    parser = argparse.ArgumentParser(prog="sim.run",
                                     description="Run one simulated CielBard fight.")
    add_fight_flags(parser)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed")
    parser.add_argument("--json", dest="json_path", metavar="PATH",
                        help="write FightResult.to_dict(include_events=True) to PATH")
    parser.add_argument("--trace", action="store_true",
                        help="print one line per cast (and full tracebacks on error)")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary")
    parser.add_argument("--strict", action="store_true",
                        help="exit 4 when any rejection or engine warning occurred")
    return parser


def config_from_args(args: argparse.Namespace, *, seed: int | None = None) -> FightConfig:
    """Build a `FightConfig` from parsed CLI arguments. Raises SimConfigError."""
    downtime = tuple(parse_downtime(item) for item in getattr(args, "downtime", ()) or ())
    config = FightConfig(
        seconds=args.seconds,
        seed=int(seed if seed is not None else getattr(args, "seed", DEFAULT_SEED)),
        ping_ms=args.ping,
        pulse_ms=args.pulse,
        engine_config=parse_overrides(getattr(args, "engine_set", ())),
        downtime=downtime,
        enemies=args.enemies,
        stat_overrides=parse_stat_overrides(getattr(args, "stat_set", ())),
        use_potion=bool(getattr(args, "potion", False)),
        deterministic_damage=bool(getattr(args, "deterministic", False)),
        kill_time_s=getattr(args, "kill_time", None),
        trace=bool(getattr(args, "trace", False)),
    )
    config.validate()
    return config


def fail(prog: str, exc: BaseException, code: int, *, show_traceback: bool = False) -> int:
    """Print `prog: message` to stderr (optionally with a traceback) and return `code`."""
    if show_traceback:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    print(f"{prog}: {exc}", file=sys.stderr)
    return code


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write a byte-stable JSON document (sorted keys, two-space indent, LF endings)."""
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")


def emit(text: str) -> None:
    """Print a block with LF endings regardless of platform."""
    sys.stdout.write(text + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `python -m sim.run`. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args)
    except SimConfigError as exc:
        return fail("sim.run", exc, EXIT_CONFIG, show_traceback=args.trace)
    except ValueError as exc:
        return fail("sim.run", exc, EXIT_CONFIG, show_traceback=args.trace)
    try:
        result = run_fight(config)
    except (SimulationError, LuaBridgeError) as exc:
        return fail("sim.run", exc, EXIT_ENGINE, show_traceback=args.trace)
    except SimConfigError as exc:
        return fail("sim.run", exc, EXIT_CONFIG, show_traceback=args.trace)
    if not args.quiet:
        emit(report.format_fight(result))
    if args.trace:
        trace = report.format_trace(result)
        if trace:
            emit(trace)
    if args.json_path:
        write_json(args.json_path, result.to_dict(include_events=True))
    if args.strict:
        rejections = report.rejection_count(result)
        warnings = len(result.warnings)
        if rejections or warnings:
            message = f"strict: {rejections} rejections, {warnings} engine warnings"
            for warning in result.warnings:
                print(f"sim.run: warning: {warning}", file=sys.stderr)
            print(f"sim.run: {message}", file=sys.stderr)
            return EXIT_STRICT
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
