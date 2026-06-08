#! python
"""Command line interface for recommending movies."""

import argparse
import logging
from pathlib import Path

from src.sqlite_recommender import SQLiteMovieRecommender


def main():
    parser = argparse.ArgumentParser(description="Recommend movies from a dataset")
    parser.add_argument("dataset", help="CSV dataset produced by movies.py")
    parser.add_argument("title", nargs="?", help="Movie title to search for")
    parser.add_argument(
        "--store",
        help="SQLite store path. Defaults to the dataset path with .sqlite suffix.",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=SQLiteMovieRecommender.DEFAULT_CANDIDATE_LIMIT,
        help="Maximum shared-term candidates to rank before score fallback.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    store_path = args.store or Path(args.dataset).with_suffix(".sqlite")
    recommender = SQLiteMovieRecommender.from_csv(
        args.dataset,
        store_path,
        candidate_limit=args.candidate_limit,
    )

    title = args.title or input("What movie would you like a recommendation for? ")
    try:
        recommendations = recommender.recommend(title)
        print(recommendations)
    except ValueError as exc:
        print(exc)


if __name__ == "__main__":
    main()
