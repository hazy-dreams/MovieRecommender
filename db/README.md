# Postgres Serving Store

This directory contains the local development schema for the MovieRecommender
serving store. It follows `docs/architecture/serving-schema-provenance.md` and
keeps IMDb `tconst` as the canonical movie key.

## Target database

The preferred target is a managed Postgres database with pgvector support, such
as Neon. Keep durable database state out of the project/Juno VPS unless a real
requirement beats the managed option.

Set `DATABASE_URL` for the target database before running the schema or fixture
commands:

```bash
export DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"
make db-schema
make db-load-tiny
make db-verify
```

For Neon, use a development branch or throwaway database while validating schema
changes. The schema uses standard Postgres plus `pg_trgm` and `vector`, so the
same commands should work against any compatible Postgres provider.

## Optional local Docker setup

Docker Compose remains an optional convenience for machines where the current
user is allowed to run Docker. It is not the required verification path.

Start a local Postgres instance with pgvector and pg_trgm support:

```bash
make db-up
export DATABASE_URL="postgresql://movierec:movierec@127.0.0.1:54329/movierec"
make db-schema
make db-load-tiny
make db-verify
```

The Compose service binds only to localhost and uses local-only development
credentials.

## Schema notes

- `source_snapshots`, `etl_runs`, `etl_run_sources`, and `row_provenance`
  capture load provenance.
- `movies`, `movie_external_ids`, `people`, `person_external_ids`,
  `movie_credits`, `movie_text_features`, and `movie_embeddings` are the serving
  tables.
- `pg_trgm` indexes support fuzzy title search over `display_title` and
  `primary_title`.
- `movie_embeddings.embedding` uses unbounded `vector` storage with a
  `vector_dims(embedding) = vector_dimension` check so multiple dimensions can
  coexist.
- ANN indexes should be scoped to the configured feature/model/version/dimension
  slice. The local verification script creates the tiny-fixture HNSW index.

Embedding generation is intentionally out of scope here. App and API request
paths should query existing rows only; text feature and embedding creation
belong to offline ETL jobs.
