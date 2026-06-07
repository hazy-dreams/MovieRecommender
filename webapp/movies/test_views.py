import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webapp.settings")
import django
django.setup()

import pandas as pd
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from movies.views import get_recommender, _load_recommender


class RecommenderSettingsTest(SimpleTestCase):
    """Tests for default recommender dataset configuration."""

    def test_default_dataset_path_points_to_repo_root(self):
        expected_path = Path(BASE_DIR) / "movies_10.csv"

        self.assertEqual(Path(settings.RECOMMENDER_DATASET_PATH), expected_path)


class GetRecommenderTest(SimpleTestCase):
    """Tests for the cached recommender helper."""

    def setUp(self):
        _load_recommender.cache_clear()

    def test_dataset_loaded_once(self):
        df = pd.DataFrame(
            {
                "title": ["Movie A"],
                "director": ["Director A"],
                "genres": ["Drama"],
                "score": [9.0],
                "actors": ["Actor X"],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w+") as tmp:
            df.to_csv(tmp.name, index=False)
        try:
            with override_settings(RECOMMENDER_DATASET_PATH=tmp.name):
                with patch("src.movie_recommender.MovieRecommender.load_dataset") as mock_load:
                    mock_load.return_value = df
                    rec1 = get_recommender()
                    rec2 = get_recommender()
            self.assertIs(rec1, rec2)
            mock_load.assert_called_once_with(tmp.name)
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
