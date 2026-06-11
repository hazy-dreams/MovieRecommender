#! python
"""Command line interface for reducing the movie dataset."""

import argparse
import logging

from movie_recommender.data import MovieDatasetReducer


def main():
    parser = argparse.ArgumentParser(description="Create a reduced movie dataset")
    parser.add_argument(
        "-p",
        "--percentage",
        type=float,
        default=0.90,
        help="Quantile of votes to keep (e.g. 0.90 keeps top 10%% of movies)",
    )
    parser.add_argument(
        "-o", "--output", default="movies_10", help="Output filename without extension"
    )
    parser.add_argument(
        "--input-dir",
        default=".",
        help="Directory containing IMDb TSV files",
    )
    parser.add_argument(
        "--min-votes",
        type=int,
        default=1000,
        help="Minimum votes to keep; use 0 to rely only on --percentage",
    )
    parser.add_argument(
        "--no-typed",
        action="store_true",
        help="Skip optional typed Parquet artifact generation",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    reducer = MovieDatasetReducer()
    reducer.reduce_dataset(
        args.percentage,
        args.output,
        min_votes=args.min_votes,
        write_typed=not args.no_typed,
        input_dir=args.input_dir,
    )


if __name__ == "__main__":
    main()
