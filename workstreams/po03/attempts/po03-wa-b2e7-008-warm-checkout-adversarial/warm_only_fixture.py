"""Fixture body copied into a synthetic committed test by the adversarial harness."""

import unittest
from pathlib import Path


class WarmOnlyGate(unittest.TestCase):
    def test_requires_uncommitted_warm_marker(self):
        self.assertTrue(
            Path(".warm-state").is_file(),
            "gate depends on an uncommitted warm-checkout marker",
        )


if __name__ == "__main__":
    unittest.main()
