"""Unit tests for the movie recommendation utilities."""

from pathlib import Path
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import pandas as pd

from movie_recommender.data import MovieDatasetReducer
from movie_recommender.recommenders.legacy_content import MovieRecommender
from movie_recommender.recommenders.sqlite_recommender import SQLiteMovieRecommender


class MovieUtilsTest(unittest.TestCase):
    """Tests for recommender utilities and helpers."""

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
                with self.assertLogs(
                    "movie_recommender.data.dataset_reducer", level="INFO"
                ) as logs:
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

    def test_package_import_is_lightweight(self) -> None:
        """Importing the package should not load pandas/sklearn eagerly."""
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import movie_recommender; "
                    "assert 'pandas' not in sys.modules; "
                    "assert 'sklearn' not in sys.modules"
                ),
            ],
            cwd=repo_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_direct_src_path_package_imports_use_canonical_paths(self) -> None:
        """PYTHONPATH=src should expose only canonical package imports."""
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util; "
                    "from movie_recommender.data.dataset_reducer import "
                    "MovieDatasetReducer; "
                    "from movie_recommender.recommenders.legacy_content import "
                    "MovieRecommender; "
                    "from movie_recommender.recommenders.sqlite_recommender import "
                    "SQLiteMovieRecommender; "
                    "from movie_recommender.recommenders.evaluation import "
                    "evaluate_recommendations; "
                    "from movie_recommender.data.imdb_bootstrap import list_sources; "
                    "assert MovieDatasetReducer.__name__ == 'MovieDatasetReducer'; "
                    "assert MovieRecommender.__name__ == 'MovieRecommender'; "
                    "assert SQLiteMovieRecommender.__name__ == "
                    "'SQLiteMovieRecommender'; "
                    "assert evaluate_recommendations.__name__ == "
                    "'evaluate_recommendations'; "
                    "assert list_sources.__name__ == 'list_sources'; "
                    "old_names = ['dataset_reducer', 'sqlite_recommender', "
                    "'recommendation_evaluation', 'imdb_bootstrap']; "
                    "assert all(importlib.util.find_spec(name) is None "
                    "for name in old_names)"
                ),
            ],
            cwd="/tmp",
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sqlite_recommender_rebuilds_when_csv_identity_changes(self) -> None:
        """A reused store path should rebuild for a different source CSV."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_one = Path(tmp) / "one.csv"
            csv_two = Path(tmp) / "two.csv"
            store_path = Path(tmp) / "movies.sqlite"
            pd.DataFrame(
                {
                    "title": ["Movie A", "Movie B"],
                    "director": ["Director A", "Director B"],
                    "genres": ["Drama", "Drama"],
                    "score": [9.0, 8.0],
                    "actors": ["Actor X", "Actor Y"],
                }
            ).to_csv(csv_one, index=False)
            pd.DataFrame(
                {
                    "title": ["Movie C", "Movie D"],
                    "director": ["Director C", "Director D"],
                    "genres": ["Comedy", "Comedy"],
                    "score": [7.0, 6.0],
                    "actors": ["Actor Z", "Actor W"],
                }
            ).to_csv(csv_two, index=False)

            SQLiteMovieRecommender.from_csv(csv_one, store_path)
            older_than_store = store_path.stat().st_mtime - 100
            os.utime(csv_two, (older_than_store, older_than_store))
            rec = SQLiteMovieRecommender.from_csv(csv_two, store_path)

            with sqlite3.connect(store_path) as conn:
                metadata = dict(
                    conn.execute("SELECT key, value FROM store_metadata").fetchall()
                )
            result = rec.recommend("Movie C", top_n=1)
            expected_source_path = str(csv_two.resolve())
            rebuilds_for_csv_one = SQLiteMovieRecommender._store_needs_rebuild(
                csv_one,
                store_path,
            )

        self.assertEqual(result, ["Movie D"])
        self.assertEqual(metadata["source_path"], expected_source_path)
        self.assertTrue(rebuilds_for_csv_one)

    def test_sqlite_recommender_uses_unique_temp_file(self) -> None:
        """A stale fixed temp DB path should not be shared or deleted."""
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B"],
                "director": ["Director A", "Director B"],
                "genres": ["Drama", "Drama"],
                "score": [9.0, 8.0],
                "actors": ["Actor X", "Actor Y"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "movies.csv"
            store_path = Path(tmp) / "movies.sqlite"
            fixed_tmp_path = Path(tmp) / "movies.sqlite.tmp"
            fixed_tmp_path.write_text("sentinel", encoding="utf-8")
            df.to_csv(csv_path, index=False)

            SQLiteMovieRecommender.build_store(csv_path, store_path)

            self.assertEqual(fixed_tmp_path.read_text(encoding="utf-8"), "sentinel")
            self.assertFalse(Path(f"{store_path}.lock").exists())

    def test_sqlite_recommender_creates_score_fallback_index(self) -> None:
        """The fallback score/title ordering should have a matching index."""
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B"],
                "director": ["Director A", "Director B"],
                "genres": ["Drama", "Drama"],
                "score": [9.0, 8.0],
                "actors": ["Actor X", "Actor Y"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "movies.csv"
            store_path = Path(tmp) / "movies.sqlite"
            df.to_csv(csv_path, index=False)

            SQLiteMovieRecommender.build_store(csv_path, store_path)
            with sqlite3.connect(store_path) as conn:
                indexes = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    )
                }

        self.assertIn("idx_movies_score_title", indexes)

    def test_sqlite_recommender_recovers_stale_build_lock(self) -> None:
        """A dead lock owner should not block future store builds."""
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B"],
                "director": ["Director A", "Director B"],
                "genres": ["Drama", "Drama"],
                "score": [9.0, 8.0],
                "actors": ["Actor X", "Actor Y"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "movies.csv"
            store_path = Path(tmp) / "movies.sqlite"
            lock_path = Path(f"{store_path}.lock")
            df.to_csv(csv_path, index=False)
            lock_path.write_text(
                f"pid=999999999\ncreated_at={time.time()}\n",
                encoding="ascii",
            )

            SQLiteMovieRecommender.build_store(csv_path, store_path)

            self.assertTrue(store_path.exists())
            self.assertFalse(lock_path.exists())

    def test_sqlite_recommender_does_not_stale_live_lock_by_age(self) -> None:
        """An old lock with a live owner PID should not be expired by age alone."""
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "movies.sqlite.lock"
            lock_path.write_text(
                f"pid={os.getpid()}\ncreated_at={time.time() - 3600}\n",
                encoding="ascii",
            )

            is_stale = SQLiteMovieRecommender._lock_is_stale(lock_path)

        self.assertFalse(is_stale)

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
            with sqlite3.connect(store_path) as conn:
                candidates = rec._candidate_tconsts(
                    conn,
                    "row:1",
                    ["action", "actora", "directora"],
                    1,
                )
        finally:
            os.unlink(tmp.name)
            if os.path.exists(store_path):
                os.unlink(store_path)

        self.assertEqual(result, ["Movie B", "Movie D", "Movie C"])
        self.assertEqual(candidates, ["row:2"])

    def test_sqlite_recommender_limits_distinct_candidate_movies(self) -> None:
        """Duplicate term matches should not consume the candidate movie cap."""
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B", "Movie C"],
                "director": ["Aab", "Aab", "Aab"],
                "genres": ["Aaa", "Aaa", "Other"],
                "score": [9.0, 8.0, 7.0],
                "actors": ["Actor A", "Actor B", "Actor C"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        store_path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
        os.unlink(store_path)
        try:
            SQLiteMovieRecommender.from_csv(
                Path(tmp.name),
                store_path,
                candidate_limit=2,
            )
            with sqlite3.connect(store_path) as conn:
                candidates = SQLiteMovieRecommender._candidate_tconsts(
                    conn,
                    "row:1",
                    ["aaa", "aab"],
                    2,
                )
        finally:
            os.unlink(tmp.name)
            if os.path.exists(store_path):
                os.unlink(store_path)

        self.assertEqual(candidates, ["row:2", "row:3"])

    def test_sqlite_recommender_selects_candidates_by_overlap_before_limit(
        self,
    ) -> None:
        """A higher-overlap candidate should win before candidate_limit is applied."""
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B", "Movie C", "Movie D"],
                "director": ["Aab", "Aab", "Aab", "Aab"],
                "genres": ["Aaa", "Other", "Other", "Aaa"],
                "score": [9.0, 8.0, 7.0, 1.0],
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
            result = rec.recommend("Movie A", top_n=1)
            with sqlite3.connect(store_path) as conn:
                candidates = SQLiteMovieRecommender._candidate_tconsts(
                    conn,
                    "row:1",
                    ["aaa", "aab"],
                    1,
                )
        finally:
            os.unlink(tmp.name)
            if os.path.exists(store_path):
                os.unlink(store_path)

        self.assertEqual(candidates, ["row:4"])
        self.assertEqual(result, ["Movie D"])

    def test_sqlite_recommender_ranks_candidate_limit_before_top_n(self) -> None:
        """Candidates beyond top_n but within candidate_limit should be ranked."""
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B", "Movie C", "Movie D", "Movie E"],
                "director": [
                    "Director A",
                    "Director B",
                    "Director C",
                    "Director D",
                    "Director E",
                ],
                "genres": ["Action", "Action", "Action", "Action", "Action"],
                "score": [9.0, 1.0, 2.0, 8.0, 10.0],
                "actors": ["Actor A", "Actor B", "Actor C", "Actor D", "Actor E"],
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
                candidate_limit=4,
            )
            result = rec.recommend("Movie A", top_n=2)
        finally:
            os.unlink(tmp.name)
            if os.path.exists(store_path):
                os.unlink(store_path)

        self.assertEqual(result, ["Movie E", "Movie D"])

    def test_cli_imports_sqlite_recommender_directly(self) -> None:
        """The CLI should import the packaged SQLite recommender directly."""
        cli_source = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "movie_recommender"
            / "cli"
            / "recommender.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "from movie_recommender.recommenders.sqlite_recommender import "
            "SQLiteMovieRecommender",
            cli_source,
        )
        self.assertNotIn("from src import SQLiteMovieRecommender", cli_source)


if __name__ == "__main__":
    unittest.main()
