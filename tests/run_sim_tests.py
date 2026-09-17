#!/usr/bin/env python3
"""Run the simulator's unit and integration tests with plain unittest.

Equivalent to::

    python -m unittest discover -s tests -p "test_*.py" -t .

run from the repository root, but without requiring the caller to be in the
repository root and without a pytest dependency. Prints one summary line and
exits non-zero when anything failed or errored.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
PATTERN = "test_*.py"


def build_suite() -> unittest.TestSuite:
    """Discover every `test_*.py` module under `tests/`.

    The repository root is placed on `sys.path` first so that discovered modules
    can `import sim` (and so the simulator package is the one in this checkout,
    not an installed copy).
    """
    root = str(ROOT)
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)
    loader = unittest.TestLoader()
    return loader.discover(start_dir=str(TESTS_DIR), pattern=PATTERN, top_level_dir=str(TESTS_DIR))


def main(argv: list[str] | None = None) -> int:
    """Run the discovered suite. Returns the process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    verbosity = 2 if ("-v" in argv or "--verbose" in argv) else 1
    suite = build_suite()
    result = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stderr).run(suite)
    total = result.testsRun
    if result.wasSuccessful():
        skipped = len(result.skipped)
        extra = f", {skipped} skipped" if skipped else ""
        print(f"CielBard sim tests passed ({total} tests{extra}).")
        return 0
    failed = len(result.failures) + len(result.errors)
    print(
        f"CielBard sim tests failed ({failed} of {total} tests).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
