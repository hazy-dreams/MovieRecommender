from __future__ import annotations

import json
from pathlib import Path

import pytest

from movie_recommender.storage.postgres import (
    EmbeddingConfig,
    SCHEMA_PATH,
    build_ann_index_sql,
    load_fixture,
    render_fuzzy_title_search_sql,
    render_vector_recommendations_sql,
    validate_fixture_vectors,
)


def test_schema_defines_serving_contract_tables_and_extensions() -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    for extension in ("pg_trgm", "vector"):
        assert f"CREATE EXTENSION IF NOT EXISTS {extension};" in schema_sql

    for table_name in (
        "source_snapshots",
        "etl_runs",
        "etl_run_sources",
        "row_provenance",
        "movies",
        "movie_external_ids",
        "people",
        "person_external_ids",
        "movie_credits",
        "movie_text_features",
        "movie_embeddings",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in schema_sql

    assert "UNIQUE NULLS NOT DISTINCT" in schema_sql
    assert "gin_trgm_ops" in schema_sql
    assert "CHECK (vector_dims(embedding) = vector_dimension)" in schema_sql


def test_vector_query_uses_literal_serving_slice_predicates() -> None:
    config = EmbeddingConfig(
        feature_name="recommendation_soup",
        feature_version="v1",
        model_name="local-fixture-model",
        model_version="2026-06-12",
        vector_dimension=3,
    )

    sql = render_vector_recommendations_sql(config)

    assert "e.embedding::vector(3) <=> q.embedding" in sql
    assert "e.model_name = 'local-fixture-model'" in sql
    assert "e.model_version = '2026-06-12'" in sql
    assert "e.vector_dimension = 3" in sql
    assert "e.feature_name = 'recommendation_soup'" in sql
    assert "e.feature_version = 'v1'" in sql
    assert "JOIN movies qm ON qm.tconst = e.tconst" in sql
    assert "qm.active" in sql
    assert "%(query_tconst)s" in sql
    assert "%(candidate_limit)s" in sql


def test_ann_index_sql_scopes_to_configured_embedding_space() -> None:
    config = EmbeddingConfig(
        feature_name="recommendation_soup",
        feature_version="v1",
        model_name="local-fixture-model",
        model_version="2026-06-12",
        vector_dimension=3,
    )

    sql = build_ann_index_sql(config, index_name="idx_test_ann")

    assert "USING hnsw ((embedding::vector(3)) vector_cosine_ops)" in sql
    assert "WHERE active" in sql
    assert "feature_name = 'recommendation_soup'" in sql
    assert "model_name = 'local-fixture-model'" in sql
    assert "vector_dimension = 3" in sql


def test_ann_index_rejects_dimensions_above_pgvector_hnsw_limit() -> None:
    config = EmbeddingConfig(
        feature_name="recommendation_soup",
        feature_version="v1",
        model_name="large-model",
        model_version="v1",
        vector_dimension=3072,
    )

    with pytest.raises(ValueError, match="HNSW"):
        build_ann_index_sql(config)


def test_ann_index_default_name_is_derived_from_embedding_config() -> None:
    first_config = EmbeddingConfig(
        feature_name="recommendation_soup",
        feature_version="v1",
        model_name="local-fixture-model",
        model_version="2026-06-12",
        vector_dimension=3,
    )
    second_config = EmbeddingConfig(
        feature_name="recommendation_soup",
        feature_version="v1",
        model_name="local-fixture-model",
        model_version="2026-06-13",
        vector_dimension=4,
    )

    first_sql = build_ann_index_sql(first_config)
    second_sql = build_ann_index_sql(second_config)
    first_index_name = first_sql.split()[5]
    second_index_name = second_sql.split()[5]

    assert first_index_name != second_index_name
    assert first_index_name.startswith("idx_movie_emb_ann_recommendation_s")
    assert second_index_name.startswith("idx_movie_emb_ann_recommendation_s")
    assert len(first_index_name) <= 63
    assert len(second_index_name) <= 63


def test_ann_index_default_name_stays_under_postgres_identifier_limit() -> None:
    config = EmbeddingConfig(
        feature_name="feature_name_hits_max",
        feature_version="version_max",
        model_name="model-name-with-extra-characters",
        model_version="model-version-with-extra-characters",
        vector_dimension=2000,
    )

    sql = build_ann_index_sql(config)
    index_name = sql.split()[5]

    assert len(index_name) <= 63


def test_ann_index_default_name_stays_under_postgres_byte_limit() -> None:
    first_config = EmbeddingConfig(
        feature_name="é" * 16,
        feature_version="versión",
        model_name="modelo-con-acentos",
        model_version="versión-uno",
        vector_dimension=2000,
    )
    second_config = EmbeddingConfig(
        feature_name="é" * 16,
        feature_version="versión",
        model_name="modelo-con-acentos",
        model_version="versión-dos",
        vector_dimension=2000,
    )

    first_index_name = build_ann_index_sql(first_config).split()[5]
    second_index_name = build_ann_index_sql(second_config).split()[5]

    assert len(first_index_name.encode("utf-8")) <= 63
    assert len(second_index_name.encode("utf-8")) <= 63
    assert first_index_name != second_index_name


def test_fuzzy_title_query_uses_trigram_operators_and_stable_ordering() -> None:
    sql = render_fuzzy_title_search_sql()

    assert "similarity(display_title, %(query)s)" in sql
    assert "display_title %% %(query)s" in sql
    assert "primary_title %% %(query)s" in sql
    assert "ORDER BY title_similarity DESC" in sql
    assert "tconst ASC" in sql


def test_tiny_fixture_matches_configured_vector_dimension() -> None:
    fixture = json.loads(
        Path("fixtures/storage/tiny_serving_fixture.json").read_text(encoding="utf-8")
    )
    config = EmbeddingConfig(**fixture["embedding_config"])

    validate_fixture_vectors(fixture, config)


def test_fixture_dimension_mismatch_is_rejected() -> None:
    fixture = json.loads(
        Path("fixtures/storage/tiny_serving_fixture.json").read_text(encoding="utf-8")
    )
    config = EmbeddingConfig(
        feature_name="recommendation_soup",
        feature_version="v1",
        model_name="local-fixture-model",
        model_version="2026-06-12",
        vector_dimension=4,
    )

    with pytest.raises(ValueError, match="vector_dimension"):
        validate_fixture_vectors(fixture, config)


class RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, object] | None]] = []
        self._etl_run_id = 100
        self._source_snapshot_id = 200
        self._people: dict[str, int] = {}
        self._text_features: dict[str, int] = {}
        self._last_result: tuple[int, ...] | None = None

    def execute(self, sql: str, params: dict[str, object] | None = None) -> None:
        self.executed.append((sql, params))
        if "RETURNING etl_run_id" in sql:
            self._last_result = (self._etl_run_id,)
        elif "RETURNING source_snapshot_id" in sql:
            self._last_result = (self._source_snapshot_id,)
        elif "RETURNING person_id" in sql:
            key = str(params["nconst"])
            self._people.setdefault(key, len(self._people) + 1)
            self._last_result = (self._people[key],)
        elif "RETURNING text_feature_id" in sql:
            key = str(params["tconst"])
            self._text_features.setdefault(key, len(self._text_features) + 10)
            self._last_result = (self._text_features[key],)
        else:
            self._last_result = None

    def fetchone(self) -> tuple[int, ...]:
        assert self._last_result is not None
        return self._last_result


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_obj = RecordingCursor()
        self.commits = 0

    def cursor(self) -> RecordingCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1


def test_load_fixture_upserts_canonical_movies_text_features_and_vectors() -> None:
    fixture = json.loads(
        Path("fixtures/storage/tiny_serving_fixture.json").read_text(encoding="utf-8")
    )
    config = EmbeddingConfig(**fixture["embedding_config"])
    conn = RecordingConnection()

    load_fixture(conn, fixture, config)

    all_sql = "\n".join(sql for sql, _ in conn.cursor_obj.executed)
    assert "INSERT INTO movies" in all_sql
    assert "ON CONFLICT (tconst) DO UPDATE" in all_sql
    assert "end_year" in all_sql
    assert "end_year = EXCLUDED.end_year" in all_sql
    assert "UPDATE movies" in all_sql
    assert "tconst <> ALL(%(active_tconsts)s::text[])" in all_sql
    assert "UPDATE movie_text_features" in all_sql
    assert "UPDATE movie_embeddings" in all_sql
    assert "movie_embeddings.text_feature_id = movie_text_features.text_feature_id" in all_sql
    assert "active = false" in all_sql
    assert "DELETE FROM movie_credits" in all_sql
    assert "INSERT INTO movie_text_features" in all_sql
    assert "ON CONFLICT (tconst, feature_name, feature_version, source_text_sha256)" in all_sql
    assert "INSERT INTO movie_embeddings" in all_sql
    assert "ON CONFLICT (text_feature_id, model_name, model_version, vector_dimension)" in all_sql
    assert "INSERT INTO row_provenance" in all_sql
    assert conn.commits == 1
