import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("config_precedence_resolver.py")
SPEC = importlib.util.spec_from_file_location("wa028_config", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ConfigPrecedenceResolverTests(unittest.TestCase):
    def test_declared_beats_environment_and_defaults(self):
        report = MODULE.resolve_config(
            ["route"],
            {"route": "declared-route"},
            {"PO03_ROUTE": "environment-route"},
            {"route": "default-route"},
        )
        self.assertEqual(
            {"source": "declared", "availability": "AVAILABLE", "value": "declared-route"},
            report["values"]["route"],
        )

    def test_environment_beats_default_when_declaration_absent(self):
        report = MODULE.resolve_config(
            ["route"], {}, {"PO03_ROUTE": "environment-route"}, {"route": "default-route"}
        )
        self.assertEqual("environment", report["values"]["route"]["source"])

    def test_hidden_unknown_values_are_preserved_not_filled(self):
        report = MODULE.resolve_config(
            ["a", "b", "c"],
            {"a": "UNKNOWN", "b": None},
            {"PO03_A": "ambient", "PO03_B": "ambient"},
            {"a": "default", "b": "default"},
        )
        self.assertEqual("UNKNOWN", report["values"]["a"]["value"])
        self.assertEqual("UNKNOWN", report["values"]["a"]["availability"])
        self.assertIsNone(report["values"]["b"]["value"])
        self.assertEqual("UNAVAILABLE", report["values"]["b"]["availability"])
        self.assertEqual({"state": "UNAVAILABLE"}, report["values"]["c"]["value"])

    def test_empty_environment_value_is_not_silently_defaulted(self):
        report = MODULE.resolve_config(
            ["route"], {}, {"PO03_ROUTE": ""}, {"route": "default-route"}
        )
        self.assertEqual("", report["values"]["route"]["value"])
        self.assertEqual("environment", report["values"]["route"]["source"])


if __name__ == "__main__":
    unittest.main()
