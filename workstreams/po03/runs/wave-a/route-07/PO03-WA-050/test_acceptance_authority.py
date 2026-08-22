"""Falsification tests for PO03-WA-050 alias-resistant self-acceptance blocking.

The hypothesis fails if any aliased spelling of the producing principal is
accepted as an independent reviewer.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from acceptance_authority import (  # noqa: E402
    ALIAS_ONLY_FIELDS,
    ChallengerFamilyRequired,
    IdentityRegistry,
    IdentityRoutingError,
    PROHIBITED_ROUTING_ALIASES,
    Principal,
    SelfAcceptanceBlocked,
    authorize_acceptance,
    normalize_identity,
)

PRODUCER = Principal(
    function="obzio.function.transactional-custody",
    appointment="obzio.appointment.transactional-custody.20260822.001",
    display_name="Route 01 Custody Producer",
    aliases=(
        "route-01-material-worker",
        "Route_01 Material Worker",
        "route.01.material.worker@obzio.example",
        "Operator D",
    ),
    runtime_binding="Cursor Cloud",
    provider_run_id="bc-route-01",
    model_family="claude-opus-5",
)

REVIEWER = Principal(
    function="obzio.function.evaluation-and-semantics",
    appointment="obzio.appointment.evaluation-and-semantics.20260822.001",
    display_name="Route 07 Independent Reviewer",
    aliases=("route-07-independent-reviewer",),
    runtime_binding="Cursor Cloud",
    provider_run_id="bc-route-07",
    model_family="gpt-5.6-sol",
)


def registry() -> IdentityRegistry:
    reg = IdentityRegistry()
    reg.register(PRODUCER)
    reg.register(REVIEWER)
    return reg


class NormalizationTests(unittest.TestCase):
    def test_case_and_separator_variants_collapse(self):
        forms = [
            "route-01-material-worker",
            "Route-01-Material-Worker",
            "ROUTE_01_MATERIAL_WORKER",
            "route.01.material.worker",
            "  route 01   material worker  ",
            "route--01--material--worker",
        ]
        canon = {normalize_identity(f) for f in forms}
        self.assertEqual(1, len(canon), canon)

    def test_email_form_collapses_to_the_handle(self):
        self.assertEqual(
            normalize_identity("route-01-material-worker"),
            normalize_identity("route-01-material-worker@obzio.example"),
        )

    def test_invisible_characters_are_stripped(self):
        sneaky = "route-01-\u200bmaterial\u200d-worker\ufeff"
        self.assertEqual(normalize_identity("route-01-material-worker"), normalize_identity(sneaky))

    def test_homoglyph_substitution_is_defeated(self):
        # Cyrillic 'о' and 'а' rendering as Latin.
        sneaky = "r\u043eute-01-m\u0430terial-w\u043erker"
        self.assertEqual(normalize_identity("route-01-material-worker"), normalize_identity(sneaky))

    def test_fullwidth_and_compatibility_forms_collapse(self):
        self.assertEqual(normalize_identity("route-01-material-worker"), normalize_identity(
            "route-01-m\uff41terial-worker"
        ))

    def test_empty_identity_is_rejected(self):
        for bad in ("", "   ", None, 7):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    normalize_identity(bad)


class SelfAcceptanceTests(unittest.TestCase):
    def test_exact_self_acceptance_is_blocked(self):
        with self.assertRaises(SelfAcceptanceBlocked):
            authorize_acceptance(
                registry(), "route-01-material-worker", "route-01-material-worker"
            )

    def test_every_alias_of_the_producer_is_blocked_as_reviewer(self):
        attacks = [
            "Route-01-Material-Worker",
            "ROUTE_01_MATERIAL_WORKER",
            "route.01.material.worker@obzio.example",
            "r\u043eute-01-m\u0430terial-w\u043erker",
            "route-01-\u200bmaterial-worker",
            "obzio.appointment.transactional-custody.20260822.001",
            "obzio.function.transactional-custody",
            "Route 01 Custody Producer",
        ]
        for attack in attacks:
            with self.subTest(alias=attack):
                with self.assertRaises(SelfAcceptanceBlocked):
                    authorize_acceptance(registry(), "route-01-material-worker", attack)

    def test_a_distinct_principal_is_authorized(self):
        record = authorize_acceptance(
            registry(), "route-01-material-worker", "route-07-independent-reviewer"
        )
        self.assertTrue(record["authorized"])
        self.assertNotEqual(record["producer_principal"], record["reviewer_principal"])

    def test_authorization_never_grants_a_terminal_state(self):
        record = authorize_acceptance(
            registry(), "route-01-material-worker", "route-07-independent-reviewer"
        )
        self.assertFalse(record["terminal_state_permitted"])
        self.assertNotIn("ACCEPTED", record["permitted_reviewer_outputs"])
        self.assertEqual(
            ["RECOMMEND_ACCEPT", "RECOMMEND_REJECT", "RETEST"],
            record["permitted_reviewer_outputs"],
        )


class RoutingAliasTests(unittest.TestCase):
    def test_prohibited_alias_cannot_route_a_reviewer(self):
        for alias in sorted(PROHIBITED_ROUTING_ALIASES):
            with self.subTest(alias=alias):
                with self.assertRaises(IdentityRoutingError):
                    authorize_acceptance(registry(), "route-01-material-worker", alias)

    def test_prohibited_alias_is_readable_in_a_provenance_field(self):
        reg = registry()
        principal = reg.resolve("Operator D", field_name="provenance")
        self.assertEqual(PRODUCER.durable_key, principal.durable_key)

    def test_alias_only_fields_are_explicit(self):
        self.assertIn("runtime", ALIAS_ONLY_FIELDS)
        self.assertIn("provenance", ALIAS_ONLY_FIELDS)
        self.assertNotIn("reviewer_id", ALIAS_ONLY_FIELDS)

    def test_unregistered_identity_is_refused(self):
        with self.assertRaises(IdentityRoutingError):
            authorize_acceptance(registry(), "route-01-material-worker", "somebody-else")


class ChallengerFamilyTests(unittest.TestCase):
    def test_same_family_challenger_is_refused_for_consequential_decisions(self):
        reg = IdentityRegistry()
        reg.register(PRODUCER)
        same_family = Principal(
            function="obzio.function.evaluation-and-semantics",
            appointment="obzio.appointment.evaluation-and-semantics.20260822.002",
            aliases=("same-family-reviewer",),
            model_family="claude-opus-5",
        )
        reg.register(same_family)
        with self.assertRaises(ChallengerFamilyRequired):
            authorize_acceptance(reg, "route-01-material-worker", "same-family-reviewer")

    def test_same_family_is_tolerated_for_non_consequential_review(self):
        reg = IdentityRegistry()
        reg.register(PRODUCER)
        same_family = Principal(
            function="obzio.function.evaluation-and-semantics",
            appointment="obzio.appointment.evaluation-and-semantics.20260822.002",
            aliases=("same-family-reviewer",),
            model_family="claude-opus-5",
        )
        reg.register(same_family)
        record = authorize_acceptance(
            reg, "route-01-material-worker", "same-family-reviewer", consequential=False
        )
        self.assertTrue(record["authorized"])

    def test_missing_model_family_blocks_a_consequential_decision(self):
        reg = IdentityRegistry()
        reg.register(PRODUCER)
        unknown = Principal(
            function="obzio.function.evaluation-and-semantics",
            appointment="obzio.appointment.evaluation-and-semantics.20260822.003",
            aliases=("unknown-family-reviewer",),
            model_family="",
        )
        reg.register(unknown)
        with self.assertRaises(ChallengerFamilyRequired):
            authorize_acceptance(reg, "route-01-material-worker", "unknown-family-reviewer")


if __name__ == "__main__":
    unittest.main()
