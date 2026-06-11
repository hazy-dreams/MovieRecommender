"""Command line entrypoint for IMDb source bootstrap helpers."""

from movie_recommender.data.imdb_bootstrap import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
