"""Reusable MovieRecommender package."""

__all__ = ["MovieDatasetReducer", "MovieRecommender", "SQLiteMovieRecommender"]


def __getattr__(name):
    if name == "MovieDatasetReducer":
        from .data.dataset_reducer import MovieDatasetReducer

        return MovieDatasetReducer
    if name == "MovieRecommender":
        from .recommenders.legacy_content import MovieRecommender

        return MovieRecommender
    if name == "SQLiteMovieRecommender":
        from .recommenders.sqlite_recommender import SQLiteMovieRecommender

        return SQLiteMovieRecommender
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
