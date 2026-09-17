"""Unit tests for `sim.damage` and `sim.rng` (SPEC.md section 4.8).

Written pytest-style (plain `assert`) inside `unittest.TestCase` subclasses so the file
runs under both `pytest` and `python -m unittest discover`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sim.damage import BuffSnapshot, DamageModel, StatProfile  # noqa: E402
from sim.rng import STREAM_NAMES, SeededRNG  # noqa: E402
from sim.tables import Tables  # noqa: E402

NEUTRAL = BuffSnapshot()


def _profile(**overrides: float) -> StatProfile:
    """A StatProfile from the shipped stats.json with test overrides applied."""
    return StatProfile.from_tables(Tables.load(), **overrides)


class RNGTests(unittest.TestCase):
    """The named-substream RNG."""

    def test_stream_is_stable_across_instances(self) -> None:
        a = SeededRNG(7).stream("crit")
        b = SeededRNG(7).stream("crit")
        assert [a.random() for _ in range(20)] == [b.random() for _ in range(20)]

    def test_stream_is_cached(self) -> None:
        rng = SeededRNG(3)
        assert rng.stream("crit") is rng.stream("crit")
        assert rng.seed == 3

    def test_different_seeds_differ(self) -> None:
        one = [SeededRNG(1).stream("crit").random() for _ in range(5)]
        two = [SeededRNG(2).stream("crit").random() for _ in range(5)]
        assert one != two

    def test_independent_streams(self) -> None:
        rng = SeededRNG(11)
        dh_before = rng.stream("dh").getstate()
        for _ in range(1000):
            rng.stream("crit").random()
        assert rng.stream("dh").getstate() == dh_before

    def test_all_declared_stream_names_resolve(self) -> None:
        rng = SeededRNG(5)
        seen = {name: rng.stream(name).random() for name in STREAM_NAMES}
        assert len(set(seen.values())) == len(STREAM_NAMES)


class DamageTests(unittest.TestCase):
    """The potency-to-damage model."""

    def test_roll_is_deterministic_for_seed(self) -> None:
        first = DamageModel(_profile(), SeededRNG(42))
        second = DamageModel(_profile(), SeededRNG(42))
        a = [first.roll(220, NEUTRAL) for _ in range(100)]
        b = [second.roll(220, NEUTRAL) for _ in range(100)]
        assert a == b

    def test_crit_rate_observed_matches_profile(self) -> None:
        profile = _profile(damage_variance=0.0)
        model = DamageModel(profile, SeededRNG(99))
        rolls = 100_000
        crits = sum(1 for _ in range(rolls) if model.roll(100, NEUTRAL).crit)
        observed = crits / rolls
        assert abs(observed - profile.crit_rate) < 0.005, observed

    def test_dh_rate_observed_matches_profile(self) -> None:
        profile = _profile(damage_variance=0.0)
        model = DamageModel(profile, SeededRNG(98))
        rolls = 100_000
        hits = sum(1 for _ in range(rolls) if model.roll(100, NEUTRAL).direct_hit)
        observed = hits / rolls
        assert abs(observed - profile.dh_rate) < 0.005, observed

    def test_buff_snapshot_multiplies(self) -> None:
        profile = _profile(
            crit_rate=0.0, dh_rate=0.0, damage_variance=0.0, potency_to_damage=100.0
        )
        model = DamageModel(profile, SeededRNG(1))
        plain = model.roll(100, NEUTRAL)
        buffed = model.roll(100, BuffSnapshot(damage_mult=1.15))
        assert plain.amount == 100.0 * 100.0
        assert buffed.amount == 100.0 * 100.0 * 1.15
        assert buffed.crit is False
        assert buffed.direct_hit is False
        assert abs(buffed.multiplier - 1.15) < 1e-12

    def test_buff_snapshot_combined(self) -> None:
        merged = BuffSnapshot(1.15, 0.02, 0.0).combined(BuffSnapshot(1.06, 0.0, 0.20))
        assert abs(merged.damage_mult - 1.15 * 1.06) < 1e-12
        assert abs(merged.crit_add - 0.02) < 1e-12
        assert abs(merged.dh_add - 0.20) < 1e-12

    def test_expected_matches_mean_of_rolls(self) -> None:
        profile = _profile()
        model = DamageModel(profile, SeededRNG(2024))
        snap = BuffSnapshot(damage_mult=1.15, crit_add=0.02, dh_add=0.20)
        rolls = 200_000
        total = 0.0
        for _ in range(rolls):
            total += model.roll(220, snap).amount
        mean = total / rolls
        expected = model.expected(220, snap)
        assert abs(mean - expected) / expected < 0.01, (mean, expected)

    def test_zero_variance_consumes_no_variance_stream(self) -> None:
        rng = SeededRNG(5)
        model = DamageModel(_profile(damage_variance=0.0), rng)
        before = rng.stream("variance").getstate()
        for _ in range(10):
            model.roll(220, NEUTRAL)
        assert rng.stream("variance").getstate() == before

    def test_nonzero_variance_consumes_the_variance_stream(self) -> None:
        rng = SeededRNG(5)
        model = DamageModel(_profile(damage_variance=0.05), rng)
        before = rng.stream("variance").getstate()
        model.roll(220, NEUTRAL)
        assert rng.stream("variance").getstate() != before

    def test_crit_add_clamped_to_unit_interval(self) -> None:
        profile = _profile(crit_rate=0.5, dh_rate=0.0, damage_variance=0.0)
        model = DamageModel(profile, SeededRNG(77))
        always = BuffSnapshot(crit_add=10.0)
        never = BuffSnapshot(crit_add=-10.0)
        assert all(model.roll(100, always).crit for _ in range(200))
        assert not any(model.roll(100, never).crit for _ in range(200))
        # The expectation applies the same clamp.
        assert abs(model.expected(100, always) - 100.0 * profile.potency_to_damage
                   * profile.crit_mult) < 1e-9
        assert abs(model.expected(100, never) - 100.0 * profile.potency_to_damage) < 1e-9

    def test_dh_add_clamped_to_unit_interval(self) -> None:
        profile = _profile(crit_rate=0.0, dh_rate=0.9, damage_variance=0.0)
        model = DamageModel(profile, SeededRNG(78))
        assert all(model.roll(100, BuffSnapshot(dh_add=1.0)).direct_hit for _ in range(200))

    def test_from_tables_rejects_unknown_override(self) -> None:
        try:
            _profile(crit_ratio=0.5)
        except TypeError as exc:
            assert "crit_ratio" in str(exc)
        else:
            raise AssertionError("expected TypeError for an unknown StatProfile override")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
