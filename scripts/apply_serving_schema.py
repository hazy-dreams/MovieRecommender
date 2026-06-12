from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from movie_recommender.storage.postgres import SCHEMA_PATH, apply_schema  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the Postgres serving schema.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=SCHEMA_PATH,
        help=f"Schema SQL path. Default: {SCHEMA_PATH}",
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required; run `make setup` first") from exc

    with psycopg.connect(args.database_url) as conn:
        apply_schema(conn, args.schema)

    print(f"Applied serving schema from {args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
