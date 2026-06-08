__all__ = ["MovieDatasetReducer", "MovieRecommender", "SQLiteMovieRecommender"]


def __getattr__(name):
    if name == "MovieDatasetReducer":
        from .dataset_reducer import MovieDatasetReducer

        return MovieDatasetReducer
    if name == "MovieRecommender":
        from .movie_recommender import MovieRecommender

        return MovieRecommender
    if name == "SQLiteMovieRecommender":
        from .sqlite_recommender import SQLiteMovieRecommender

        return SQLiteMovieRecommender
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
