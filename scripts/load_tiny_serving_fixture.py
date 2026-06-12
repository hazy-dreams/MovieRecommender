from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from movie_recommender.storage.postgres import load_fixture_file  # noqa: E402


DEFAULT_FIXTURE = REPO_ROOT / "fixtures" / "storage" / "tiny_serving_fixture.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Load the tiny Postgres serving fixture.")
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

    with psycopg.connect(args.database_url) as conn:
        config = load_fixture_file(conn, args.fixture)

    print(
        "Loaded tiny serving fixture "
        f"({config.feature_name}/{config.feature_version}, "
        f"{config.model_name}/{config.model_version}, dim={config.vector_dimension})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
