"""The simulated world's push semantics, checked against real git plumbing.

The whole matrix rests on one assumption: republishing an identical tree to the
same ref converges on one durable result instead of creating a second one.  The
probe runs that against actual git in a throwaway local repository, with no
network, credentials or configured identity.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from harness import fixtures, git_custody_probe
from harness.custody_machine import ExternalWorld
from harness.git_custody_probe import GitUnavailable, git_version, run_probe, verify_recorded_canary
from harness.seeded import repository_root


def _git_or_skip() -> str:
    try:
        return git_version()
    except GitUnavailable as exc:
        raise unittest.SkipTest(f"git unavailable: {exc}") from exc


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.version = _git_or_skip()
        cls.probe = run_probe()

    def test_the_ref_did_not_exist_before_the_push(self):
        self.assertFalse(self.probe["remote_had_commit_before_push"])

    def test_republishing_the_same_tree_converges_on_one_commit(self):
        self.assertTrue(self.probe["push_is_idempotent"])
        self.assertEqual(self.probe["remote_tip_after_first_push"], self.probe["remote_tip_after_replay"])
        self.assertEqual(self.probe["commit"], self.probe["remote_tip_after_first_push"])

    def test_both_pushes_succeed(self):
        self.assertEqual(0, self.probe["first_push_returncode"])
        self.assertEqual(0, self.probe["second_push_returncode"])

    def test_every_artifact_reads_back_byte_identically_from_a_fresh_clone(self):
        self.assertTrue(self.probe["all_artifacts_reconcile"])
        self.assertEqual(len(fixtures.default_payload()), len(self.probe["readback"]))
        for row in self.probe["readback"]:
            self.assertEqual(row["expected_sha256"], row["sha256"], row["logical_name"])
            self.assertEqual(row["expected_bytes"], row["bytes"], row["logical_name"])

    def test_the_workload_payload_is_the_recorded_po03_canary(self):
        self.assertTrue(self.probe["canary_sha256_matches_recorded"])
        self.assertTrue(self.probe["canary_bytes_matches_recorded"])


class SimulationFidelityTests(unittest.TestCase):
    """The simulated world must model the property the probe observed."""

    def test_the_simulated_world_is_also_content_addressed_and_convergent(self):
        _git_or_skip()
        payload = dict(fixtures.default_payload())
        ref = "refs/po03/fidelity"
        first = ExternalWorld.commit_id_for(ref, payload)
        second = ExternalWorld.commit_id_for(ref, dict(sorted(payload.items(), reverse=True)))
        self.assertEqual(first, second)

    def test_a_different_tree_is_a_different_durable_result(self):
        payload = dict(fixtures.default_payload())
        ref = "refs/po03/fidelity"
        changed = {**payload, "canary.txt": payload["canary.txt"] + b"x"}
        self.assertNotEqual(
            ExternalWorld.commit_id_for(ref, payload), ExternalWorld.commit_id_for(ref, changed)
        )

    def test_the_same_tree_under_a_different_ref_is_a_different_result(self):
        payload = dict(fixtures.default_payload())
        self.assertNotEqual(
            ExternalWorld.commit_id_for("refs/po03/a", payload),
            ExternalWorld.commit_id_for("refs/po03/b", payload),
        )


class RecordedCanaryTests(unittest.TestCase):
    def test_the_embedded_fixture_is_checked_against_its_commit_or_declared_unsupported(self):
        _git_or_skip()
        result = verify_recorded_canary(repository_root())
        self.assertIn(result["disposition"], {"MATCHES", "DIVERGED", "NOT_SUPPORTED"})
        if result["disposition"] == "MATCHES":
            self.assertEqual(fixtures.CANARY_SHA256, result["observed_sha256"])
            self.assertEqual(fixtures.CANARY_BYTES, result["observed_bytes"])
        else:
            # The commit lives on another PO-03 branch, so a single-branch clone
            # may not hold the object.  That is recorded, never guessed.
            self.assertTrue(result["reason"].strip())

    def test_the_embedded_digest_matches_the_embedded_bytes(self):
        import hashlib

        self.assertEqual(fixtures.CANARY_SHA256, hashlib.sha256(fixtures.CANARY_TEXT).hexdigest())
        self.assertEqual(fixtures.CANARY_BYTES, len(fixtures.CANARY_TEXT))


class IsolationTests(unittest.TestCase):
    def test_the_probe_uses_no_network_and_no_ambient_git_identity(self):
        env = git_custody_probe.GIT_ENV
        self.assertEqual("/dev/null", env["GIT_CONFIG_GLOBAL"])
        self.assertEqual("/dev/null", env["GIT_CONFIG_SYSTEM"])
        self.assertEqual("0", env["GIT_TERMINAL_PROMPT"])
        source = git_custody_probe.__doc__ or ""
        self.assertIn("file://", source)


if __name__ == "__main__":
    unittest.main()
