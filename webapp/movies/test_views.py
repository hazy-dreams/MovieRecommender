import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp.settings")
import django
django.setup()

import pandas as pd
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from movies.views import get_recommender, _load_existing_store, _load_recommender


class RecommenderSettingsTest(SimpleTestCase):
    """Tests for default recommender dataset configuration."""

    def test_default_dataset_path_points_to_repo_root(self):
        expected_path = Path(BASE_DIR) / "movies_10.csv"

        self.assertEqual(Path(settings.RECOMMENDER_DATASET_PATH), expected_path)

    def test_default_store_path_points_to_repo_root(self):
        expected_path = Path(BASE_DIR) / "movies_10.sqlite"

        self.assertEqual(Path(settings.RECOMMENDER_STORE_PATH), expected_path)


class GetRecommenderTest(SimpleTestCase):
    """Tests for the cached recommender helper."""

    def setUp(self):
        _load_recommender.cache_clear()
        _load_existing_store.cache_clear()

    def test_dataset_loaded_once(self):
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B"],
                "director": ["Director A", "Director B"],
                "genres": ["Drama", "Drama"],
                "score": [9.0, 8.0],
                "actors": ["Actor X", "Actor Y"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        store_path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
        os.unlink(store_path)
        try:
            with override_settings(
                RECOMMENDER_DATASET_PATH=tmp.name,
                RECOMMENDER_STORE_PATH=store_path,
            ):
                rec1 = get_recommender()
                rec2 = get_recommender()
            self.assertIs(rec1, rec2)
            self.assertTrue(Path(store_path).exists())
        finally:
            os.unlink(tmp.name)
            if Path(store_path).exists():
                os.unlink(store_path)

    def test_existing_store_loaded_without_csv(self):
        df = pd.DataFrame(
            {
                "title": ["Movie A", "Movie B"],
                "director": ["Director A", "Director B"],
                "genres": ["Drama", "Drama"],
                "score": [9.0, 8.0],
                "actors": ["Actor X", "Actor Y"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        store_path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
        os.unlink(store_path)
        try:
            with override_settings(
                RECOMMENDER_DATASET_PATH=tmp.name,
                RECOMMENDER_STORE_PATH=store_path,
            ):
                get_recommender()
            os.unlink(tmp.name)
            _load_recommender.cache_clear()
            with override_settings(
                RECOMMENDER_DATASET_PATH=tmp.name,
                RECOMMENDER_STORE_PATH=store_path,
            ):
                rec = get_recommender()
            self.assertEqual(rec.recommend("Movie A", top_n=1), ["Movie B"])
        finally:
            if Path(tmp.name).exists():
                os.unlink(tmp.name)
            if Path(store_path).exists():
                os.unlink(store_path)


if __name__ == "__main__":
    unittest.main()
