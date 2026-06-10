# Serving Schema and Data Provenance

This document defines the target Postgres serving schema for movie metadata,
fuzzy title search, vector retrieval, and ETL auditability. It is the design
contract for implementing the Postgres/pgvector storage layer in issue #16.

The current reduced CSV and SQLite preview store remain transitional artifacts.
The target serving store should be loaded by ETL jobs, not by app/API request
handlers.

## Goals

- Use IMDb `tconst` as the canonical movie identity anchor.
- Preserve source provenance for IMDb, TMDB-like enrichments, reduced CSVs, and
  transitional SQLite stores.
- Store people, credits, text features, and embeddings with stable upsert keys.
- Support fuzzy title search with `pg_trgm`.
- Support bounded vector candidate retrieval with `pgvector`.
- Make embedding versions and ETL runs auditable.
- Preserve the rule that app/API requests never generate embeddings inline.

## Non-Goals

- This document does not implement migrations, database setup, ETL code, or
  embedding generation.
- This schema is not a full analytics warehouse. It keeps only the fields needed
  for serving, traceability, and later reloads.
- This document does not define public deployment, Coolify, or production
  operations.

## Identity and Upsert Rules

`movies.tconst` is the canonical movie primary key. Titles are display and
search attributes, not identities. Duplicate titles must be handled by
`tconst`, not by title suffixes in the target store.

Use these upsert keys:

| Entity | Primary/upsert key | Notes |
| --- | --- | --- |
| Movie | `tconst` | IMDb title ID, required for all served movies. |
| Person | `nconst` when available; otherwise source-specific external ID | IMDb people use `nconst`. TMDB-only people may use a generated internal ID plus `person_external_ids`. |
| External movie ID | `(source_name, source_id)` | Maps TMDB-like IDs to `tconst`. |
| Credit | `(tconst, nconst, role_type, credit_order)` when `nconst` exists | If a source lacks `nconst`, use the resolved `person_id`; keep source fields for audit. |
| Text feature | `(tconst, feature_name, feature_version, source_text_sha256)` | Regenerated text for the same feature/version is a new row. |
| Embedding | `(text_feature_id, model_name, model_version, vector_dimension)` | A changed source text/version produces a new text feature row and therefore a new embedding row. |
| Source snapshot | `(source_name, snapshot_name, snapshot_date, content_sha256)` | Hashes distinguish different files for the same snapshot date. |
| ETL run | generated `etl_run_id` | References all snapshots and artifacts used by the run. |

## Source and Provenance Tables

### `source_snapshots`

Records immutable source inputs. One row should exist for each raw file or
logical source payload used by a load.

```sql
CREATE TABLE source_snapshots (
    source_snapshot_id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    snapshot_name TEXT NOT NULL,
    snapshot_date DATE,
    source_uri TEXT,
    content_sha256 TEXT NOT NULL,
    byte_size BIGINT,
    row_count BIGINT,
    schema_version TEXT,
    fetched_at TIMESTAMPTZ,
    notes TEXT,
    UNIQUE NULLS NOT DISTINCT (
        source_name,
        snapshot_name,
        snapshot_date,
        content_sha256
    )
);
```

Examples:

- `source_name = 'imdb'`, `snapshot_name = 'title.basics.tsv.gz'`
- `source_name = 'imdb'`, `snapshot_name = 'title.principals.tsv.gz'`
- `source_name = 'tmdb'`, `snapshot_name = 'movie-details-api'`
- `source_name = 'reduced_csv'`, `snapshot_name = 'movies_10.csv'`
- `source_name = 'sqlite_preview'`, `snapshot_name = 'movies_10.sqlite'`

The hash must be computed from the exact bytes loaded or consumed. For
decompressed TSVs, record whether the hash is for compressed or decompressed
bytes in `notes` until the loader has a formal convention.

`snapshot_date` is nullable for ad hoc artifacts such as reduced CSV files and
API payloads. The unique constraint must treat null dates as equal so reloading
the same `(source_name, snapshot_name, content_sha256)` without a date upserts
the existing snapshot row instead of creating duplicate provenance records. If
the target Postgres version cannot use `UNIQUE NULLS NOT DISTINCT`, implement
the same behavior with an expression unique index that normalizes null dates to
a sentinel value.

### `etl_runs`

Tracks each load attempt and its outcome.

```sql
CREATE TABLE etl_runs (
    etl_run_id BIGSERIAL PRIMARY KEY,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    code_version TEXT,
    loader_name TEXT,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    records_read BIGINT,
    records_written BIGINT,
    error_message TEXT
);
```

Expected `run_type` values include `imdb_load`, `tmdb_enrichment`,
`csv_backfill`, `sqlite_backfill`, `text_feature_build`, and
`embedding_backfill`.

### `etl_run_sources`

Connects ETL runs to the immutable source snapshots they consumed.

```sql
CREATE TABLE etl_run_sources (
    etl_run_id BIGINT NOT NULL REFERENCES etl_runs(etl_run_id),
    source_snapshot_id BIGINT NOT NULL REFERENCES source_snapshots(source_snapshot_id),
    role TEXT NOT NULL,
    PRIMARY KEY (etl_run_id, source_snapshot_id, role)
);
```

Examples of `role`: `title_basics`, `title_crew`, `title_ratings`,
`title_principals`, `name_basics`, `reduced_csv`, `sqlite_store`, `tmdb_payload`.

### `row_provenance`

Provides row-level traceability without copying whole source rows into serving
tables.

```sql
CREATE TABLE row_provenance (
    row_provenance_id BIGSERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    source_snapshot_id BIGINT NOT NULL REFERENCES source_snapshots(source_snapshot_id),
    source_row_key TEXT,
    source_row_hash TEXT,
    etl_run_id BIGINT NOT NULL REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

For movies, `entity_key` is `tconst`. For people, it is `nconst` when present.
For embeddings, it is the embedding row ID or a deterministic key composed from
the text feature and embedding version.

## Serving Entity Tables

### `movies`

Stores one row per served movie.

```sql
CREATE TABLE movies (
    tconst TEXT PRIMARY KEY,
    primary_title TEXT NOT NULL,
    display_title TEXT NOT NULL,
    original_title TEXT,
    title_type TEXT,
    start_year INTEGER,
    end_year INTEGER,
    runtime_minutes INTEGER,
    genres TEXT[] NOT NULL DEFAULT '{}',
    average_rating NUMERIC(3, 1),
    num_votes INTEGER,
    weighted_score DOUBLE PRECISION,
    is_adult BOOLEAN,
    active BOOLEAN NOT NULL DEFAULT true,
    first_seen_etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    last_seen_etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`display_title` is the UI title. Unlike the CSV/SQLite preview path, duplicate
display titles should not be disambiguated by mutating the title. Search and
detail endpoints should return `tconst` so clients can distinguish duplicates.

Recommended indexes:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX idx_movies_display_title_trgm
    ON movies USING gin (display_title gin_trgm_ops);

CREATE INDEX idx_movies_primary_title_trgm
    ON movies USING gin (primary_title gin_trgm_ops);

CREATE INDEX idx_movies_score
    ON movies (weighted_score DESC NULLS LAST, display_title ASC, tconst ASC);
```

### `movie_external_ids`

Maps source-specific movie IDs to canonical `tconst`.

```sql
CREATE TABLE movie_external_ids (
    source_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    source_snapshot_id BIGINT REFERENCES source_snapshots(source_snapshot_id),
    etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_name, source_id),
    UNIQUE (source_name, tconst)
);
```

For IMDb, the external ID row may be `('imdb', tconst, tconst)`. For TMDB-like
inputs, this table records the resolved bridge from the TMDB movie ID to the
IMDb `tconst`.

### `people`

Stores people that can appear in movie credits.

```sql
CREATE TABLE people (
    person_id BIGSERIAL PRIMARY KEY,
    nconst TEXT UNIQUE,
    primary_name TEXT NOT NULL,
    birth_year INTEGER,
    death_year INTEGER,
    primary_professions TEXT[] NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT true,
    first_seen_etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    last_seen_etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

IMDb people should upsert by `nconst`. A TMDB-only person may be inserted with
`nconst = NULL`, but must have a row in `person_external_ids`.

### `person_external_ids`

```sql
CREATE TABLE person_external_ids (
    source_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    person_id BIGINT NOT NULL REFERENCES people(person_id),
    source_snapshot_id BIGINT REFERENCES source_snapshots(source_snapshot_id),
    etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_name, source_id),
    UNIQUE (source_name, person_id)
);
```

### `movie_credits`

Stores cast and crew relationships used for display, filtering, text feature
construction, and reranking.

```sql
CREATE TABLE movie_credits (
    movie_credit_id BIGSERIAL PRIMARY KEY,
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    person_id BIGINT NOT NULL REFERENCES people(person_id),
    role_type TEXT NOT NULL,
    category TEXT,
    job TEXT,
    character_names TEXT[] NOT NULL DEFAULT '{}',
    credit_order INTEGER NOT NULL DEFAULT 0,
    source_name TEXT NOT NULL,
    source_snapshot_id BIGINT REFERENCES source_snapshots(source_snapshot_id),
    etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tconst, person_id, role_type, credit_order)
);
```

Recommended `role_type` values are `director`, `writer`, `actor`, `actress`,
`producer`, and `crew`. Preserve raw IMDb `category` and `job` values when they
exist. For the current reduced CSV, director and cast lists should be loaded as
`director`, `actor`, or `actress` where that information is known; otherwise use
`actor` for cast names carried by the transitional artifact and retain the
artifact provenance.

`source_name` records which loader last wrote the serving credit, but it is not
part of the serving upsert key. If the same credit is observed from multiple
sources, attach those sources through `row_provenance` instead of duplicating the
credit row.

Recommended indexes:

```sql
CREATE INDEX idx_movie_credits_tconst_role
    ON movie_credits (tconst, role_type, credit_order);

CREATE INDEX idx_movie_credits_person
    ON movie_credits (person_id, role_type);
```

## Text Features

Text features are versioned source texts used for search, retrieval, and
embedding generation. They are not generated in app/API request handlers.

```sql
CREATE TABLE movie_text_features (
    text_feature_id BIGSERIAL PRIMARY KEY,
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    feature_name TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    source_text TEXT NOT NULL,
    source_text_sha256 TEXT NOT NULL,
    build_method TEXT NOT NULL,
    source_etl_run_id BIGINT NOT NULL REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (text_feature_id, tconst),
    UNIQUE (tconst, feature_name, feature_version, source_text_sha256)
);
```

Only one text feature row should be active for a given movie feature contract:

```sql
CREATE UNIQUE INDEX idx_movie_text_features_one_active
    ON movie_text_features (tconst, feature_name, feature_version)
    WHERE active;
```

Initial expected feature:

- `feature_name = 'recommendation_soup'`
- `feature_version = 'v1'`
- `source_text` combines normalized title, genres, directors, and top cast from
  the loaded serving tables.

If the text construction changes, increment `feature_version`. Do not overwrite
old text feature rows that have embeddings; mark superseded rows inactive if
needed. If the source movie data changes but the construction method and
`feature_version` stay the same, insert a new inactive row with the new
`source_text_sha256`, build replacement embeddings, then activate the new row
and mark the older row inactive in the same transaction.

## Embeddings

Embeddings are offline artifacts. App/API requests may query existing vectors
but must never call an embedding model inline. If a requested movie has no
active embedding for the configured model/version, the serving path should
fallback to non-vector retrieval or return a controlled unavailable state.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE movie_embeddings (
    movie_embedding_id BIGSERIAL PRIMARY KEY,
    text_feature_id BIGINT NOT NULL REFERENCES movie_text_features(text_feature_id),
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    vector_dimension INTEGER NOT NULL,
    embedding vector NOT NULL,
    embedding_sha256 TEXT,
    source_text_sha256 TEXT NOT NULL,
    embedding_etl_run_id BIGINT NOT NULL REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT true,
    FOREIGN KEY (text_feature_id, tconst)
        REFERENCES movie_text_features(text_feature_id, tconst),
    UNIQUE (text_feature_id, model_name, model_version, vector_dimension)
);
```

The actual `embedding` column dimension must be fixed in the migration for the
selected model, for example `vector(1536) NOT NULL` instead of unbounded
`vector NOT NULL`. Keep `vector_dimension` as explicit metadata even though
Postgres enforces the column dimension.

Vector versioning rules:

- A new model name, model version, vector dimension, or source text version must
  create new embedding rows.
- Existing embeddings must not be silently overwritten when `source_text_sha256`
  changes.
- The active serving model/version should be selected by configuration, not by
  "latest row" queries.
- Backfills should run as `etl_runs` with `run_type = 'embedding_backfill'`.
- The loader should set old rows inactive only after the replacement rows are
  successfully written and verified.

Recommended pgvector index:

```sql
CREATE INDEX idx_movie_embeddings_ann
    ON movie_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WHERE active;
```

Use `ivfflat` instead of `hnsw` only if #16 chooses it deliberately for local
resource constraints. Either way, the ANN index must be scoped to the active
serving embedding set through query predicates on `active`, `model_name`,
`model_version`, and `vector_dimension`.

## Search and Retrieval Flow

### Fuzzy Title Search

Title search should use `pg_trgm` over `movies.display_title` and
`movies.primary_title`.

Expected query shape:

```sql
SELECT tconst, display_title, primary_title, start_year, weighted_score,
       GREATEST(
           similarity(display_title, :query),
           similarity(primary_title, :query)
       ) AS title_similarity
FROM movies
WHERE active
  AND (
      display_title % :query
      OR primary_title % :query
  )
ORDER BY title_similarity DESC,
         weighted_score DESC NULLS LAST,
         display_title ASC,
         tconst ASC
LIMIT :limit;
```

The app should pass `tconst` to recommendation/detail calls. Title strings alone
are insufficient because duplicate titles are valid.

### Vector Candidate Retrieval

Recommendation retrieval should be bounded:

1. Resolve the query movie by `tconst`.
2. Load its active embedding for the configured feature name/version and
   model/version/dimension.
3. Use pgvector ANN to fetch a limited candidate set.
4. Exclude the query movie.
5. Rerank or decorate candidates using movie metadata, ratings, genres, and
   credits as needed.

Expected query shape:

```sql
WITH query_embedding AS (
    SELECT e.embedding
    FROM movie_embeddings e
    JOIN movie_text_features tf
      ON tf.text_feature_id = e.text_feature_id
     AND tf.tconst = e.tconst
    WHERE e.tconst = :query_tconst
      AND e.active
      AND e.model_name = :model_name
      AND e.model_version = :model_version
      AND e.vector_dimension = :vector_dimension
      AND tf.active
      AND tf.feature_name = :feature_name
      AND tf.feature_version = :feature_version
)
SELECT m.tconst,
       m.display_title,
       m.primary_title,
       m.start_year,
       m.weighted_score,
       e.embedding <=> q.embedding AS cosine_distance
FROM query_embedding q
JOIN movie_embeddings e
  ON e.active
 AND e.model_name = :model_name
 AND e.model_version = :model_version
 AND e.vector_dimension = :vector_dimension
JOIN movie_text_features tf
  ON tf.text_feature_id = e.text_feature_id
 AND tf.tconst = e.tconst
 AND tf.active
 AND tf.feature_name = :feature_name
 AND tf.feature_version = :feature_version
JOIN movies m ON m.tconst = e.tconst
WHERE e.tconst <> :query_tconst
  AND m.active
ORDER BY e.embedding <=> q.embedding,
         m.weighted_score DESC NULLS LAST,
         m.display_title ASC,
         m.tconst ASC
LIMIT :candidate_limit;
```

The serving layer can add metadata-based reranking after this bounded retrieval,
but it must not scan all movies or generate embeddings inline.

## Transitional CSV and SQLite Loading

The current reduced CSV has these relevant columns:

- `tconst`
- `title`
- `primary_title`
- `director`
- `director_ids`
- `director_names`
- `genres`
- `score`
- `cast_ids`
- `actors`

CSV backfill expectations:

- Register the CSV as a `source_snapshots` row with `source_name =
  'reduced_csv'`, byte size, row count, and SHA-256 hash.
- Create an `etl_runs` row with `run_type = 'csv_backfill'`.
- Upsert `movies` by `tconst`.
- Load `primary_title` from `primary_title` when present.
- Load `display_title` from `primary_title` or `title`, removing only the
  transitional ` (tt...)` duplicate-title suffix if the artifact contains one.
- Load `weighted_score` from `score`.
- Load `genres` from the serialized list in `genres`.
- Upsert people from `director_ids`/`director_names` and `cast_ids`/`actors`
  when IDs are present.
- Create credits for directors and top cast using the list order as
  `credit_order`.
- Record row-level provenance for each upserted movie and for generated credits
  when source row hashes are available.

SQLite preview backfill expectations:

- Treat the SQLite file as a transitional serving artifact, not as the source of
  truth when raw IMDb snapshots or reduced CSVs are available.
- Register the SQLite file as `source_name = 'sqlite_preview'`.
- Use it only to seed `movies` and simple term-derived text features if the CSV
  is unavailable.
- Do not preserve SQLite `movie_terms` as a target table; target retrieval uses
  text features, embeddings, and Postgres indexes.

Raw IMDb loading expectations:

- Register each required IMDb file as a separate `source_snapshots` row.
- Use `title.basics` and `title.ratings` for `movies`.
- Use `name.basics` for `people`.
- Use `title.crew` and `title.principals` for `movie_credits`.
- Preserve current reducer limits where needed for serving features: up to three
  directors and five top cast members for the first `recommendation_soup`
  version.

TMDB-like loading expectations:

- Resolve enriched movie rows to `tconst` before inserting serving records.
- Store TMDB movie IDs in `movie_external_ids`.
- Store TMDB person IDs in `person_external_ids`.
- If TMDB payloads provide overviews or other text, store them as separate
  `movie_text_features` with source snapshot provenance.

## Runtime Boundaries

Allowed in app/API request handlers:

- Fuzzy title search using `pg_trgm`.
- Lookup by `tconst`.
- Bounded ANN retrieval using existing active embeddings.
- Metadata joins for display and reranking.

Not allowed in app/API request handlers:

- Reading raw IMDb/TMDB files.
- Importing reduced CSV or SQLite artifacts.
- Building text features.
- Calling embedding models.
- Writing new embeddings as a side effect of user requests.
- Full-table similarity scans.

Missing text features or embeddings should be handled by offline backfill jobs.

## Implementation Notes for Issue #16

Issue #16 can implement migrations from this table list without inventing table
boundaries:

- `source_snapshots`
- `etl_runs`
- `etl_run_sources`
- `row_provenance`
- `movies`
- `movie_external_ids`
- `people`
- `person_external_ids`
- `movie_credits`
- `movie_text_features`
- `movie_embeddings`

Minimum extension setup:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;
```

Minimum local verification for #16:

- Apply the schema to a clean local database.
- Insert a small fixture with two movies, people, credits, one text feature per
  movie, and one embedding per movie.
- Verify `pg_trgm` title search returns duplicate titles with distinct `tconst`
  values.
- Verify pgvector nearest-neighbor retrieval returns bounded candidates by
  configured model/version/dimension.
- Verify an ETL run can be traced to its source snapshots and affected movie
  rows.
