"""Compatibility shim for the moved dataset reducer."""

try:
    from movie_recommender.data.dataset_reducer import MovieDatasetReducer
except ModuleNotFoundError as exc:
    if exc.name != "movie_recommender":
        raise
    from .movie_recommender.data.dataset_reducer import MovieDatasetReducer

__all__ = ["MovieDatasetReducer"]
