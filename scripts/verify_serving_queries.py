from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from movie_recommender.storage.postgres import (  # noqa: E402
    EmbeddingConfig,
    build_ann_index_sql,
    search_titles,
    vector_recommendations,
)


DEFAULT_FIXTURE = REPO_ROOT / "fixtures" / "storage" / "tiny_serving_fixture.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify fuzzy title search, vector retrieval, and provenance."
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help=f"Fixture JSON path. Default: {DEFAULT_FIXTURE}",
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required; run `make setup` first") from exc

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    config = EmbeddingConfig(**fixture["embedding_config"])

    with psycopg.connect(args.database_url) as conn:
        conn.execute(build_ann_index_sql(config))
        conn.commit()

        title_rows = search_titles(conn, "Arival", limit=5)
        vector_rows = vector_recommendations(
            conn,
            "tt0000001",
            config,
            candidate_limit=5,
        )
        provenance_rows = _fetch_provenance(conn)

    if {row["tconst"] for row in title_rows} != {"tt0000001", "tt0000002"}:
        raise SystemExit(f"expected duplicate-title rows, got {title_rows!r}")
    if not vector_rows or vector_rows[0]["tconst"] != "tt0000002":
        raise SystemExit(f"expected tt0000002 nearest neighbor, got {vector_rows!r}")
    if not provenance_rows:
        raise SystemExit("expected row provenance for loaded movies")

    print("Fuzzy title search:")
    print(json.dumps(_jsonable(title_rows), indent=2, sort_keys=True))
    print("Vector recommendations:")
    print(json.dumps(_jsonable(vector_rows), indent=2, sort_keys=True))
    print("Provenance trace:")
    print(json.dumps(_jsonable(provenance_rows), indent=2, sort_keys=True))
    return 0


def _fetch_provenance(conn):
    cur = conn.cursor()
    cur.execute(
        """
SELECT rp.entity_key, er.run_type, ss.source_name, ss.snapshot_name
FROM row_provenance rp
JOIN etl_runs er ON er.etl_run_id = rp.etl_run_id
JOIN source_snapshots ss ON ss.source_snapshot_id = rp.source_snapshot_id
WHERE rp.table_name = 'movies'
ORDER BY rp.entity_key;
""".strip()
    )
    columns = [column.name for column in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def _jsonable(rows):
    return [
        {key: (float(value) if hasattr(value, "as_tuple") else value) for key, value in row.items()}
        for row in rows
    ]


if __name__ == "__main__":
    raise SystemExit(main())
