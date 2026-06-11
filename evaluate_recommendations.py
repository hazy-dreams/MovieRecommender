#! python
"""Command line entrypoint for recommendation quality evaluation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.recommendation_evaluation import (
    DEFAULT_EVALUATION_CASES,
    DEFAULT_EVALUATION_DATASET,
    evaluate_recommendations,
    write_report,
)
from src.sqlite_recommender import SQLiteMovieRecommender


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the bounded SQLite recommender against seed cases."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_EVALUATION_DATASET,
        help=f"Evaluation CSV fixture. Default: {DEFAULT_EVALUATION_DATASET}",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_EVALUATION_CASES,
        help=f"Evaluation seed JSON. Default: {DEFAULT_EVALUATION_CASES}",
    )
    parser.add_argument(
        "--store",
        type=Path,
        help="Optional SQLite store path. Defaults to a temporary file.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        help="Override top_n for every seed case.",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=SQLiteMovieRecommender.DEFAULT_CANDIDATE_LIMIT,
        help="Maximum shared-term candidates to rank before score fallback.",
    )
    args = parser.parse_args()

    report = evaluate_recommendations(
        dataset_path=args.dataset,
        cases_path=args.cases,
        store_path=args.store,
        top_n=args.top_n,
        candidate_limit=args.candidate_limit,
    )
    write_report(report, sys.stdout)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
