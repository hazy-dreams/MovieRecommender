"""Small recommendation quality evaluator for the SQLite preview path."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from src.sqlite_recommender import SQLiteMovieRecommender


DEFAULT_EVALUATION_DATASET = Path("fixtures/recommendation_eval_movies.csv")
DEFAULT_EVALUATION_CASES = Path("fixtures/recommendation_eval_cases.json")


@dataclass(frozen=True)
class EvaluationCase:
    """One seed query and its expected recommendation behavior."""

    case_id: str
    query: str
    top_n: int
    expected_good: tuple[str, ...]
    expected_bad: tuple[str, ...]
    expected_error: str | None = None
    failure_mode: str = ""
    notes: str = ""


@dataclass(frozen=True)
class CaseResult:
    """Evaluation outcome for one seed case."""

    case: EvaluationCase
    recommendations: tuple[str, ...]
    error: str | None
    missing_good: tuple[str, ...]
    present_bad: tuple[str, ...]

    @property
    def passed(self) -> bool:
        if self.case.expected_error:
            return (
                self.error is not None
                and self.case.expected_error in self.error
                and not self.recommendations
            )
        return self.error is None and not self.missing_good and not self.present_bad


@dataclass(frozen=True)
class EvaluationReport:
    """Aggregate recommendation evaluation results."""

    dataset_path: Path
    cases_path: Path
    scorer: str
    results: tuple[CaseResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def expected_good_hits(self) -> int:
        return sum(
            len(result.case.expected_good) - len(result.missing_good)
            for result in self.results
        )

    @property
    def expected_good_total(self) -> int:
        return sum(len(result.case.expected_good) for result in self.results)

    @property
    def expected_bad_absent(self) -> int:
        return sum(
            len(result.case.expected_bad) - len(result.present_bad)
            for result in self.results
        )

    @property
    def expected_bad_total(self) -> int:
        return sum(len(result.case.expected_bad) for result in self.results)

    @property
    def expected_error_hits(self) -> int:
        return sum(
            1
            for result in self.results
            if result.case.expected_error
            and result.error
            and result.case.expected_error in result.error
        )

    @property
    def expected_error_total(self) -> int:
        return sum(1 for result in self.results if result.case.expected_error)


def load_evaluation_cases(cases_path: str | Path) -> tuple[str, tuple[EvaluationCase, ...]]:
    """Load seed cases from the tracked JSON fixture."""
    path = Path(cases_path)
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    cases = []
    for raw_case in payload["cases"]:
        cases.append(
            EvaluationCase(
                case_id=raw_case["id"],
                query=raw_case["query"],
                top_n=int(raw_case.get("top_n", 10)),
                expected_good=tuple(raw_case.get("expected_good", [])),
                expected_bad=tuple(raw_case.get("expected_bad", [])),
                expected_error=raw_case.get("expected_error"),
                failure_mode=raw_case.get("failure_mode", ""),
                notes=raw_case.get("notes", ""),
            )
        )
    return payload.get("scorer", "sqlite-bounded-term-overlap"), tuple(cases)


def evaluate_recommendations(
    dataset_path: str | Path = DEFAULT_EVALUATION_DATASET,
    cases_path: str | Path = DEFAULT_EVALUATION_CASES,
    store_path: str | Path | None = None,
    top_n: int | None = None,
    candidate_limit: int = SQLiteMovieRecommender.DEFAULT_CANDIDATE_LIMIT,
) -> EvaluationReport:
    """Run seed cases against the current bounded SQLite recommender."""
    dataset = Path(dataset_path)
    cases_file = Path(cases_path)
    scorer, cases = load_evaluation_cases(cases_file)

    if store_path is None:
        with tempfile.TemporaryDirectory() as tmp:
            return _evaluate_with_store(
                dataset,
                cases_file,
                Path(tmp) / "recommendation_eval.sqlite",
                cases,
                scorer,
                top_n,
                candidate_limit,
            )

    return _evaluate_with_store(
        dataset,
        cases_file,
        Path(store_path),
        cases,
        scorer,
        top_n,
        candidate_limit,
    )


def _evaluate_with_store(
    dataset_path: Path,
    cases_path: Path,
    store_path: Path,
    cases: tuple[EvaluationCase, ...],
    scorer: str,
    top_n: int | None,
    candidate_limit: int,
) -> EvaluationReport:
    recommender = SQLiteMovieRecommender.from_csv(
        dataset_path,
        store_path,
        candidate_limit=candidate_limit,
    )
    results = []
    for case in cases:
        effective_top_n = case.top_n if top_n is None else top_n
        effective_case = EvaluationCase(
            case_id=case.case_id,
            query=case.query,
            top_n=effective_top_n,
            expected_good=case.expected_good,
            expected_bad=case.expected_bad,
            expected_error=case.expected_error,
            failure_mode=case.failure_mode,
            notes=case.notes,
        )
        results.append(_evaluate_case(recommender, effective_case))
    return EvaluationReport(dataset_path, cases_path, scorer, tuple(results))


def _evaluate_case(
    recommender: SQLiteMovieRecommender,
    case: EvaluationCase,
) -> CaseResult:
    recommendations: tuple[str, ...] = ()
    error = None
    try:
        recommendations = tuple(recommender.recommend(case.query, top_n=case.top_n))
    except ValueError as exc:
        error = str(exc)

    missing_good = tuple(
        title for title in case.expected_good if title not in recommendations
    )
    present_bad = tuple(title for title in case.expected_bad if title in recommendations)
    return CaseResult(case, recommendations, error, missing_good, present_bad)


def write_report(report: EvaluationReport, output: TextIO) -> None:
    """Write a human-readable report for local comparison and CI logs."""
    passed = sum(1 for result in report.results if result.passed)
    total = len(report.results)
    print("Recommendation Quality Evaluation", file=output)
    print(f"Scorer: {report.scorer}", file=output)
    print(f"Dataset: {report.dataset_path}", file=output)
    print(f"Seeds: {report.cases_path}", file=output)
    print(f"Cases: {passed}/{total} passed", file=output)
    print(
        "Expected-good hits: "
        f"{report.expected_good_hits}/{report.expected_good_total}",
        file=output,
    )
    print(
        "Expected-bad misses: "
        f"{report.expected_bad_absent}/{report.expected_bad_total}",
        file=output,
    )
    print(
        "Expected errors: "
        f"{report.expected_error_hits}/{report.expected_error_total}",
        file=output,
    )
    print("", file=output)

    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case.case_id}: {result.case.query}", file=output)
        if result.error is not None:
            print(f"  error: {result.error}", file=output)
        else:
            joined = ", ".join(result.recommendations) or "(none)"
            print(f"  top {result.case.top_n}: {joined}", file=output)
        _write_expectations(result, output)
        if result.case.failure_mode:
            print(f"  failure mode: {result.case.failure_mode}", file=output)
        if result.case.notes:
            print(f"  notes: {result.case.notes}", file=output)


def _write_expectations(result: CaseResult, output: TextIO) -> None:
    if result.case.expected_good:
        missing = ", ".join(result.missing_good) or "(none)"
        print(f"  missing expected good: {missing}", file=output)
    if result.case.expected_bad:
        present = ", ".join(result.present_bad) or "(none)"
        print(f"  present expected bad: {present}", file=output)
    if result.case.expected_error:
        print(f"  expected error: {result.case.expected_error}", file=output)
