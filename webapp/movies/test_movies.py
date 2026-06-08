"""Unit tests for the movie recommendation utilities."""

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.dataset_reducer import MovieDatasetReducer
from src.movie_recommender import MovieRecommender
from src.sqlite_recommender import SQLiteMovieRecommender


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
        self.assertEqual(set(dataset["primary_title"]), {"Same Title"})
        self.assertEqual(
            set(dataset["title"]), {"Same Title (tt001)", "Same Title (tt002)"}
        )

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

    def test_reduce_dataset_writes_canonical_csv_artifact(self) -> None:
        """The reducer command path should emit the canonical app-compatible CSV."""
        reducer = MovieDatasetReducer()
        expected_columns = [
            "tconst",
            "title",
            "primary_title",
            "director",
            "director_ids",
            "director_names",
            "genres",
            "score",
            "cast_ids",
            "actors",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "imdb"
            input_dir.mkdir()
            pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "titleType": ["movie", "movie"],
                    "primaryTitle": ["Same Title", "Same Title"],
                    "genres": ["Drama", "Comedy"],
                }
            ).to_csv(input_dir / "title.basics.tsv", sep="\t", index=False)
            pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "directors": ["nm001", "nm002"],
                }
            ).to_csv(input_dir / "title.crew.tsv", sep="\t", index=False)
            pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "averageRating": [7.0, 8.0],
                    "numVotes": [10, 20],
                }
            ).to_csv(input_dir / "title.ratings.tsv", sep="\t", index=False)
            pd.DataFrame(
                {
                    "nconst": ["nm001", "nm002", "nm101", "nm102"],
                    "primaryName": [
                        "Director One",
                        "Director Two",
                        "Actor One",
                        "Actor Two",
                    ],
                }
            ).to_csv(input_dir / "name.basics.tsv", sep="\t", index=False)
            pd.DataFrame(
                {
                    "tconst": ["tt001", "tt002"],
                    "ordering": [1, 1],
                    "nconst": ["nm101", "nm102"],
                    "category": ["actor", "actor"],
                }
            ).to_csv(input_dir / "title.principals.tsv", sep="\t", index=False)

            output_prefix = Path(tmp) / "movies_10"
            dataset = reducer.reduce_dataset(
                percentage=None,
                output_name=output_prefix,
                min_votes=0,
                write_typed=False,
                input_dir=input_dir,
            )
            csv_dataset = pd.read_csv(f"{output_prefix}.csv")
            rec = MovieRecommender()
            loaded = rec.load_dataset(f"{output_prefix}.csv")

        self.assertEqual(dataset.columns.tolist(), expected_columns)
        self.assertEqual(csv_dataset.columns.tolist(), expected_columns)
        self.assertNotIn("Unnamed: 0", csv_dataset.columns)
        self.assertEqual(set(csv_dataset["tconst"]), {"tt001", "tt002"})
        self.assertEqual(set(csv_dataset["primary_title"]), {"Same Title"})
        self.assertEqual(
            set(csv_dataset["title"]), {"Same Title (tt001)", "Same Title (tt002)"}
        )
        self.assertIsInstance(dataset.loc[0, "director_ids"], list)
        self.assertIsInstance(dataset.loc[0, "director_names"], list)
        self.assertIsInstance(dataset.loc[0, "cast_ids"], list)
        self.assertIsInstance(dataset.loc[0, "actors"], list)
        self.assertIsInstance(dataset.loc[0, "genres"], list)
        self.assertEqual(
            set(loaded["title"]), {"Same Title (tt001)", "Same Title (tt002)"}
        )

    def test_typed_output_is_optional_when_parquet_engine_is_missing(self) -> None:
        """Typed output should fall back clearly when optional support is absent."""
        reducer = MovieDatasetReducer()
        metadata = pd.DataFrame({"title": ["Movie A"]})

        with tempfile.TemporaryDirectory() as tmp:
            output_prefix = Path(tmp) / "movies_10"
            with patch.object(
                pd.DataFrame, "to_parquet", side_effect=ImportError("missing parquet")
            ):
                with self.assertLogs("src.dataset_reducer", level="INFO") as logs:
                    typed_path = reducer._write_typed_output(metadata, output_prefix)

        self.assertIsNone(typed_path)
        self.assertIn("Skipped typed Parquet output: missing parquet", logs.output[0])

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

    def test_load_dataset_disambiguates_duplicate_titles_with_tconst(self) -> None:
        """Legacy tconst-bearing CSVs should not build ambiguous title indices."""
        rec = MovieRecommender()
        df = pd.DataFrame(
            {
                "tconst": ["tt001", "tt002", "tt003"],
                "title": ["Same Title", "Same Title", "Other Title"],
                "director": ["Director A", "Director B", "Director C"],
                "genres": ["Action", "Comedy", "Drama"],
                "score": [9.0, 8.0, 7.5],
                "actors": ["Actor A", "Actor B", "Actor C"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        try:
            loaded = rec.load_dataset(Path(tmp.name))
            result = rec.recommend("Same Title (tt001)", top_n=2).tolist()
        finally:
            os.unlink(tmp.name)

        self.assertEqual(
            loaded["title"].tolist(),
            ["Same Title (tt001)", "Same Title (tt002)", "Other Title"],
        )
        self.assertEqual(result, ["Same Title (tt002)", "Other Title"])

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

    def test_sqlite_recommender_builds_store_and_recommends(self) -> None:
        """SQLite path should recommend from an indexed store, not a full matrix."""
        df = pd.DataFrame(
            {
                "tconst": ["tt001", "tt002", "tt003"],
                "title": ["Movie A", "Movie B", "Movie C"],
                "primary_title": ["Movie A", "Movie B", "Movie C"],
                "director": ["Director A", "Director B", "Director C"],
                "genres": [["Action"], ["Action"], ["Drama"]],
                "score": [9.0, 8.0, 8.5],
                "actors": [["Actor X", "Actor Y"], ["Actor Y"], ["Actor X"]],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        store_path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
        os.unlink(store_path)
        try:
            rec = SQLiteMovieRecommender.from_csv(Path(tmp.name), store_path)
            result = rec.recommend("Movie A", top_n=2)
        finally:
            os.unlink(tmp.name)
            if os.path.exists(store_path):
                os.unlink(store_path)

        self.assertEqual(result, ["Movie B", "Movie C"])

    def test_sqlite_recommender_disambiguates_duplicate_titles(self) -> None:
        """The SQLite path should preserve duplicate primary titles by tconst."""
        df = pd.DataFrame(
            {
                "tconst": ["tt001", "tt002", "tt003"],
                "title": ["Same Title", "Same Title", "Other Title"],
                "director": ["Director A", "Director B", "Director C"],
                "genres": ["Action", "Comedy", "Drama"],
                "score": [9.0, 8.0, 7.5],
                "actors": ["Actor A", "Actor B", "Actor C"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        store_path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
        os.unlink(store_path)
        try:
            rec = SQLiteMovieRecommender.from_csv(Path(tmp.name), store_path)
            result = rec.recommend("Same Title (tt001)", top_n=2)
        finally:
            os.unlink(tmp.name)
            if os.path.exists(store_path):
                os.unlink(store_path)

        self.assertEqual(result, ["Same Title (tt002)", "Other Title"])

    def test_sqlite_recommender_limits_term_candidates(self) -> None:
        """Shared-term retrieval should be capped before fallback ranking."""
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B", "Movie C", "Movie D"],
                "director": ["Director A", "Director B", "Director C", "Director D"],
                "genres": ["Action", "Action", "Action", "Drama"],
                "score": [9.0, 8.0, 7.0, 10.0],
                "actors": ["Actor A", "Actor B", "Actor C", "Actor D"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        store_path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
        os.unlink(store_path)
        try:
            rec = SQLiteMovieRecommender.from_csv(
                Path(tmp.name),
                store_path,
                candidate_limit=1,
            )
            result = rec.recommend("Movie A", top_n=3)
        finally:
            os.unlink(tmp.name)
            if os.path.exists(store_path):
                os.unlink(store_path)

        self.assertEqual(result, ["Movie B", "Movie D", "Movie C"])


if __name__ == "__main__":
    unittest.main()
