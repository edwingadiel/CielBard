"""Fight configuration for the CielBard simulator.

A :class:`FightConfig` is the complete, hashable-by-value description of one
fight.  Two runs built from equal configs produce byte-identical results, so the
config is also what a batch, a sweep or the calibration pass varies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

__all__ = ["SimConfigError", "DowntimeWindow", "FightConfig"]


class SimConfigError(ValueError):
    """Raised for an impossible or contradictory fight configuration."""


@dataclass(frozen=True)
class DowntimeWindow:
    """A window during which the target cannot be attacked."""

    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        """Raises SimConfigError when end <= start or start < 0."""
        if self.start_s < 0:
            raise SimConfigError(f"downtime start must be >= 0, got {self.start_s}")
        if self.end_s <= self.start_s:
            raise SimConfigError(
                f"downtime end must be > start, got {self.start_s}..{self.end_s}"
            )

    @property
    def duration_s(self) -> float:
        """The length of the window in seconds."""
        return self.end_s - self.start_s

    def contains(self, t_s: float) -> bool:
        """True when `t_s` lies inside the window (start inclusive, end exclusive)."""
        return self.start_s <= t_s < self.end_s


@dataclass(frozen=True)
class FightConfig:
    """Everything needed to reproduce one fight exactly."""

    seconds: float = 510.0
    seed: int = 1
    ping_ms: float = 0.0
    pulse_ms: int = 30                    # also written into the engine config
    engine_config: Mapping[str, Any] = field(default_factory=dict)
    downtime: Tuple[DowntimeWindow, ...] = ()
    # The number of striking dummies. Dummy 1 is the engine's target; the rest are
    # identical clones placed `enemy_spread_yalms` from it, which is what makes the
    # AoE replacements (Ladonsbite, Shadowbite, Rain of Death) worth casting.
    enemies: int = 1
    # The radius, in yalms, of the ring the clones stand on around the primary target.
    # `CielBard_Rotation.lua`'s `CountEnemiesNear` only counts an entity whose `pos` is
    # within 5 yalms of the target's, which is Shadowbite's radius, so the default puts
    # every clone comfortably inside it. Raise it above 5 to build a scattered pack the
    # engine must decline to treat as an AoE target group.
    enemy_spread_yalms: float = 2.0
    stat_overrides: Mapping[str, float] = field(default_factory=dict)
    job_overrides: Mapping[str, Any] = field(default_factory=dict)
    use_potion: bool = False
    deterministic_damage: bool = False    # damage_variance -> 0
    tick_offset_s: float | None = None    # None -> drawn from the "tick_offset" stream
    fast_skip_locked: bool = True
    trace: bool = False
    repo_root: Path | None = None         # default: parents of this file
    # The dummy's linear death time in seconds, which is all the engine's TTK
    # estimator ever sees. None (the default) is a striking dummy that never dies,
    # which is what SPEC 1 says this simulator models; set it to `seconds` to get
    # SPEC 6.6's linear kill-time dummy, whose terminal phase suppresses DoT
    # refreshes for the last `dotMinimumTTK` seconds of the fight.
    kill_time_s: float | None = None

    def validate(self) -> None:
        """Raises SimConfigError for: seconds <= 0, pulse_ms <= 0 or > 1000,
        ping_ms < 0, overlapping downtime windows, downtime beyond `seconds`,
        enemies < 1, enemy_spread_yalms < 0."""
        if self.seconds <= 0:
            raise SimConfigError(f"seconds must be > 0, got {self.seconds}")
        if self.pulse_ms <= 0 or self.pulse_ms > 1000:
            raise SimConfigError(f"pulse_ms must be in 1..1000, got {self.pulse_ms}")
        if self.ping_ms < 0:
            raise SimConfigError(f"ping_ms must be >= 0, got {self.ping_ms}")
        if self.enemies < 1:
            raise SimConfigError(f"enemies must be >= 1, got {self.enemies}")
        if self.enemy_spread_yalms < 0:
            raise SimConfigError(
                f"enemy_spread_yalms must be >= 0, got {self.enemy_spread_yalms}"
            )
        if self.kill_time_s is not None and self.kill_time_s <= 0:
            raise SimConfigError(f"kill_time_s must be > 0 or None, got {self.kill_time_s}")
        windows = sorted(self.downtime, key=lambda w: (w.start_s, w.end_s))
        previous: DowntimeWindow | None = None
        for window in windows:
            if window.end_s > self.seconds:
                raise SimConfigError(
                    f"downtime window {window.start_s}..{window.end_s} ends after the "
                    f"fight ({self.seconds}s)"
                )
            if previous is not None and window.start_s < previous.end_s:
                raise SimConfigError(
                    f"downtime windows overlap: {previous.start_s}..{previous.end_s} "
                    f"and {window.start_s}..{window.end_s}"
                )
            previous = window

    def engine_overrides(self) -> Dict[str, Any]:
        """The full override mapping handed to FakeClient.init_engine: the caller's
        `engine_config` plus the forced values
        {"enabled": True, "debug": False, "pulseMs": self.pulse_ms,
         "usePotion": self.use_potion, "requireCombat": True, "requireLOS": False}.
        Caller keys win over the forced ones EXCEPT `enabled` and `debug`.
        """
        overrides: Dict[str, Any] = {
            "pulseMs": self.pulse_ms,
            "usePotion": self.use_potion,
            "requireCombat": True,
            "requireLOS": False,
        }
        overrides.update(dict(self.engine_config))
        overrides["enabled"] = True
        overrides["debug"] = False
        return overrides

    def resolved_repo_root(self) -> Path:
        """The repository root: `repo_root` when set, otherwise this file's grandparent."""
        if self.repo_root is not None:
            return Path(self.repo_root)
        return Path(__file__).resolve().parent.parent

    def with_seed(self, seed: int) -> "FightConfig":
        """A copy of this config with a different RNG seed."""
        return replace(self, seed=seed)

    def to_dict(self) -> Dict[str, Any]:
        """A JSON-ready view of the config (paths become strings)."""
        return {
            "seconds": float(self.seconds),
            "seed": int(self.seed),
            "ping_ms": float(self.ping_ms),
            "pulse_ms": int(self.pulse_ms),
            "engine_config": {str(k): self.engine_config[k] for k in sorted(self.engine_config)},
            "downtime": [[float(w.start_s), float(w.end_s)] for w in self.downtime],
            "enemies": int(self.enemies),
            "enemy_spread_yalms": float(self.enemy_spread_yalms),
            "stat_overrides": {
                str(k): float(self.stat_overrides[k]) for k in sorted(self.stat_overrides)
            },
            "job_overrides": {str(k): self.job_overrides[k] for k in sorted(self.job_overrides)},
            "use_potion": bool(self.use_potion),
            "deterministic_damage": bool(self.deterministic_damage),
            "tick_offset_s": None if self.tick_offset_s is None else float(self.tick_offset_s),
            "kill_time_s": None if self.kill_time_s is None else float(self.kill_time_s),
            "fast_skip_locked": bool(self.fast_skip_locked),
            "trace": bool(self.trace),
            "repo_root": None if self.repo_root is None else str(self.repo_root),
        }
