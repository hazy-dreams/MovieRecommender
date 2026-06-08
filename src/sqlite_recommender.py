"""SQLite-backed bounded movie recommendation utilities."""

from __future__ import annotations

import ast
import csv
import re
import sqlite3
from collections import Counter
from pathlib import Path


class SQLiteMovieRecommender:
    """Recommend movies from a persistent SQLite preview store."""

    REQUIRED_COLUMNS = {"title", "director", "genres", "score", "actors"}
    DEFAULT_CANDIDATE_LIMIT = 500

    def __init__(
        self,
        store_path: str | Path,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> None:
        self.store_path = Path(store_path)
        self.candidate_limit = max(0, candidate_limit)

    @classmethod
    def from_csv(
        cls,
        dataset_path: str | Path,
        store_path: str | Path,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> "SQLiteMovieRecommender":
        """Build or reuse a SQLite store for ``dataset_path``."""
        dataset_path = Path(dataset_path)
        store_path = Path(store_path)
        if cls._store_needs_rebuild(dataset_path, store_path):
            cls.build_store(dataset_path, store_path)
        return cls(store_path, candidate_limit=candidate_limit)

    @staticmethod
    def _store_needs_rebuild(dataset_path: Path, store_path: Path) -> bool:
        if not store_path.exists():
            return True
        return dataset_path.stat().st_mtime > store_path.stat().st_mtime

    @classmethod
    def build_store(cls, dataset_path: str | Path, store_path: str | Path) -> Path:
        """Stream a reduced CSV into an indexed SQLite recommendation store."""
        dataset_path = Path(dataset_path)
        store_path = Path(store_path)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        title_counts = cls._count_titles(dataset_path)

        tmp_path = store_path.with_name(f"{store_path.name}.tmp")
        if tmp_path.exists():
            tmp_path.unlink()

        with sqlite3.connect(tmp_path) as conn:
            conn.executescript(
                """
                CREATE TABLE movies (
                    tconst TEXT PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    primary_title TEXT,
                    director TEXT,
                    genres TEXT,
                    actors TEXT,
                    score REAL NOT NULL
                );
                CREATE TABLE movie_terms (
                    term TEXT NOT NULL,
                    tconst TEXT NOT NULL,
                    PRIMARY KEY (term, tconst),
                    FOREIGN KEY (tconst) REFERENCES movies(tconst)
                );
                CREATE INDEX idx_movies_title ON movies(title);
                CREATE INDEX idx_movie_terms_tconst ON movie_terms(tconst);
                """
            )
            with dataset_path.open(newline="", encoding="utf-8") as csv_file:
                reader = csv.DictReader(csv_file)
                cls._validate_columns(reader.fieldnames)
                for row_number, row in enumerate(reader, start=1):
                    movie = cls._movie_from_row(row, row_number, title_counts)
                    conn.execute(
                        """
                        INSERT INTO movies (
                            tconst, title, primary_title, director, genres, actors, score
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        movie,
                    )
                    terms = cls._terms_for_row(row)
                    conn.executemany(
                        "INSERT OR IGNORE INTO movie_terms (term, tconst) VALUES (?, ?)",
                        [(term, movie[0]) for term in terms],
                    )
            conn.commit()
        tmp_path.replace(store_path)
        return store_path

    @classmethod
    def _count_titles(cls, dataset_path: Path) -> Counter[str]:
        with dataset_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            cls._validate_columns(reader.fieldnames)
            return Counter(row["title"] for row in reader)

    @classmethod
    def _validate_columns(cls, fieldnames: list[str] | None) -> None:
        if fieldnames is None:
            raise ValueError("Dataset is missing a header row.")
        missing_columns = sorted(cls.REQUIRED_COLUMNS - set(fieldnames))
        if missing_columns:
            raise ValueError(
                "Dataset is missing required column(s): " + ", ".join(missing_columns)
            )

    @classmethod
    def _movie_from_row(
        cls,
        row: dict[str, str],
        row_number: int,
        title_counts: Counter[str],
    ) -> tuple[str, str, str, str, str, str, float]:
        tconst = row.get("tconst") or f"row:{row_number}"
        title = row["title"]
        if title_counts[title] > 1:
            if not row.get("tconst"):
                raise ValueError(
                    "Dataset contains duplicate title values and no tconst values to "
                    "disambiguate them."
                )
            title = f"{title} ({row['tconst']})"
        return (
            tconst,
            title,
            row.get("primary_title", title),
            row.get("director", ""),
            row.get("genres", ""),
            row.get("actors", ""),
            float(row["score"]),
        )

    @classmethod
    def _terms_for_row(cls, row: dict[str, str]) -> set[str]:
        terms: set[str] = set()
        for column in ["actors", "director", "genres"]:
            for value in cls._parse_values(row.get(column, "")):
                term = cls._normalize(value)
                if term:
                    terms.add(term)
        return terms

    @staticmethod
    def _parse_values(value: object) -> list[str]:
        if value is None:
            return []
        text = str(value)
        if not text:
            return []
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = text
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def recommend(self, title: str, top_n: int = 10) -> list[str]:
        """Return ``top_n`` movie titles similar to ``title``."""
        top_n = max(0, top_n)
        with sqlite3.connect(self.store_path) as conn:
            movie = conn.execute(
                "SELECT tconst FROM movies WHERE title = ?",
                (title,),
            ).fetchone()
            if movie is None:
                raise ValueError("This movie is not in the dataset.")

            tconst = movie[0]
            query_terms = [
                row[0]
                for row in conn.execute(
                    "SELECT term FROM movie_terms WHERE tconst = ?",
                    (tconst,),
                )
            ]
            recommendations = self._recommend_from_terms(
                conn, tconst, query_terms, top_n
            )
            if len(recommendations) < top_n:
                recommendations.extend(
                    self._fallback_by_score(
                        conn,
                        tconst,
                        recommendations,
                        top_n - len(recommendations),
                    )
                )
            return recommendations

    def _recommend_from_terms(
        self,
        conn: sqlite3.Connection,
        tconst: str,
        query_terms: list[str],
        top_n: int,
    ) -> list[str]:
        if not query_terms:
            return []
        limit = min(top_n, self.candidate_limit)
        if limit == 0:
            return []
        placeholders = ",".join("?" for _ in query_terms)
        rows = conn.execute(
            f"""
            SELECT m.title
            FROM movie_terms mt
            JOIN movies m ON m.tconst = mt.tconst
            WHERE mt.term IN ({placeholders})
              AND m.tconst != ?
            GROUP BY m.tconst
            ORDER BY COUNT(*) DESC, m.score DESC, m.title ASC
            LIMIT ?
            """,
            [*query_terms, tconst, limit],
        )
        return [row[0] for row in rows]

    @staticmethod
    def _fallback_by_score(
        conn: sqlite3.Connection,
        tconst: str,
        existing_titles: list[str],
        limit: int,
    ) -> list[str]:
        if limit <= 0:
            return []
        title_placeholders = ",".join("?" for _ in existing_titles)
        title_filter = ""
        params: list[object] = [tconst]
        if existing_titles:
            title_filter = f"AND title NOT IN ({title_placeholders})"
            params.extend(existing_titles)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT title
            FROM movies
            WHERE tconst != ?
              {title_filter}
            ORDER BY score DESC, title ASC
            LIMIT ?
            """,
            params,
        )
        return [row[0] for row in rows]
