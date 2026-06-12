"""Offline TMDB text enrichment keyed by canonical IMDb IDs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


DEFAULT_CACHE_PATH = Path("data/tmdb/tmdb_enrichment.sqlite")
DEFAULT_LANGUAGE = "en-US"
SOURCE = "tmdb"
SOURCE_API_VERSION = "v3"
SKIP_STATUSES = {"fetched", "missing", "ambiguous"}


@dataclass(frozen=True)
class TMDBEnrichmentResult:
    """Result for one enrichment attempt."""

    tconst: str
    status: str
    tmdb_id: int | None = None
    imdb_id: str | None = None
    title: str | None = None
    original_title: str | None = None
    release_date: str | None = None
    original_language: str | None = None
    overview: str | None = None
    tagline: str | None = None
    keywords: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    error: str | None = None


class TMDBRequestError(RuntimeError):
    """Run-level TMDB request failure."""


class TMDBClient:
    """Small TMDB API v3 client for offline enrichment jobs."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(
        self,
        api_key: str,
        language: str = DEFAULT_LANGUAGE,
        timeout_seconds: int = 20,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.language = language
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.sleep = sleep

    def _request(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        query = dict(params or {})
        query["api_key"] = self.api_key
        url = f"{self.BASE_URL}{path}?{urlencode(query)}"
        request = Request(url, headers={"Accept": "application/json"})

        attempts = 0
        while True:
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise TMDBRequestError(
                            f"TMDB response was not a JSON object: {self.BASE_URL}{path}"
                        )
                    return payload
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TMDBRequestError(
                    f"TMDB response was not valid JSON: {self.BASE_URL}{path}"
                ) from exc
            except HTTPError as exc:
                attempts += 1
                if exc.code == 429 and attempts <= self.max_retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = _parse_retry_after(retry_after, attempts)
                    self.sleep(delay)
                    continue
                raise TMDBRequestError(
                    f"TMDB request failed with HTTP {exc.code}: {self.BASE_URL}{path}"
                ) from exc
            except (TimeoutError, URLError) as exc:
                attempts += 1
                if attempts <= self.max_retries:
                    self.sleep(float(attempts))
                    continue
                raise TMDBRequestError(f"TMDB request failed: {exc}") from exc

    def find_by_imdb_id(self, tconst: str) -> list[dict[str, object]]:
        """Map an IMDb title ID to TMDB movie results."""
        data = self._request(
            f"/find/{quote(tconst)}",
            {"external_source": "imdb_id"},
        )
        movie_results = data.get("movie_results")
        if movie_results is None:
            raise TMDBRequestError("TMDB find response missing movie_results")
        if not isinstance(movie_results, list):
            raise TMDBRequestError("TMDB find response movie_results was not a list")
        valid_results = [result for result in movie_results if isinstance(result, dict)]
        if len(valid_results) != len(movie_results):
            raise TMDBRequestError("TMDB find response had malformed movie results")
        return valid_results

    def movie_details(self, tmdb_id: int) -> dict[str, object]:
        """Fetch TMDB movie details plus keyword names."""
        return self._request(
            f"/movie/{tmdb_id}",
            {"append_to_response": "keywords", "language": self.language},
        )


class TMDBEnrichmentCache:
    """SQLite cache for resumable TMDB enrichment runs."""

    def __init__(
        self,
        path: str | Path = DEFAULT_CACHE_PATH,
        source_language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self.path = Path(path)
        self.source_language = source_language
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tmdb_enrichment (
                    tconst TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_api_version TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    tmdb_id INTEGER,
                    imdb_id TEXT,
                    title TEXT,
                    original_title TEXT,
                    release_date TEXT,
                    original_language TEXT,
                    overview TEXT,
                    tagline TEXT,
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    genres_json TEXT NOT NULL DEFAULT '[]',
                    combined_text TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL,
                    payload_hash TEXT,
                    run_id TEXT,
                    PRIMARY KEY (
                        tconst,
                        source,
                        source_api_version,
                        source_language
                    )
                )
                """
            )

    def get(self, tconst: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tmdb_enrichment
                WHERE tconst = ?
                  AND source = ?
                  AND source_api_version = ?
                  AND source_language = ?
                """,
                (tconst, SOURCE, SOURCE_API_VERSION, self.source_language),
            ).fetchone()
        return dict(row) if row else None

    def upsert(self, result: TMDBEnrichmentResult, run_id: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        keywords = list(result.keywords)
        genres = list(result.genres)
        combined_text = _combined_text(result.overview, result.tagline, keywords, genres)
        payload_hash = _payload_hash(
            {
                "status": result.status,
                "tmdb_id": result.tmdb_id,
                "imdb_id": result.imdb_id,
                "overview": result.overview,
                "tagline": result.tagline,
                "keywords": keywords,
                "genres": genres,
                "error": result.error,
            }
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tmdb_enrichment (
                    tconst,
                    source,
                    source_api_version,
                    source_language,
                    status,
                    error,
                    tmdb_id,
                    imdb_id,
                    title,
                    original_title,
                    release_date,
                    original_language,
                    overview,
                    tagline,
                    keywords_json,
                    genres_json,
                    combined_text,
                    fetched_at,
                    payload_hash,
                    run_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    tconst,
                    source,
                    source_api_version,
                    source_language
                ) DO UPDATE SET
                    status = excluded.status,
                    error = excluded.error,
                    tmdb_id = excluded.tmdb_id,
                    imdb_id = excluded.imdb_id,
                    title = excluded.title,
                    original_title = excluded.original_title,
                    release_date = excluded.release_date,
                    original_language = excluded.original_language,
                    overview = excluded.overview,
                    tagline = excluded.tagline,
                    keywords_json = excluded.keywords_json,
                    genres_json = excluded.genres_json,
                    combined_text = excluded.combined_text,
                    fetched_at = excluded.fetched_at,
                    payload_hash = excluded.payload_hash,
                    run_id = excluded.run_id
                """,
                (
                    result.tconst,
                    SOURCE,
                    SOURCE_API_VERSION,
                    self.source_language,
                    result.status,
                    result.error,
                    result.tmdb_id,
                    result.imdb_id,
                    result.title,
                    result.original_title,
                    result.release_date,
                    result.original_language,
                    result.overview,
                    result.tagline,
                    json.dumps(keywords),
                    json.dumps(genres),
                    combined_text,
                    now,
                    payload_hash,
                    run_id,
                ),
            )

    def list_rows(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tmdb_enrichment ORDER BY tconst"
            ).fetchall()
        return [dict(row) for row in rows]


class TMDBMovieEnricher:
    """Enrich one canonical movie row through TMDB."""

    def __init__(
        self,
        client: TMDBClient,
        cache: TMDBEnrichmentCache,
        run_id: str | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.run_id = run_id

    def enrich_movie(
        self,
        row: dict[str, object],
        force: bool = False,
    ) -> TMDBEnrichmentResult:
        tconst = str(row.get("tconst") or "").strip()
        if not tconst:
            raise ValueError("input row is missing tconst")

        cached = self.cache.get(tconst)
        if cached and not force and cached["status"] in SKIP_STATUSES:
            return TMDBEnrichmentResult(tconst=tconst, status="skipped")

        try:
            candidates = self.client.find_by_imdb_id(tconst)
            selected = _select_candidate(candidates, row)
            if not candidates:
                result = TMDBEnrichmentResult(tconst=tconst, status="missing")
            elif selected is None:
                result = TMDBEnrichmentResult(
                    tconst=tconst,
                    status="ambiguous",
                    error="TMDB movie result failed title/year sanity checks",
                )
            else:
                details = self.client.movie_details(int(selected["id"]))
                result = _result_from_details(tconst, details, selected)
        except TMDBRequestError:
            raise
        except Exception as exc:
            result = TMDBEnrichmentResult(tconst=tconst, status="error", error=str(exc))

        if result.status == "error" and cached and cached["status"] == "fetched":
            return result

        self.cache.upsert(result, run_id=self.run_id)
        return result


def enrich_csv(
    input_path: str | Path,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    api_key: str | None = None,
    limit: int | None = None,
    force: bool = False,
    run_id: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    output=sys.stdout,
) -> dict[str, int]:
    """Enrich rows from a reduced CSV artifact and return status counts."""
    if not api_key:
        raise ValueError("TMDB_API_KEY is required for live TMDB enrichment")

    rows = _read_input_rows(input_path)
    if limit is not None:
        rows = rows[:limit]

    cache = TMDBEnrichmentCache(cache_path, source_language=language)
    client = TMDBClient(api_key, language=language)
    enricher = TMDBMovieEnricher(client, cache, run_id=run_id)
    counts: dict[str, int] = {}
    for row in rows:
        result = enricher.enrich_movie(row, force=force)
        counts[result.status] = counts.get(result.status, 0) + 1
        print(f"{result.tconst}\t{result.status}", file=output)
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich a reduced movie CSV with TMDB plot/theme text."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Reduced CSV artifact containing canonical tconst values.",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"SQLite cache/output path. Default: {DEFAULT_CACHE_PATH}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum input rows to process.",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help=f"TMDB source language. Default: {DEFAULT_LANGUAGE}",
    )
    parser.add_argument(
        "--run-id",
        help="Optional operator-provided run/config identifier.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh rows even when a final cached status already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate input and print the local plan without calling TMDB.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    rows = _read_input_rows(args.input)
    selected_rows = rows[: args.limit] if args.limit is not None else rows
    if args.dry_run:
        print(f"Would enrich {len(selected_rows)} movie rows from {args.input}.")
        print(f"Would store TMDB cache/output at {args.cache}.")
        print("No TMDB requests made.")
        return 0

    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        parser.error("TMDB_API_KEY is required for live TMDB enrichment")

    try:
        counts = enrich_csv(
            args.input,
            cache_path=args.cache,
            api_key=api_key,
            limit=args.limit,
            force=args.force,
            run_id=args.run_id,
            language=args.language,
        )
    except TMDBRequestError as exc:
        parser.exit(1, f"tmdb_enrichment.py: error: {exc}\n")
    print("Summary: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    return 0


def _read_input_rows(input_path: str | Path) -> list[dict[str, object]]:
    path = Path(input_path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "tconst" not in reader.fieldnames:
            raise ValueError("input CSV must include a tconst column")
        return [dict(row) for row in reader]


def _parse_retry_after(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            pass
    return float(attempt)


def _select_candidate(
    candidates: list[dict[str, object]],
    row: dict[str, object],
) -> dict[str, object] | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    input_title = _input_title(row)
    input_year = _input_year(row)
    if not input_title and not input_year:
        return candidates[0] if len(candidates) == 1 else None

    sane_candidates = [
        candidate
        for candidate in candidates
        if _title_matches(input_title, candidate)
        and _year_matches(input_year, candidate.get("release_date"))
    ]
    return sane_candidates[0] if len(sane_candidates) == 1 else None


def _input_title(row: dict[str, object]) -> str | None:
    for key in ("primary_title", "primaryTitle", "title"):
        value = str(row.get(key) or "").strip()
        if value:
            return re.sub(r"\s+\(tt\d+\)$", "", value)
    return None


def _input_year(row: dict[str, object]) -> str | None:
    for key in ("startYear", "release_year", "year"):
        value = str(row.get(key) or "").strip()
        if re.fullmatch(r"\d{4}", value):
            return value
    return None


def _title_matches(input_title: str | None, candidate: dict[str, object]) -> bool:
    if not input_title:
        return True
    normalized_input = _normalize_title(input_title)
    candidate_titles = [
        _normalize_title(str(candidate.get("title") or "")),
        _normalize_title(str(candidate.get("original_title") or "")),
    ]
    return normalized_input in candidate_titles


def _year_matches(input_year: str | None, release_date: object) -> bool:
    if not input_year:
        return True
    release_year = str(release_date or "")[:4]
    return bool(re.fullmatch(r"\d{4}", release_year)) and release_year == input_year


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _result_from_details(
    tconst: str,
    details: dict[str, object],
    selected: dict[str, object],
) -> TMDBEnrichmentResult:
    keywords_data = details.get("keywords")
    keyword_rows: Iterable[object]
    if isinstance(keywords_data, dict):
        keyword_rows = keywords_data.get("keywords") or keywords_data.get("results") or []
    else:
        keyword_rows = []

    return TMDBEnrichmentResult(
        tconst=tconst,
        status="fetched",
        tmdb_id=_int_or_none(details.get("id") or selected.get("id")),
        imdb_id=_str_or_none(details.get("imdb_id")) or tconst,
        title=_str_or_none(details.get("title") or selected.get("title")),
        original_title=_str_or_none(
            details.get("original_title") or selected.get("original_title")
        ),
        release_date=_str_or_none(details.get("release_date") or selected.get("release_date")),
        original_language=_str_or_none(details.get("original_language")),
        overview=_str_or_none(details.get("overview")),
        tagline=_str_or_none(details.get("tagline")),
        keywords=tuple(_names(keyword_rows)),
        genres=tuple(_names(details.get("genres") or [])),
    )


def _names(rows: Iterable[object]) -> list[str]:
    names = []
    for row in rows:
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def _str_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _combined_text(
    overview: str | None,
    tagline: str | None,
    keywords: list[str],
    genres: list[str],
) -> str:
    parts = [overview or "", tagline or "", " ".join(keywords), " ".join(genres)]
    return "\n".join(part for part in parts if part.strip())


def _payload_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
