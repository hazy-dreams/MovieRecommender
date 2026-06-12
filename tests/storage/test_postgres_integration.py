from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from movie_recommender.storage.postgres import (
    EmbeddingConfig,
    apply_schema,
    build_ann_index_sql,
    load_fixture,
    search_titles,
    vector_recommendations,
)


@pytest.mark.skipif(
    not os.environ.get("POSTGRES_TEST_DSN"),
    reason="set POSTGRES_TEST_DSN to run Postgres/pgvector integration tests",
)
def test_tiny_fixture_search_vector_and_provenance_round_trip() -> None:
    psycopg = pytest.importorskip("psycopg")
    fixture = json.loads(
        Path("fixtures/storage/tiny_serving_fixture.json").read_text(encoding="utf-8")
    )
    config = EmbeddingConfig(**fixture["embedding_config"])

    with psycopg.connect(os.environ["POSTGRES_TEST_DSN"]) as conn:
        apply_schema(conn)
        load_fixture(conn, fixture, config)
        conn.execute(build_ann_index_sql(config))
        conn.commit()

        title_rows = search_titles(conn, "Arival", limit=5)
        vector_rows = vector_recommendations(
            conn,
            "tt0000001",
            config,
            candidate_limit=5,
        )
        provenance_count = conn.execute(
            "SELECT count(*) FROM row_provenance WHERE table_name = 'movies';"
        ).fetchone()[0]

    assert {row["tconst"] for row in title_rows} == {"tt0000001", "tt0000002"}
    assert vector_rows[0]["tconst"] == "tt0000002"
    assert provenance_count >= 2
