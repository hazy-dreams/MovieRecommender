"""Command line entrypoint for TMDB enrichment helpers."""

from movie_recommender.data.tmdb_enrichment import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
