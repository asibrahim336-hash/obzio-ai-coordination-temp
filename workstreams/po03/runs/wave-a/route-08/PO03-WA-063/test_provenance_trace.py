import unittest

from provenance_trace import NOT_SUPPORTED, trace_unit


class ProvenanceTraceTests(unittest.TestCase):
    def base(self):
        registry = {"task_id": "T", "model": "model-x", "route_id": "r", "result_commit_id": "c"}
        result = {"independent_acceptance": {"state": "PENDING", "reviewer_id": None, "receipt_uri": None}}
        receipt = {
            "recommendation": "RECOMMEND_ACCEPT",
            "reviewer": {
                "reviewer_family": "gpt",
                "exact_model_configuration": "model-y",
                "function_id": "obzio.function.review",
                "appointment_id": "obzio.appointment.review.20260822.001",
            },
            "family_review_status": {"position": "FIRST_INDEPENDENT_CHALLENGER_FAMILY"},
        }
        return registry, result, receipt

    def test_recommendation_is_not_accepted_contribution(self):
        row = trace_unit(*self.base())
        self.assertEqual(row["accepted_contribution"], NOT_SUPPORTED)

    def test_runtime_never_grants_authority(self):
        row = trace_unit(*self.base())
        self.assertFalse(row["producer_runtime_provenance"]["authority_granted"])
        self.assertFalse(row["authority_source"]["runtime_or_model_used_as_authority"])

    def test_family_disagreement_is_preserved(self):
        registry, result, receipt = self.base()
        receipt["family_review_status"]["two_family_comparison"] = {"comparison": "DISAGREEMENT"}
        row = trace_unit(registry, result, receipt)
        self.assertEqual(row["two_family_disagreement"], "DISAGREEMENT")


if __name__ == "__main__":
    unittest.main()
