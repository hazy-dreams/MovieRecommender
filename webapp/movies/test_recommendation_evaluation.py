"""Tests for the recommendation quality evaluation harness."""

from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.recommendation_evaluation import (
    DEFAULT_EVALUATION_CASES,
    DEFAULT_EVALUATION_DATASET,
    evaluate_recommendations,
    write_report,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class RecommendationEvaluationTest(unittest.TestCase):
    """The harness should report repeatable seed-case outcomes."""

    def test_default_seed_report_passes(self) -> None:
        output = StringIO()

        report = evaluate_recommendations()
        write_report(report, output)

        self.assertTrue(report.passed)
        self.assertEqual(report.expected_good_hits, 4)
        self.assertEqual(report.expected_bad_absent, 2)
        self.assertIn("Cases: 3/3 passed", output.getvalue())
        self.assertIn("[PASS] crime-shared-terms: Neon Heist", output.getvalue())
        self.assertIn("Expected errors: 1/1", output.getvalue())

    def test_report_flags_expected_bad_recommendation(self) -> None:
        failing_cases = {
            "schema_version": 1,
            "scorer": "sqlite-bounded-term-overlap",
            "cases": [
                {
                    "id": "bad-title-present",
                    "query": "Neon Heist",
                    "top_n": 3,
                    "expected_good": ["Midnight Crew"],
                    "expected_bad": ["Midnight Crew"],
                    "failure_mode": "Expected-bad titles should fail when present.",
                    "notes": "Intentional failing seed for report coverage.",
                }
            ],
        }
        output = StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / "cases.json"
            cases_path.write_text(json.dumps(failing_cases), encoding="utf-8")
            report = evaluate_recommendations(
                dataset_path=DEFAULT_EVALUATION_DATASET,
                cases_path=cases_path,
            )
            write_report(report, output)

        self.assertFalse(report.passed)
        self.assertIn("Cases: 0/1 passed", output.getvalue())
        self.assertIn("[FAIL] bad-title-present: Neon Heist", output.getvalue())
        self.assertIn("present expected bad: Midnight Crew", output.getvalue())

    def test_cli_report_command_exits_successfully_for_default_seeds(self) -> None:
        result = subprocess.run(
            [sys.executable, "evaluate_recommendations.py"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Recommendation Quality Evaluation", result.stdout)
        self.assertIn(str(DEFAULT_EVALUATION_CASES), result.stdout)


if __name__ == "__main__":
    unittest.main()
