"""Recall fixture: real portability defects that live inside a test module.

Never imported by the suite and never executed.  It is the guard on the
``TEST_FIXTURE`` role.  That role is the widest of the eight, so it needs a
counterexample: a test file is not a blanket exemption, and the literals below
must keep firing even though every one of them sits in an asserting test method
in a ``test_*.py`` file.

The difference from ``test_strings_under_test.py`` is that each literal here
reaches a filesystem sink.  A hard-coded scratch directory in a test is the
exact failure mode that makes a suite pass on a warm checkout and fail in a
clean runner, and it would be worthless to trade it away for a quieter report.
"""

import os
import shutil
import unittest
from pathlib import Path

SHARED_SCRATCH = "/tmp/po03-shared-scratch"


class HardCodedScratch(unittest.TestCase):
    def setUp(self):
        # Module-level constant reaching a sink: still a defect.
        Path(SHARED_SCRATCH).mkdir(parents=True, exist_ok=True)

    def test_reads_a_file_outside_the_tree(self):
        content = open("/etc/obzio/po03.json", encoding="utf-8").read()
        self.assertTrue(content)

    def test_writes_where_an_earlier_run_may_have_left_something(self):
        target = Path("/var/tmp/po03-checkpoint.json")
        target.write_text("{}", encoding="utf-8")
        self.assertTrue(target.exists())

    def test_walks_an_absolute_tree(self):
        self.assertTrue(os.path.exists("/srv/obzio/ledger.jsonl"))

    def test_home_relative_state(self):
        self.assertTrue(os.path.expanduser("~/.obzio/credentials"))

    def tearDown(self):
        shutil.rmtree("/tmp/po03-shared-scratch", ignore_errors=True)
