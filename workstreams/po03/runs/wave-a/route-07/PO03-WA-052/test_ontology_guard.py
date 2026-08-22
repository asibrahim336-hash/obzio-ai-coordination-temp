"""Falsification tests for the PO03-WA-052 four-axis ontology guard.

The hypothesis fails if a runtime or provider value can occupy an authority axis,
if authority can be sourced from a runtime binding, or if a rename or rebinding
silently drops standing permission.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ontology_guard import (  # noqa: E402
    AUTHORITY_BEARING_AXES,
    ActorRecord,
    AuthoritySourceError,
    Axis,
    EVIDENCE_ONLY_AXES,
    LEGACY_ALIASES,
    OntologyViolation,
    authority_source,
    axis_of,
    rebind_runtime,
    rename_function,
    resolve,
)

GOOD = ActorRecord(
    function="obzio.function.evaluation-and-semantics",
    appointment="obzio.appointment.evaluation-and-semantics.20260822.001",
    runtime_binding="Cursor Cloud",
    provider_model="claude-opus-5-thinking-high",
    aliases=("Operator D", "Claude extension"),
    provenance=("v010 mission title retained as evidence",),
    authority_envelope="obzio.authority-envelope.evaluation-and-semantics.20260822.001",
)


class AxisSeparationTests(unittest.TestCase):
    def test_a_well_formed_record_resolves_into_four_axes(self):
        resolution = resolve(GOOD)
        self.assertTrue(resolution.separated)
        self.assertEqual(
            {"function", "appointment", "runtime", "provider"}, set(resolution.axes)
        )
        self.assertEqual("Cursor Cloud", resolution.axes["runtime"])
        self.assertEqual("claude-opus-5-thinking-high", resolution.axes["provider"])

    def test_axes_are_disjoint_by_construction(self):
        self.assertEqual(set(), AUTHORITY_BEARING_AXES & EVIDENCE_ONLY_AXES)
        self.assertEqual(
            {Axis.FUNCTION, Axis.APPOINTMENT, Axis.RUNTIME, Axis.PROVIDER},
            AUTHORITY_BEARING_AXES | EVIDENCE_ONLY_AXES,
        )

    def test_axis_inference_places_known_vocabulary(self):
        self.assertIs(Axis.FUNCTION, axis_of("obzio.function.evaluation-and-semantics"))
        self.assertIs(
            Axis.APPOINTMENT, axis_of("obzio.appointment.evaluation-and-semantics.20260822.001")
        )
        self.assertIs(Axis.RUNTIME, axis_of("Cursor Cloud"))
        self.assertIs(Axis.PROVIDER, axis_of("gpt-5.6-sol-xhigh"))
        self.assertIsNone(axis_of("something unclassified"))

    def test_runtime_value_on_the_function_axis_is_refused(self):
        bad = ActorRecord(function="Cursor Cloud", appointment=GOOD.appointment)
        with self.assertRaises(OntologyViolation):
            resolve(bad)

    def test_provider_value_on_the_function_axis_is_refused(self):
        bad = ActorRecord(function="claude-opus-5", appointment=GOOD.appointment)
        with self.assertRaises(OntologyViolation):
            resolve(bad)

    def test_provider_value_on_the_appointment_axis_is_refused(self):
        bad = ActorRecord(function=GOOD.function, appointment="gpt-5.6-sol-xhigh")
        with self.assertRaises(OntologyViolation):
            resolve(bad)

    def test_function_identifier_on_the_runtime_axis_is_refused(self):
        bad = ActorRecord(
            function=GOOD.function,
            appointment=GOOD.appointment,
            runtime_binding="obzio.function.evaluation-and-semantics",
        )
        with self.assertRaises(OntologyViolation):
            resolve(bad)

    def test_runtime_value_on_the_provider_axis_is_refused(self):
        bad = ActorRecord(
            function=GOOD.function, appointment=GOOD.appointment, provider_model="Chrome extension"
        )
        with self.assertRaises(OntologyViolation):
            resolve(bad)

    def test_non_strict_resolution_reports_instead_of_raising(self):
        bad = ActorRecord(function="Cursor Cloud", appointment=GOOD.appointment)
        resolution = resolve(bad, strict=False)
        self.assertFalse(resolution.separated)
        self.assertTrue(any("runtime" in v for v in resolution.violations))


class LegacyAliasTests(unittest.TestCase):
    def test_every_legacy_alias_is_refused_on_an_authority_axis(self):
        for alias in sorted(LEGACY_ALIASES):
            with self.subTest(alias=alias):
                bad = ActorRecord(function=alias, appointment=GOOD.appointment)
                with self.assertRaises(OntologyViolation):
                    resolve(bad)

    def test_legacy_aliases_survive_in_the_alias_field(self):
        resolution = resolve(GOOD)
        self.assertIn("Operator D", resolution.aliases)
        self.assertIn("Claude extension", resolution.aliases)

    def test_provenance_is_preserved_and_never_promoted_to_an_axis(self):
        resolution = resolve(GOOD)
        self.assertEqual(("v010 mission title retained as evidence",), resolution.provenance)
        self.assertNotIn("v010 mission title retained as evidence", resolution.axes.values())


class AuthoritySourceTests(unittest.TestCase):
    def test_authority_reads_from_an_appointment(self):
        self.assertEqual(GOOD.authority_envelope, authority_source(GOOD, Axis.APPOINTMENT))

    def test_authority_reads_from_a_function(self):
        self.assertEqual(GOOD.authority_envelope, authority_source(GOOD, Axis.FUNCTION))

    def test_a_runtime_never_grants_authority(self):
        with self.assertRaises(AuthoritySourceError):
            authority_source(GOOD, Axis.RUNTIME)

    def test_a_provider_never_grants_authority(self):
        with self.assertRaises(AuthoritySourceError):
            authority_source(GOOD, Axis.PROVIDER)

    def test_a_record_without_an_envelope_grants_nothing(self):
        stripped = ActorRecord(function=GOOD.function, appointment=GOOD.appointment)
        with self.assertRaises(AuthoritySourceError):
            authority_source(stripped, Axis.APPOINTMENT)


class ContinuityTests(unittest.TestCase):
    def test_runtime_rebinding_preserves_appointment_and_authority(self):
        rebound = rebind_runtime(GOOD, "Cursor Desktop", "gpt-5.6-sol-xhigh")
        self.assertEqual(GOOD.appointment, rebound.appointment)
        self.assertEqual(GOOD.function, rebound.function)
        self.assertEqual(GOOD.authority_envelope, rebound.authority_envelope)
        self.assertEqual("Cursor Desktop", rebound.runtime_binding)
        self.assertIn("previous-runtime:Cursor Cloud", rebound.provenance)

    def test_a_rename_is_additive_and_keeps_standing_permission(self):
        renamed = rename_function(GOOD, "obzio.function.independent-assurance-and-acceptance")
        self.assertEqual(GOOD.appointment, renamed.appointment)
        self.assertEqual(GOOD.authority_envelope, renamed.authority_envelope)
        self.assertIn(f"previous-function:{GOOD.function}", renamed.provenance)

    def test_a_rename_into_a_runtime_label_is_refused(self):
        with self.assertRaises(OntologyViolation):
            rename_function(GOOD, "Claude extension")

    def test_rebinding_into_a_function_identifier_is_refused(self):
        with self.assertRaises(OntologyViolation):
            rebind_runtime(GOOD, "obzio.function.evaluation-and-semantics")


if __name__ == "__main__":
    unittest.main()
