# Postgres Serving Store

This directory contains the local development schema for the MovieRecommender
serving store. It follows `docs/architecture/serving-schema-provenance.md` and
keeps IMDb `tconst` as the canonical movie key.

## Local setup

Start a local Postgres instance with pgvector and pg_trgm support:

```bash
make db-up
```

The Docker Compose service uses local-only development credentials:

```text
postgresql://movierec:movierec@127.0.0.1:54329/movierec
```

Apply the schema:

```bash
make db-schema
```

Load the tiny fixture:

```bash
make db-load-tiny
```

Verify fuzzy title search, vector retrieval, and provenance:

```bash
make db-verify
```

Use a different database by overriding `DATABASE_URL`:

```bash
make db-schema DATABASE_URL=postgresql://user:password@host:5432/dbname
```

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
