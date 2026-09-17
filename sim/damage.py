"""The CielBard simulator's stat and damage model.

Potency is converted to damage by a single calibration scalar, `potency_to_damage`, so
that the whole stat side of the simulator is one number to fit against real parses. Crit
and direct-hit rolls come from independent named RNG substreams; the variance roll is
skipped entirely (no draw) when `damage_variance` is zero.

`damage_variance = 0` removes only the +/- 5 % roll: `roll` still draws crit and direct
hit. The expected-value mode is `expected_value=True`, which makes
`Simulation._deal_damage` call :meth:`DamageModel.expected` instead and consumes no
randomness at all.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .rng import SeededRNG
from .tables import Tables

__all__ = ["StatProfile", "BuffSnapshot", "DamageResult", "DamageModel"]

_NEUTRAL_KEYS = ("damage_mult", "crit_add", "dh_add")


def _clamp_unit(value: float) -> float:
    """Clamp a probability to [0, 1]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True)
class StatProfile:
    """Stat-side inputs. Everything here is loaded from stats.json and overridable."""

    crit_rate: float
    crit_mult: float
    dh_rate: float
    dh_mult: float
    potency_to_damage: float
    damage_variance: float
    crit_dh_independent: bool = True
    # True -> the core replaces every `roll` with `expected`, so a fight consumes no
    # crit/dh/variance randomness at all. Set from FightConfig.deterministic_damage.
    expected_value: bool = False

    @classmethod
    def from_tables(cls, tables: Tables, **overrides: Any) -> "StatProfile":
        """Build a profile from `tables.stats`, with keyword overrides applied on top.

        An override naming a field this profile does not have raises TypeError, which is
        the typo protection sweeps rely on.
        """
        stats = tables.stats
        profile = cls(
            crit_rate=float(stats["crit_rate"]),
            crit_mult=float(stats["crit_mult"]),
            dh_rate=float(stats["dh_rate"]),
            dh_mult=float(stats["dh_mult"]),
            potency_to_damage=float(stats["potency_to_damage"]),
            damage_variance=float(stats["damage_variance"]),
            crit_dh_independent=bool(stats["crit_dh_independent"]),
        )
        if not overrides:
            return profile
        unknown = sorted(set(overrides) - set(profile.__dataclass_fields__))
        if unknown:
            raise TypeError(f"StatProfile.from_tables: unknown override(s) {unknown}")
        return replace(profile, **overrides)


@dataclass(frozen=True)
class BuffSnapshot:
    """Multipliers frozen at cast time (or DoT application time).

    `damage_mult` is the product of every multiplicative buff (Raging Strikes, Mage's
    Ballad, Radiant Finale, Medicated). `crit_add` / `dh_add` are additive rate bonuses
    (Wanderer's Minuet, Army's Paeon, Battle Voice).
    """

    damage_mult: float = 1.0
    crit_add: float = 0.0
    dh_add: float = 0.0

    def combined(self, other: "BuffSnapshot") -> "BuffSnapshot":
        """Merge two snapshots: multipliers multiply, rate bonuses add."""
        return BuffSnapshot(
            damage_mult=self.damage_mult * other.damage_mult,
            crit_add=self.crit_add + other.crit_add,
            dh_add=self.dh_add + other.dh_add,
        )


NEUTRAL_SNAPSHOT = BuffSnapshot()


@dataclass(frozen=True)
class DamageResult:
    """One resolved damage instance."""

    amount: float
    potency: int
    crit: bool
    direct_hit: bool
    multiplier: float


class DamageModel:
    """Potency -> damage, with crit/direct-hit rolls drawn from named RNG streams."""

    __slots__ = ("_profile", "_rng", "_crit", "_dh", "_variance")

    def __init__(self, profile: StatProfile, rng: SeededRNG) -> None:
        """Bind a stat profile to a seeded RNG family and resolve its substreams."""
        self._profile = profile
        self._rng = rng
        self._crit = rng.stream("crit")
        self._dh = rng.stream("dh")
        self._variance = rng.stream("variance")

    @property
    def profile(self) -> StatProfile:
        """The stat profile this model was built with."""
        return self._profile

    @property
    def rng(self) -> SeededRNG:
        """The RNG family this model draws from."""
        return self._rng

    def roll(self, potency: int, snap: BuffSnapshot = NEUTRAL_SNAPSHOT) -> DamageResult:
        """One damage instance.

        amount = potency * potency_to_damage * snap.damage_mult
                 * (crit_mult if crit else 1) * (dh_mult if dh else 1) * variance

        crit is `stream("crit").random() < clamp(crit_rate + snap.crit_add, 0, 1)`,
        dh likewise from `stream("dh")`; the two rolls are independent when
        `crit_dh_independent`. variance is
        `1 + stream("variance").uniform(-damage_variance, damage_variance)`, and is
        skipped entirely (no draw) when `damage_variance == 0.0`.

        This always draws crit and direct hit. For the expected-value path see
        :meth:`expected`, which the core uses when `profile.expected_value` is set.
        """
        profile = self._profile
        crit_rate = _clamp_unit(profile.crit_rate + snap.crit_add)
        dh_rate = _clamp_unit(profile.dh_rate + snap.dh_add)

        crit_draw = self._crit.random()
        crit = crit_draw < crit_rate
        if profile.crit_dh_independent:
            direct_hit = self._dh.random() < dh_rate
        else:
            # Correlated mode: both outcomes are read off the same uniform draw, so a
            # crit implies a direct hit whenever dh_rate >= crit_rate.
            direct_hit = crit_draw < dh_rate

        multiplier = snap.damage_mult
        if crit:
            multiplier *= profile.crit_mult
        if direct_hit:
            multiplier *= profile.dh_mult
        if profile.damage_variance != 0.0:
            spread = profile.damage_variance
            multiplier *= 1.0 + self._variance.uniform(-spread, spread)

        amount = float(potency) * profile.potency_to_damage * multiplier
        return DamageResult(
            amount=amount,
            potency=int(potency),
            crit=crit,
            direct_hit=direct_hit,
            multiplier=multiplier,
        )

    def expected(self, potency: int, snap: BuffSnapshot = NEUTRAL_SNAPSHOT) -> float:
        """Closed-form expectation of `roll`, consuming no randomness.

        Used by `Simulation._deal_damage` whenever `profile.expected_value` is set
        (`sim.run --deterministic`), by sweeps that want low variance, and by
        `test_damage` to check that the mean of 200_000 rolls is within 1 % of it.
        """
        profile = self._profile
        crit_rate = _clamp_unit(profile.crit_rate + snap.crit_add)
        dh_rate = _clamp_unit(profile.dh_rate + snap.dh_add)
        cm = profile.crit_mult
        dm = profile.dh_mult
        if profile.crit_dh_independent:
            expected_mult = (1.0 + crit_rate * (cm - 1.0)) * (1.0 + dh_rate * (dm - 1.0))
        else:
            # Both outcomes come off one uniform draw, so they are perfectly correlated.
            lo = min(crit_rate, dh_rate)
            hi = max(crit_rate, dh_rate)
            only_mult = cm if crit_rate > dh_rate else dm
            expected_mult = lo * cm * dm + (hi - lo) * only_mult + (1.0 - hi)
        # The variance roll is symmetric about 1.0, so it contributes a factor of 1.
        return float(potency) * profile.potency_to_damage * snap.damage_mult * expected_mult
