"""Compatibility shim for the SQLite recommender."""

try:
    from movie_recommender.recommenders.sqlite_recommender import SQLiteMovieRecommender
except ModuleNotFoundError as exc:
    if exc.name != "movie_recommender":
        raise
    from .movie_recommender.recommenders.sqlite_recommender import (
        SQLiteMovieRecommender,
    )

__all__ = ["SQLiteMovieRecommender"]
