"""Compatibility shim for IMDb bootstrap helpers."""

try:
    from movie_recommender.data.imdb_bootstrap import *  # noqa: F403
except ModuleNotFoundError as exc:
    if exc.name != "movie_recommender":
        raise
    from .movie_recommender.data.imdb_bootstrap import *  # noqa: F403
