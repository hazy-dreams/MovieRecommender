"""Compatibility shim for the SQLite recommender."""

from .movie_recommender.recommenders.sqlite_recommender import SQLiteMovieRecommender

__all__ = ["SQLiteMovieRecommender"]
