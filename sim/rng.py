"""Deterministic, named random substreams for the CielBard simulator.

Every stochastic system in the simulator draws from its own named stream so that adding,
removing or reordering rolls in one system cannot perturb another system's sequence.
"""

from __future__ import annotations

import hashlib
import random

__all__ = ["SeededRNG", "STREAM_NAMES"]

#: The complete set of stream names the simulator is allowed to use. Adding a stream
#: means adding it here *and* to SPEC.md section 4.6 -- it is part of the public contract.
STREAM_NAMES: tuple[str, ...] = (
    "crit",
    "dh",
    "variance",
    "repertoire",
    "hawks_eye",
    "tick_offset",
)


class SeededRNG:
    """Deterministic named random streams.

    A named substream is independent of every other substream, so adding a roll to one
    system never perturbs another system's sequence. This is what makes the simulator's
    determinism robust to code changes rather than merely reproducible.
    """

    __slots__ = ("_seed", "_streams")

    def __init__(self, seed: int) -> None:
        """Create a generator family rooted at `seed`."""
        self._seed = int(seed)
        self._streams: dict[str, random.Random] = {}

    @property
    def seed(self) -> int:
        """The root seed this family was created with."""
        return self._seed

    def stream(self, name: str) -> random.Random:
        """Return the `random.Random` for `name`, creating it on first use.

        The stream's seed is derived as
        `int.from_bytes(hashlib.blake2b(f"{seed}:{name}".encode(), digest_size=8), "big")`,
        which is stable across interpreter runs (unlike `hash()`).
        """
        existing = self._streams.get(name)
        if existing is not None:
            return existing
        digest = hashlib.blake2b(f"{self._seed}:{name}".encode(), digest_size=8).digest()
        stream = random.Random(int.from_bytes(digest, "big"))
        self._streams[name] = stream
        return stream

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"SeededRNG(seed={self._seed}, streams={sorted(self._streams)})"
