"""Dataset loading and reduction helpers."""

__all__ = ["MovieDatasetReducer"]


def __getattr__(name):
    if name == "MovieDatasetReducer":
        from .dataset_reducer import MovieDatasetReducer

        return MovieDatasetReducer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
