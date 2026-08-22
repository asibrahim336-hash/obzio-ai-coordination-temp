import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("portable_route_cardinality.py")
SPEC = importlib.util.spec_from_file_location("wa032_routes", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


COMMAND = (
    "python3 workstreams/po03/runs/wave-a/route-08/PO03-WA-064/"
    "successor_reproducer.py --repo . --manifest successor-generation.json"
)


class PortableRouteCardinalityTests(unittest.TestCase):
    def test_exactly_one_route_passes(self):
        report = MODULE.qualify_routes({"reproduction_command": COMMAND})
        self.assertEqual("PASS", report["disposition"])
        self.assertEqual(1, len(report["valid_routes"]))

    def test_zero_routes_fails(self):
        report = MODULE.qualify_routes({})
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(0, report["declarations"])

    def test_multiple_routes_fail_even_when_equivalent(self):
        report = MODULE.qualify_routes(
            {"reproduction_command": COMMAND, "portable_routes": [COMMAND]}
        )
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(2, report["declarations"])

    def test_hidden_ambiguous_shell_route_fails(self):
        report = MODULE.qualify_routes(
            {"reproduction_command": f"{COMMAND} || python3 fallback.py"}
        )
        self.assertEqual("FAIL", report["disposition"])
        self.assertEqual(
            "AMBIGUOUS_OR_UNSUPPORTED_ROUTE", report["defects"][0]["code"]
        )

    def test_multiple_routes_cannot_be_hidden_in_argv(self):
        report = MODULE.qualify_routes(
            {
                "portable_routes": [
                    {"argv": ["python3", "successor_reproducer.py"]},
                    {"argv": ["python3", "successor_reproducer.py", "--repo", "."]},
                ]
            }
        )
        self.assertEqual("FAIL", report["disposition"])


if __name__ == "__main__":
    unittest.main()
