"""Views for the movie recommendation app."""

from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.shortcuts import render

from src.sqlite_recommender import SQLiteMovieRecommender


@lru_cache(maxsize=1)
def _load_recommender(
    dataset: str,
    store: str,
    candidate_limit: int,
) -> SQLiteMovieRecommender:
    """Return a SQLite recommender with ``dataset`` imported if needed."""
    return SQLiteMovieRecommender.from_csv(
        dataset,
        store,
        candidate_limit=candidate_limit,
    )


@lru_cache(maxsize=1)
def _load_existing_store(
    store: str,
    candidate_limit: int,
) -> SQLiteMovieRecommender:
    """Return a SQLite recommender for an existing store."""
    return SQLiteMovieRecommender(store, candidate_limit=candidate_limit)


def get_recommender() -> SQLiteMovieRecommender:
    """Return a cached :class:`SQLiteMovieRecommender` instance."""
    dataset_path = Path(settings.RECOMMENDER_DATASET_PATH)
    store_path = Path(settings.RECOMMENDER_STORE_PATH)
    if not dataset_path.exists() and not store_path.exists():
        raise ValueError("Dataset not found. Please run dataset reducer.")
    if store_path.exists() and not dataset_path.exists():
        return _load_existing_store(
            str(store_path),
            settings.RECOMMENDER_CANDIDATE_LIMIT,
        )
    return _load_recommender(
        str(dataset_path),
        str(store_path),
        settings.RECOMMENDER_CANDIDATE_LIMIT,
    )


def search(request):
    """Render the search form and show recommendations."""
    recommendations = None
    error = None
    if request.method == "POST":
        title = request.POST.get("title", "")
        if title:
            try:
                recommender = get_recommender()
                recommendations = list(recommender.recommend(title))
            except Exception as exc:
                error = str(exc)
    return render(
        request,
        "movies/search.html",
        {"recommendations": recommendations, "error": error},
    )
