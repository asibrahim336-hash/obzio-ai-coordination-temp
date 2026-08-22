import unittest

from lesson_compiler import accepted_lesson, compile_lessons


def result(number, state="PENDING"):
    accepted = state == "ACCEPTED"
    return {
        "task_id": f"PO03-WA-{number:03d}",
        "result_transaction": {"result_commit_id": f"commit-{number}"},
        "independent_acceptance": {
            "state": state,
            "reviewer_id": "independent" if accepted else None,
            "receipt_uri": f"receipts/{number}.json" if accepted else None,
        },
    }


class LessonCompilerTests(unittest.TestCase):
    def test_recommendation_is_not_acceptance(self):
        row = result(41)
        row["recommendation"] = "RECOMMEND_ACCEPT"
        self.assertFalse(accepted_lesson(row))
        self.assertEqual(compile_lessons([row])["disposition"], "NOT_YET")

    def test_three_terminal_acceptances_compile(self):
        report = compile_lessons([result(41, "ACCEPTED"), result(42, "ACCEPTED"), result(43, "ACCEPTED")])
        self.assertEqual(report["disposition"], "PASS")
        self.assertEqual(len(report["compiled_route_changes"]), 3)

    def test_missing_receipt_is_not_accepted(self):
        row = result(41, "ACCEPTED")
        row["independent_acceptance"]["receipt_uri"] = None
        self.assertFalse(accepted_lesson(row))


if __name__ == "__main__":
    unittest.main()
