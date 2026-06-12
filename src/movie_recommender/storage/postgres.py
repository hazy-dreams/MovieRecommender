from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"


@dataclass(frozen=True)
class EmbeddingConfig:
    feature_name: str
    feature_version: str
    model_name: str
    model_version: str
    vector_dimension: int

    def __post_init__(self) -> None:
        if self.vector_dimension <= 0:
            raise ValueError("vector_dimension must be positive")


def apply_schema(conn: Any, schema_path: Path = SCHEMA_PATH) -> None:
    conn.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def render_fuzzy_title_search_sql() -> str:
    return """
SELECT tconst, display_title, primary_title, start_year, weighted_score,
       GREATEST(
           similarity(display_title, %(query)s),
           similarity(primary_title, %(query)s)
       ) AS title_similarity
FROM movies
WHERE active
  AND (
      display_title %% %(query)s
      OR primary_title %% %(query)s
  )
ORDER BY title_similarity DESC,
         weighted_score DESC NULLS LAST,
         display_title ASC,
         tconst ASC
LIMIT %(limit)s;
""".strip()


def render_vector_recommendations_sql(config: EmbeddingConfig) -> str:
    dimension = _sql_dimension(config.vector_dimension)
    feature_name = _sql_literal(config.feature_name)
    feature_version = _sql_literal(config.feature_version)
    model_name = _sql_literal(config.model_name)
    model_version = _sql_literal(config.model_version)

    return f"""
WITH query_embedding AS (
    SELECT e.embedding::vector({dimension}) AS embedding
    FROM movie_embeddings e
    JOIN movie_text_features tf
      ON tf.text_feature_id = e.text_feature_id
     AND tf.tconst = e.tconst
     AND tf.feature_name = e.feature_name
     AND tf.feature_version = e.feature_version
     AND tf.source_text_sha256 = e.source_text_sha256
    WHERE e.tconst = %(query_tconst)s
      AND e.active
      AND e.model_name = {model_name}
      AND e.model_version = {model_version}
      AND e.vector_dimension = {dimension}
      AND e.feature_name = {feature_name}
      AND e.feature_version = {feature_version}
      AND tf.active
)
SELECT m.tconst,
       m.display_title,
       m.primary_title,
       m.start_year,
       m.weighted_score,
       e.embedding::vector({dimension}) <=> q.embedding AS cosine_distance
FROM query_embedding q
JOIN movie_embeddings e
  ON e.active
 AND e.model_name = {model_name}
 AND e.model_version = {model_version}
 AND e.vector_dimension = {dimension}
 AND e.feature_name = {feature_name}
 AND e.feature_version = {feature_version}
JOIN movie_text_features tf
  ON tf.text_feature_id = e.text_feature_id
 AND tf.tconst = e.tconst
 AND tf.feature_name = e.feature_name
 AND tf.feature_version = e.feature_version
 AND tf.source_text_sha256 = e.source_text_sha256
 AND tf.active
JOIN movies m ON m.tconst = e.tconst
WHERE e.tconst <> %(query_tconst)s
  AND m.active
ORDER BY e.embedding::vector({dimension}) <=> q.embedding,
         m.weighted_score DESC NULLS LAST,
         m.display_title ASC,
         m.tconst ASC
LIMIT %(candidate_limit)s;
""".strip()


def build_ann_index_sql(
    config: EmbeddingConfig,
    *,
    index_name: str | None = None,
) -> str:
    if index_name is None:
        index_name = _default_ann_index_name(config)
    _validate_identifier(index_name)
    dimension = _sql_dimension(config.vector_dimension)
    feature_name = _sql_literal(config.feature_name)
    feature_version = _sql_literal(config.feature_version)
    model_name = _sql_literal(config.model_name)
    model_version = _sql_literal(config.model_version)

    return f"""
CREATE INDEX IF NOT EXISTS {index_name}
    ON movie_embeddings
    USING hnsw ((embedding::vector({dimension})) vector_cosine_ops)
    WHERE active
      AND feature_name = {feature_name}
      AND feature_version = {feature_version}
      AND model_name = {model_name}
      AND model_version = {model_version}
      AND vector_dimension = {dimension};
""".strip()


def search_titles(conn: Any, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(render_fuzzy_title_search_sql(), {"query": query, "limit": limit})
    return _rows_to_dicts(cur)


def vector_recommendations(
    conn: Any,
    query_tconst: str,
    config: EmbeddingConfig,
    *,
    candidate_limit: int = 10,
) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        render_vector_recommendations_sql(config),
        {"query_tconst": query_tconst, "candidate_limit": candidate_limit},
    )
    return _rows_to_dicts(cur)


def validate_fixture_vectors(fixture: dict[str, Any], config: EmbeddingConfig) -> None:
    if fixture.get("embedding_config") != {
        "feature_name": config.feature_name,
        "feature_version": config.feature_version,
        "model_name": config.model_name,
        "model_version": config.model_version,
        "vector_dimension": config.vector_dimension,
    }:
        raise ValueError(
            "fixture embedding_config does not match configured embedding space; "
            "check feature/model values and vector_dimension"
        )

    for movie in fixture["movies"]:
        vector = movie["embedding"]
        if len(vector) != config.vector_dimension:
            raise ValueError(
                f"{movie['tconst']} vector_dimension mismatch: "
                f"expected {config.vector_dimension}, got {len(vector)}"
            )


def load_fixture(conn: Any, fixture: dict[str, Any], config: EmbeddingConfig) -> None:
    validate_fixture_vectors(fixture, config)
    cur = conn.cursor()

    source_snapshot_id = _upsert_source_snapshot(cur, fixture["source_snapshot"])
    etl_run_id = _insert_etl_run(cur, fixture["etl_run"], len(fixture["movies"]))
    _insert_etl_run_source(cur, etl_run_id, source_snapshot_id)

    people_by_nconst: dict[str, int] = {}
    for person in fixture.get("people", []):
        people_by_nconst[person["nconst"]] = _upsert_person(cur, person)

    for movie in fixture["movies"]:
        _upsert_movie(cur, movie, etl_run_id)
        _upsert_movie_external_id(cur, movie["tconst"], source_snapshot_id, etl_run_id)
        _insert_movie_provenance(cur, movie, source_snapshot_id, etl_run_id)

        for credit in movie.get("credits", []):
            person_id = people_by_nconst[credit["nconst"]]
            _upsert_credit(cur, movie["tconst"], person_id, credit, source_snapshot_id, etl_run_id)

        text_feature_id = _upsert_text_feature(cur, movie, config, etl_run_id)
        _upsert_embedding(cur, movie, text_feature_id, config, etl_run_id)

    conn.commit()


def load_fixture_file(conn: Any, fixture_path: Path) -> EmbeddingConfig:
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes.decode("utf-8"))
    fixture["source_snapshot"]["content_sha256"] = hashlib.sha256(fixture_bytes).hexdigest()
    fixture["source_snapshot"]["byte_size"] = len(fixture_bytes)
    fixture["source_snapshot"]["row_count"] = len(fixture["movies"])
    config = EmbeddingConfig(**fixture["embedding_config"])
    load_fixture(conn, fixture, config)
    return config


def _upsert_source_snapshot(cur: Any, snapshot: dict[str, Any]) -> int:
    cur.execute(
        """
INSERT INTO source_snapshots (
    source_name, snapshot_name, snapshot_date, source_uri, content_sha256,
    byte_size, row_count, schema_version, notes
)
VALUES (
    %(source_name)s, %(snapshot_name)s, %(snapshot_date)s, %(source_uri)s,
    %(content_sha256)s, %(byte_size)s, %(row_count)s, %(schema_version)s, %(notes)s
)
ON CONFLICT (source_name, snapshot_name, snapshot_date, content_sha256)
DO UPDATE SET
    source_uri = EXCLUDED.source_uri,
    byte_size = EXCLUDED.byte_size,
    row_count = EXCLUDED.row_count,
    schema_version = EXCLUDED.schema_version,
    notes = EXCLUDED.notes
RETURNING source_snapshot_id;
""".strip(),
        snapshot,
    )
    return cur.fetchone()[0]


def _insert_etl_run(cur: Any, etl_run: dict[str, Any], records_written: int) -> int:
    cur.execute(
        """
INSERT INTO etl_runs (
    run_type, status, finished_at, code_version, loader_name, parameters,
    records_read, records_written
)
VALUES (
    %(run_type)s, %(status)s, now(), %(code_version)s, %(loader_name)s,
    %(parameters)s::jsonb, %(records_read)s, %(records_written)s
)
RETURNING etl_run_id;
""".strip(),
        {
            "run_type": etl_run["run_type"],
            "status": etl_run["status"],
            "code_version": etl_run.get("code_version"),
            "loader_name": etl_run["loader_name"],
            "parameters": json.dumps(etl_run.get("parameters", {})),
            "records_read": etl_run.get("records_read", records_written),
            "records_written": records_written,
        },
    )
    return cur.fetchone()[0]


def _insert_etl_run_source(cur: Any, etl_run_id: int, source_snapshot_id: int) -> None:
    cur.execute(
        """
INSERT INTO etl_run_sources (etl_run_id, source_snapshot_id, role)
VALUES (%(etl_run_id)s, %(source_snapshot_id)s, 'tiny_fixture')
ON CONFLICT DO NOTHING;
""".strip(),
        {"etl_run_id": etl_run_id, "source_snapshot_id": source_snapshot_id},
    )


def _upsert_person(cur: Any, person: dict[str, Any]) -> int:
    cur.execute(
        """
INSERT INTO people (nconst, primary_name, primary_professions, active)
VALUES (%(nconst)s, %(primary_name)s, %(primary_professions)s, true)
ON CONFLICT (nconst) DO UPDATE SET
    primary_name = EXCLUDED.primary_name,
    primary_professions = EXCLUDED.primary_professions,
    active = true,
    updated_at = now()
RETURNING person_id;
""".strip(),
        person,
    )
    return cur.fetchone()[0]


def _upsert_movie(cur: Any, movie: dict[str, Any], etl_run_id: int) -> None:
    cur.execute(
        """
INSERT INTO movies (
    tconst, primary_title, display_title, original_title, title_type, start_year,
    runtime_minutes, genres, average_rating, num_votes, weighted_score,
    is_adult, active, first_seen_etl_run_id, last_seen_etl_run_id
)
VALUES (
    %(tconst)s, %(primary_title)s, %(display_title)s, %(original_title)s,
    %(title_type)s, %(start_year)s, %(runtime_minutes)s, %(genres)s,
    %(average_rating)s, %(num_votes)s, %(weighted_score)s, %(is_adult)s,
    true, %(etl_run_id)s, %(etl_run_id)s
)
ON CONFLICT (tconst) DO UPDATE SET
    primary_title = EXCLUDED.primary_title,
    display_title = EXCLUDED.display_title,
    original_title = EXCLUDED.original_title,
    title_type = EXCLUDED.title_type,
    start_year = EXCLUDED.start_year,
    runtime_minutes = EXCLUDED.runtime_minutes,
    genres = EXCLUDED.genres,
    average_rating = EXCLUDED.average_rating,
    num_votes = EXCLUDED.num_votes,
    weighted_score = EXCLUDED.weighted_score,
    is_adult = EXCLUDED.is_adult,
    active = true,
    last_seen_etl_run_id = EXCLUDED.last_seen_etl_run_id,
    updated_at = now();
""".strip(),
        {**movie, "etl_run_id": etl_run_id},
    )


def _upsert_movie_external_id(
    cur: Any,
    tconst: str,
    source_snapshot_id: int,
    etl_run_id: int,
) -> None:
    cur.execute(
        """
INSERT INTO movie_external_ids (
    source_name, source_id, tconst, source_snapshot_id, etl_run_id
)
VALUES ('imdb', %(tconst)s, %(tconst)s, %(source_snapshot_id)s, %(etl_run_id)s)
ON CONFLICT (source_name, source_id) DO UPDATE SET
    tconst = EXCLUDED.tconst,
    source_snapshot_id = EXCLUDED.source_snapshot_id,
    etl_run_id = EXCLUDED.etl_run_id;
""".strip(),
        {
            "tconst": tconst,
            "source_snapshot_id": source_snapshot_id,
            "etl_run_id": etl_run_id,
        },
    )


def _insert_movie_provenance(
    cur: Any,
    movie: dict[str, Any],
    source_snapshot_id: int,
    etl_run_id: int,
) -> None:
    source_row_hash = hashlib.sha256(
        json.dumps(movie, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cur.execute(
        """
INSERT INTO row_provenance (
    table_name, entity_key, source_snapshot_id, source_row_key,
    source_row_hash, etl_run_id
)
VALUES (
    'movies', %(tconst)s, %(source_snapshot_id)s, %(tconst)s,
    %(source_row_hash)s, %(etl_run_id)s
);
""".strip(),
        {
            "tconst": movie["tconst"],
            "source_snapshot_id": source_snapshot_id,
            "source_row_hash": source_row_hash,
            "etl_run_id": etl_run_id,
        },
    )


def _upsert_credit(
    cur: Any,
    tconst: str,
    person_id: int,
    credit: dict[str, Any],
    source_snapshot_id: int,
    etl_run_id: int,
) -> None:
    cur.execute(
        """
INSERT INTO movie_credits (
    tconst, person_id, role_type, category, job, character_names,
    credit_order, source_name, source_snapshot_id, etl_run_id
)
VALUES (
    %(tconst)s, %(person_id)s, %(role_type)s, %(category)s, %(job)s,
    %(character_names)s, %(credit_order)s, 'tiny_fixture',
    %(source_snapshot_id)s, %(etl_run_id)s
)
ON CONFLICT (tconst, person_id, role_type, credit_order) DO UPDATE SET
    category = EXCLUDED.category,
    job = EXCLUDED.job,
    character_names = EXCLUDED.character_names,
    source_name = EXCLUDED.source_name,
    source_snapshot_id = EXCLUDED.source_snapshot_id,
    etl_run_id = EXCLUDED.etl_run_id,
    updated_at = now();
""".strip(),
        {
            **credit,
            "tconst": tconst,
            "person_id": person_id,
            "source_snapshot_id": source_snapshot_id,
            "etl_run_id": etl_run_id,
        },
    )


def _upsert_text_feature(
    cur: Any,
    movie: dict[str, Any],
    config: EmbeddingConfig,
    etl_run_id: int,
) -> int:
    source_text = movie["source_text"]
    source_text_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    cur.execute(
        """
UPDATE movie_embeddings
SET active = false
FROM movie_text_features
WHERE movie_embeddings.text_feature_id = movie_text_features.text_feature_id
  AND movie_text_features.tconst = %(tconst)s
  AND movie_text_features.feature_name = %(feature_name)s
  AND movie_text_features.feature_version = %(feature_version)s
  AND movie_text_features.source_text_sha256 <> %(source_text_sha256)s
  AND movie_text_features.active
  AND movie_embeddings.active;
""".strip(),
        {
            "tconst": movie["tconst"],
            "feature_name": config.feature_name,
            "feature_version": config.feature_version,
            "source_text_sha256": source_text_sha256,
        },
    )
    cur.execute(
        """
UPDATE movie_text_features
SET active = false
WHERE tconst = %(tconst)s
  AND feature_name = %(feature_name)s
  AND feature_version = %(feature_version)s
  AND source_text_sha256 <> %(source_text_sha256)s
  AND active;
""".strip(),
        {
            "tconst": movie["tconst"],
            "feature_name": config.feature_name,
            "feature_version": config.feature_version,
            "source_text_sha256": source_text_sha256,
        },
    )
    cur.execute(
        """
INSERT INTO movie_text_features (
    tconst, feature_name, feature_version, source_text, source_text_sha256,
    build_method, source_etl_run_id, active
)
VALUES (
    %(tconst)s, %(feature_name)s, %(feature_version)s, %(source_text)s,
    %(source_text_sha256)s, 'tiny_fixture', %(etl_run_id)s, true
)
ON CONFLICT (tconst, feature_name, feature_version, source_text_sha256)
DO UPDATE SET
    source_text = EXCLUDED.source_text,
    build_method = EXCLUDED.build_method,
    source_etl_run_id = EXCLUDED.source_etl_run_id,
    active = true
RETURNING text_feature_id;
""".strip(),
        {
            "tconst": movie["tconst"],
            "feature_name": config.feature_name,
            "feature_version": config.feature_version,
            "source_text": source_text,
            "source_text_sha256": source_text_sha256,
            "etl_run_id": etl_run_id,
        },
    )
    return cur.fetchone()[0]


def _upsert_embedding(
    cur: Any,
    movie: dict[str, Any],
    text_feature_id: int,
    config: EmbeddingConfig,
    etl_run_id: int,
) -> None:
    embedding = _format_vector(movie["embedding"])
    source_text_sha256 = hashlib.sha256(movie["source_text"].encode("utf-8")).hexdigest()
    embedding_sha256 = hashlib.sha256(embedding.encode("utf-8")).hexdigest()
    cur.execute(
        """
INSERT INTO movie_embeddings (
    text_feature_id, tconst, feature_name, feature_version, model_name,
    model_version, vector_dimension, embedding, embedding_sha256,
    source_text_sha256, embedding_etl_run_id, active
)
VALUES (
    %(text_feature_id)s, %(tconst)s, %(feature_name)s, %(feature_version)s,
    %(model_name)s, %(model_version)s, %(vector_dimension)s,
    %(embedding)s::vector, %(embedding_sha256)s, %(source_text_sha256)s,
    %(etl_run_id)s, true
)
ON CONFLICT (text_feature_id, model_name, model_version, vector_dimension)
DO UPDATE SET
    embedding = EXCLUDED.embedding,
    embedding_sha256 = EXCLUDED.embedding_sha256,
    source_text_sha256 = EXCLUDED.source_text_sha256,
    embedding_etl_run_id = EXCLUDED.embedding_etl_run_id,
    active = true;
""".strip(),
        {
            "text_feature_id": text_feature_id,
            "tconst": movie["tconst"],
            "feature_name": config.feature_name,
            "feature_version": config.feature_version,
            "model_name": config.model_name,
            "model_version": config.model_version,
            "vector_dimension": config.vector_dimension,
            "embedding": embedding,
            "embedding_sha256": embedding_sha256,
            "source_text_sha256": source_text_sha256,
            "etl_run_id": etl_run_id,
        },
    )


def _rows_to_dicts(cur: Any) -> list[dict[str, Any]]:
    columns = [column.name for column in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def _format_vector(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


def _sql_dimension(value: int) -> int:
    if value <= 0:
        raise ValueError("vector_dimension must be positive")
    return value


def _sql_literal(value: str) -> str:
    if "\x00" in value:
        raise ValueError("SQL literals cannot contain NUL bytes")
    return "'" + value.replace("'", "''") + "'"


def _default_ann_index_name(config: EmbeddingConfig) -> str:
    name_parts = [
        config.feature_name,
        config.feature_version,
        config.model_name,
        config.model_version,
        str(config.vector_dimension),
    ]
    digest = hashlib.sha256("|".join(name_parts).encode("utf-8")).hexdigest()[:12]
    feature = _identifier_fragment(config.feature_name, max_length=18)
    version = _identifier_fragment(config.feature_version, max_length=10)
    dimension = _identifier_fragment(str(config.vector_dimension), max_length=6)
    return f"idx_movie_emb_ann_{feature}_{version}_{dimension}_{digest}"


def _identifier_fragment(value: str, *, max_length: int) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value]
    fragment = "".join(chars).strip("_")
    while "__" in fragment:
        fragment = fragment.replace("__", "_")
    return (fragment or "x")[:max_length].strip("_") or "x"


def _validate_identifier(value: str) -> None:
    if not value.replace("_", "").isalnum() or value[0].isdigit():
        raise ValueError(f"invalid SQL identifier: {value!r}")
