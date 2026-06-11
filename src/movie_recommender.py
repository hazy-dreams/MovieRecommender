"""Compatibility shim for the legacy content recommender."""

try:
    from movie_recommender.recommenders.legacy_content import MovieRecommender
except ModuleNotFoundError as exc:
    if exc.name != "movie_recommender":
        raise
    from .movie_recommender.recommenders.legacy_content import MovieRecommender

__all__ = ["MovieRecommender"]
