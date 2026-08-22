import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from impl import is_even


class EvenTests(unittest.TestCase):
    def test_even_only(self):
        self.assertTrue(is_even(2))
