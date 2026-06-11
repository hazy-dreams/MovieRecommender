"""Recommendation engines and evaluation helpers."""

__all__ = ["MovieRecommender", "SQLiteMovieRecommender"]


def __getattr__(name):
    if name == "MovieRecommender":
        from .legacy_content import MovieRecommender

        return MovieRecommender
    if name == "SQLiteMovieRecommender":
        from .sqlite_recommender import SQLiteMovieRecommender

        return SQLiteMovieRecommender
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
