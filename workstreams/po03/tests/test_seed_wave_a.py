import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "seed_wave_a.py"
SPEC = importlib.util.spec_from_file_location("seed_wave_a", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WaveASeedTests(unittest.TestCase):
    def test_wave_a_has_exactly_64_distinct_substantive_attempts(self):
        self.assertEqual(64, len(MODULE.TASKS))
        self.assertEqual(64, len({task["id"] for task in MODULE.TASKS}))
        self.assertEqual(64, len({task["hypothesis"] for task in MODULE.TASKS}))

    def test_wave_a_keeps_every_standing_function_live(self):
        functions = {task["function"] for task in MODULE.TASKS}
        self.assertTrue(
            {
                "current-plan-engineering",
                "strategy-challenge",
                "frontier-research",
                "controlled-reproduction",
                "independent-evaluation",
                "model-runtime-evaluation",
                "semantic-state-contract",
                "operating-system-measurement",
                "successor-compilation",
            }.issubset(functions)
        )

    def test_model_allocation_is_exact_and_heterogeneous(self):
        allocations = {MODULE._model_for(index)[0] for index in range(1, 65)}
        self.assertEqual({"claude-opus-5-thinking-high", "gpt-5.6-sol-xhigh"}, allocations)


if __name__ == "__main__":
    unittest.main()
