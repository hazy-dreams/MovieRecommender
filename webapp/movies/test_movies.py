"""Unit tests for the movie recommendation utilities."""

from pathlib import Path
import os
import tempfile
import unittest

import pandas as pd

from src.dataset_reducer import MovieDatasetReducer
from src.movie_recommender import MovieRecommender


class MovieUtilsTest(unittest.TestCase):
    """Tests for :mod:`src.movie_recommender` and helpers."""

    def test_weighted_rating(self) -> None:
        """Weighted rating should combine average rating and vote count."""
        reducer = MovieDatasetReducer()
        row = {"numVotes": 100, "averageRating": 8.0}
        rating = reducer.weighted_rating(row, C=7.0, m=50)
        self.assertAlmostEqual(rating, 7.6667, places=4)

    def test_build_reduced_dataset_preserves_duplicate_titles_by_tconst(self) -> None:
        """Movies sharing a title should remain distinct canonical rows."""
        reducer = MovieDatasetReducer()
        dataset = reducer.build_reduced_dataset(
            titles=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "titleType": ["movie", "movie"],
                    "primaryTitle": ["Same Title", "Same Title"],
                    "genres": ["Drama", "Comedy"],
                }
            ),
            crew=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "directors": ["nm001", "nm002"],
                }
            ),
            ratings=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "averageRating": [7.0, 8.0],
                    "numVotes": [10, 20],
                }
            ),
            names=pd.DataFrame(
                {
                    "nconst": ["nm001", "nm002", "nm101", "nm102"],
                    "primaryName": [
                        "Director One",
                        "Director Two",
                        "Actor One",
                        "Actor Two",
                    ],
                }
            ),
            principals=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "ordering": [1, 1],
                    "nconst": ["nm101", "nm102"],
                    "category": ["actor", "actor"],
                }
            ),
            percentage=None,
            min_votes=0,
        )

        self.assertEqual(set(dataset["tconst"]), {"tt001", "tt002"})
        self.assertEqual(dataset["title"].tolist().count("Same Title"), 2)

    def test_build_reduced_dataset_extracts_directors_and_cast(self) -> None:
        """Directors should split on commas and cast should include actresses."""
        reducer = MovieDatasetReducer()
        dataset = reducer.build_reduced_dataset(
            titles=pd.DataFrame(
                {
                    "tconst": ["tt001"],
                    "titleType": ["movie"],
                    "primaryTitle": ["Movie A"],
                    "genres": ["Action,Drama"],
                }
            ),
            crew=pd.DataFrame(
                {
                    "tconst": ["tt001"],
                    "directors": ["nm001,nm002,nm003,nm004"],
                }
            ),
            ratings=pd.DataFrame(
                {
                    "tconst": ["tt001"],
                    "averageRating": [8.0],
                    "numVotes": [2000],
                }
            ),
            names=pd.DataFrame(
                {
                    "nconst": [
                        "nm001",
                        "nm002",
                        "nm003",
                        "nm004",
                        "nm101",
                        "nm102",
                        "nm103",
                    ],
                    "primaryName": [
                        "Director One",
                        "Director Two",
                        "Director Three",
                        "Director Four",
                        "Actor One",
                        "Actress One",
                        "Writer One",
                    ],
                }
            ),
            principals=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt001", "tt001"],
                    "ordering": [2, 1, 3],
                    "nconst": ["nm101", "nm102", "nm103"],
                    "category": ["actor", "actress", "writer"],
                }
            ),
            percentage=None,
            min_votes=1000,
        )
        row = dataset.iloc[0]

        self.assertEqual(row["director_ids"], ["nm001", "nm002", "nm003"])
        self.assertEqual(
            row["director_names"],
            ["Director One", "Director Two", "Director Three"],
        )
        self.assertEqual(row["director"], "Director One")
        self.assertEqual(row["actors"], ["Actress One", "Actor One"])
        self.assertEqual(row["cast_ids"], ["nm102", "nm101"])
        self.assertEqual(row["genres"], ["Action", "Drama"])
        self.assertIsInstance(row["actors"], list)
        self.assertIsInstance(row["genres"], list)

    def test_build_reduced_dataset_uses_explicit_vote_threshold(self) -> None:
        """The minimum-votes path should filter below-threshold movies."""
        reducer = MovieDatasetReducer()
        dataset = reducer.build_reduced_dataset(
            titles=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "titleType": ["movie", "movie"],
                    "primaryTitle": ["Movie A", "Movie B"],
                    "genres": ["Drama", "Drama"],
                }
            ),
            crew=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "directors": ["nm001", "nm002"],
                }
            ),
            ratings=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "averageRating": [7.0, 8.0],
                    "numVotes": [999, 1000],
                }
            ),
            names=pd.DataFrame(
                {
                    "nconst": ["nm001", "nm002"],
                    "primaryName": ["Director One", "Director Two"],
                }
            ),
            principals=pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "ordering": [1, 1],
                    "nconst": ["nm001", "nm002"],
                    "category": ["director", "director"],
                }
            ),
            percentage=None,
            min_votes=1000,
        )

        self.assertEqual(dataset["tconst"].tolist(), ["tt002"])

    def test_clean_data_and_create_soup(self) -> None:
        """Verify cleaning helpers and soup creation."""
        rec = MovieRecommender()
        self.assertEqual(rec.clean_data(["Actor X", "Actor Y"]), ["actorx", "actory"])
        self.assertEqual(rec.clean_data("Action Thriller"), "actionthriller")
        self.assertEqual(rec.clean_data(None), "")

        row = {
            "actors": ["actorx", "actory"],
            "director": ["directora", "directora"],
            "genres": ["action", "thriller"],
        }
        soup = rec.create_soup(row)
        self.assertEqual(soup, "actorxactory directoradirectora actionthriller")

    def test_load_and_recommend(self) -> None:
        """Loading a small dataset should enable recommendations."""
        rec = MovieRecommender()
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B", "Movie C"],
                "director": ["Director A", "Director B", "Director C"],
                "genres": ["Action", "Action", "Drama"],
                "score": [9.0, 8.0, 8.5],
                "actors": [
                    "Actor X Actor Y",
                    "Actor Y Actor Z",
                    "Actor X Actor W",
                ],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        try:
            rec.load_dataset(Path(tmp.name))
            result = rec.recommend("Movie A", top_n=2).tolist()
        finally:
            os.unlink(tmp.name)
        self.assertEqual(result, ["Movie B", "Movie C"])


if __name__ == "__main__":
    unittest.main()
