import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("portable_executor.py")
SPEC = importlib.util.spec_from_file_location("wa029_executor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class PortableExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        script = self.repo / "successor_reproducer.py"
        script.write_text("print('{}')\n", encoding="utf-8")
        self.command = (
            "python3 successor_reproducer.py --repo . "
            "--manifest successor-generation.json"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_supported_route_is_invoked_with_shell_false(self):
        completed = mock.Mock(returncode=0, stdout="{}\n", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            report = MODULE.execute(self.command, self.repo)
        self.assertEqual("PASS", report["disposition"])
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertIsInstance(run.call_args.args[0], list)

    def test_hidden_shell_and_interpreter_routes_are_not_executed(self):
        hostile = (
            "bash -c 'echo bad'",
            "python3 -c 'print(1)'",
            "python3 successor_reproducer.py --repo . && touch escaped",
            "curl https://example.invalid",
        )
        with mock.patch.object(MODULE.subprocess, "run") as run:
            for command in hostile:
                with self.subTest(command=command):
                    report = MODULE.execute(command, self.repo)
                    self.assertEqual("NOT_SUPPORTED", report["disposition"])
                    self.assertFalse(report["executed"])
        run.assert_not_called()

    def test_unsupported_flag_and_escape_fail_explicitly(self):
        unsupported = MODULE.execute(
            "python3 successor_reproducer.py --output result.json", self.repo
        )
        self.assertEqual(["UNSUPPORTED_FLAG:--output"], unsupported["defects"])
        escape = MODULE.execute("python3 ../successor_reproducer.py", self.repo)
        self.assertEqual("NOT_SUPPORTED", escape["disposition"])


if __name__ == "__main__":
    unittest.main()
