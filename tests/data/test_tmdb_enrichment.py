"""Tests for offline TMDB enrichment helpers."""

from __future__ import annotations

import csv
import json
import os
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from movie_recommender.data.tmdb_enrichment import (
    TMDBClient,
    TMDBEnrichmentCache,
    TMDBEnrichmentResult,
    TMDBMovieEnricher,
    TMDBRequestError,
    enrich_csv,
    main,
)


class FakeTMDBResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.headers = {}

    def __enter__(self) -> "FakeTMDBResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class RawTMDBResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers = {}

    def __enter__(self) -> "RawTMDBResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeTMDBClient:
    def __init__(
        self,
        find_results: dict[str, list[dict[str, object]]],
        details: dict[int, dict[str, object]] | None = None,
    ) -> None:
        self.find_results = find_results
        self.details = details or {}
        self.details_calls: list[int] = []

    def find_by_imdb_id(self, tconst: str) -> list[dict[str, object]]:
        return self.find_results[tconst]

    def movie_details(self, tmdb_id: int) -> dict[str, object]:
        self.details_calls.append(tmdb_id)
        return self.details[tmdb_id]


class TMDBEnrichmentTest(unittest.TestCase):
    def test_enricher_fetches_details_and_upserts_by_tconst(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "tmdb.sqlite"
            cache = TMDBEnrichmentCache(cache_path)
            client = FakeTMDBClient(
                {
                    "tt1375666": [
                        {
                            "id": 27205,
                            "title": "Inception",
                            "original_title": "Inception",
                            "release_date": "2010-07-15",
                        }
                    ]
                },
                {
                    27205: {
                        "id": 27205,
                        "imdb_id": "tt1375666",
                        "title": "Inception",
                        "original_title": "Inception",
                        "release_date": "2010-07-15",
                        "original_language": "en",
                        "overview": "A thief steals corporate secrets through dreams.",
                        "tagline": "Your mind is the scene of the crime.",
                        "genres": [{"id": 28, "name": "Action"}],
                        "keywords": {
                            "keywords": [
                                {"id": 101, "name": "dream"},
                                {"id": 102, "name": "subconscious"},
                            ]
                        },
                    }
                },
            )
            enricher = TMDBMovieEnricher(client, cache, run_id="test-run")

            first = enricher.enrich_movie(
                {"tconst": "tt1375666", "primary_title": "Inception", "startYear": "2010"}
            )
            second = enricher.enrich_movie(
                {"tconst": "tt1375666", "primary_title": "Inception", "startYear": "2010"}
            )

            with sqlite3.connect(cache_path) as conn:
                rows = conn.execute(
                    "SELECT tconst, status, tmdb_id, overview, keywords_json, "
                    "genres_json, source, source_api_version, source_language, run_id "
                    "FROM tmdb_enrichment"
                ).fetchall()

        self.assertEqual(first.status, "fetched")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(client.details_calls, [27205])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0:4], ("tt1375666", "fetched", 27205, first.overview))
        self.assertEqual(json.loads(rows[0][4]), ["dream", "subconscious"])
        self.assertEqual(json.loads(rows[0][5]), ["Action"])
        self.assertEqual(rows[0][6:10], ("tmdb", "v3", "en-US", "test-run"))

    def test_missing_and_ambiguous_results_are_recorded_without_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = TMDBEnrichmentCache(Path(tmp) / "tmdb.sqlite")
            client = FakeTMDBClient(
                {
                    "tt0000001": [],
                    "tt0000002": [
                        {
                            "id": 1,
                            "title": "Wrong Movie",
                            "original_title": "Wrong Movie",
                            "release_date": "2001-01-01",
                        }
                    ],
                }
            )
            enricher = TMDBMovieEnricher(client, cache)

            missing = enricher.enrich_movie({"tconst": "tt0000001", "primary_title": "Sample Movie"})
            ambiguous = enricher.enrich_movie(
                {"tconst": "tt0000002", "primary_title": "Sample Sequel", "startYear": "2000"}
            )

            rows = cache.list_rows()

        self.assertEqual(missing.status, "missing")
        self.assertEqual(ambiguous.status, "ambiguous")
        self.assertEqual(client.details_calls, [])
        self.assertEqual(
            [(row["tconst"], row["status"]) for row in rows],
            [("tt0000001", "missing"), ("tt0000002", "ambiguous")],
        )

    def test_client_retries_429_with_retry_after(self) -> None:
        retry_error = HTTPError(
            url="https://api.themoviedb.org/3/find/tt1375666",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "2"},
            fp=None,
        )
        sleep = Mock()

        with patch(
            "movie_recommender.data.tmdb_enrichment.urlopen",
            side_effect=[retry_error, FakeTMDBResponse({"movie_results": []})],
        ):
            client = TMDBClient("test-key", sleep=sleep, max_retries=1)
            result = client.find_by_imdb_id("tt1375666")

        self.assertEqual(result, [])
        sleep.assert_called_once_with(2.0)

    def test_client_error_does_not_include_api_key(self) -> None:
        http_error = HTTPError(
            url="https://api.themoviedb.org/3/find/tt1375666",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=None,
        )

        with patch("movie_recommender.data.tmdb_enrichment.urlopen", side_effect=http_error):
            client = TMDBClient("secret-api-key", max_retries=0)
            with self.assertRaises(RuntimeError) as error:
                client.find_by_imdb_id("tt1375666")

        self.assertNotIn("secret-api-key", str(error.exception))

    def test_malformed_json_response_is_request_failure(self) -> None:
        with patch(
            "movie_recommender.data.tmdb_enrichment.urlopen",
            return_value=RawTMDBResponse(b""),
        ):
            client = TMDBClient("test-key", max_retries=0)
            with self.assertRaises(TMDBRequestError):
                client.find_by_imdb_id("tt1375666")

    def test_malformed_find_movie_results_are_request_failures(self) -> None:
        payloads = [
            {"movie_results": {"id": 27205}},
            {"movie_results": ["not-a-result"]},
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                with patch(
                    "movie_recommender.data.tmdb_enrichment.urlopen",
                    return_value=FakeTMDBResponse(payload),
                ):
                    client = TMDBClient("test-key", max_retries=0)
                    with self.assertRaises(TMDBRequestError):
                        client.find_by_imdb_id("tt1375666")

    def test_error_status_is_retried_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = TMDBEnrichmentCache(Path(tmp) / "tmdb.sqlite")
            client = FakeTMDBClient({"tt0000001": []})
            enricher = TMDBMovieEnricher(client, cache)

            cache.upsert(TMDBEnrichmentResult(tconst="tt0000001", status="error", error="temporary"))
            result = enricher.enrich_movie({"tconst": "tt0000001", "primary_title": "Sample Movie"})

        self.assertEqual(result.status, "missing")

    def test_tmdb_request_failure_aborts_csv_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "movies.csv"
            cache_path = Path(tmp) / "tmdb.sqlite"
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["tconst", "primary_title"])
                writer.writeheader()
                writer.writerow({"tconst": "tt0000001", "primary_title": "Sample Movie"})

            with patch.object(
                TMDBClient,
                "find_by_imdb_id",
                side_effect=TMDBRequestError("TMDB request failed with HTTP 401"),
            ):
                with self.assertRaises(TMDBRequestError):
                    enrich_csv(input_path, cache_path=cache_path, api_key="bad-key")

            rows = TMDBEnrichmentCache(cache_path).list_rows()

        self.assertEqual(rows, [])

    def test_cli_exits_nonzero_on_tmdb_request_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "movies.csv"
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["tconst", "primary_title"])
                writer.writeheader()
                writer.writerow({"tconst": "tt0000001", "primary_title": "Sample Movie"})

            stderr = StringIO()
            with patch.dict(os.environ, {"TMDB_API_KEY": "bad-key"}):
                with patch(
                    "movie_recommender.data.tmdb_enrichment.enrich_csv",
                    side_effect=TMDBRequestError("TMDB request failed with HTTP 401"),
                ):
                    with redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as exit_error:
                            main(["--input", str(input_path)])

        self.assertEqual(exit_error.exception.code, 1)
        self.assertIn("TMDB request failed with HTTP 401", stderr.getvalue())

    def test_force_refresh_failure_preserves_existing_fetched_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = TMDBEnrichmentCache(Path(tmp) / "tmdb.sqlite")
            cache.upsert(
                TMDBEnrichmentResult(
                    tconst="tt1375666",
                    status="fetched",
                    tmdb_id=27205,
                    overview="Existing overview",
                    keywords=("dream",),
                    genres=("Action",),
                )
            )
            client = FakeTMDBClient({"tt1375666": []})
            client.find_by_imdb_id = Mock(
                side_effect=TMDBRequestError("TMDB request failed")
            )
            enricher = TMDBMovieEnricher(client, cache)

            with self.assertRaises(TMDBRequestError):
                enricher.enrich_movie(
                    {"tconst": "tt1375666", "primary_title": "Inception"},
                    force=True,
                )

            row = cache.get("tt1375666")

        self.assertEqual(row["status"], "fetched")
        self.assertEqual(row["overview"], "Existing overview")
        self.assertEqual(json.loads(row["keywords_json"]), ["dream"])

    def test_force_refresh_row_error_preserves_existing_fetched_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = TMDBEnrichmentCache(Path(tmp) / "tmdb.sqlite")
            cache.upsert(
                TMDBEnrichmentResult(
                    tconst="tt1375666",
                    status="fetched",
                    tmdb_id=27205,
                    overview="Existing overview",
                    keywords=("dream",),
                    genres=("Action",),
                )
            )
            client = FakeTMDBClient(
                {
                    "tt1375666": [
                        {
                            "title": "Inception",
                            "original_title": "Inception",
                            "release_date": "2010-07-15",
                        }
                    ]
                }
            )
            enricher = TMDBMovieEnricher(client, cache)

            result = enricher.enrich_movie(
                {"tconst": "tt1375666", "primary_title": "Inception"},
                force=True,
            )
            row = cache.get("tt1375666")

        self.assertEqual(result.status, "error")
        self.assertEqual(row["status"], "fetched")
        self.assertEqual(row["overview"], "Existing overview")
        self.assertEqual(json.loads(row["keywords_json"]), ["dream"])

    def test_cli_dry_run_does_not_require_api_key(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "movies.csv"
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["tconst", "primary_title"])
                writer.writeheader()
                writer.writerow({"tconst": "tt1375666", "primary_title": "Inception"})

            env = os.environ.copy()
            env.pop("TMDB_API_KEY", None)
            env["PYTHONPATH"] = str(repo_root / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "movie_recommender.cli.tmdb_enrichment",
                    "--input",
                    str(input_path),
                    "--cache",
                    str(Path(tmp) / "tmdb.sqlite"),
                    "--dry-run",
                ],
                cwd="/tmp",
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would enrich 1 movie rows", result.stdout)

    def test_cli_live_mode_requires_api_key(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env.pop("TMDB_API_KEY", None)
        env["PYTHONPATH"] = str(repo_root / "src")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "movie_recommender.cli.tmdb_enrichment",
                "--input",
                str(repo_root / "fixtures" / "recommendation_eval_movies.csv"),
            ],
            cwd="/tmp",
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("TMDB_API_KEY is required", result.stderr)


if __name__ == "__main__":
    unittest.main()
