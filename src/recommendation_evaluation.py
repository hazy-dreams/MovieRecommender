"""Compatibility shim for recommendation evaluation helpers."""

try:
    from movie_recommender.recommenders.evaluation import *  # noqa: F403
except ModuleNotFoundError as exc:
    if exc.name != "movie_recommender":
        raise
    from .movie_recommender.recommenders.evaluation import *  # noqa: F403
