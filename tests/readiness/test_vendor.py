# Run: uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/readiness -t .
"""The vendored renderer must stay a byte copy of the explainer's."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
READINESS = ROOT / "skills/readiness"


class VendorTest(unittest.TestCase):
    def test_facts_lib_is_a_byte_copy(self):
        self.assertEqual(
            (READINESS / "scripts/facts_lib.py").read_bytes(),
            (ROOT / "skills/explainer/scripts/facts_lib.py").read_bytes(),
            "re-copy: cp skills/explainer/scripts/facts_lib.py skills/readiness/scripts/",
        )


if __name__ == "__main__":
    unittest.main()
