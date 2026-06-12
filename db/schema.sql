CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source_snapshots (
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

CREATE TABLE IF NOT EXISTS etl_runs (
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

CREATE TABLE IF NOT EXISTS etl_run_sources (
    etl_run_id BIGINT NOT NULL REFERENCES etl_runs(etl_run_id),
    source_snapshot_id BIGINT NOT NULL REFERENCES source_snapshots(source_snapshot_id),
    role TEXT NOT NULL,
    PRIMARY KEY (etl_run_id, source_snapshot_id, role)
);

CREATE TABLE IF NOT EXISTS row_provenance (
    row_provenance_id BIGSERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    source_snapshot_id BIGINT NOT NULL REFERENCES source_snapshots(source_snapshot_id),
    source_row_key TEXT,
    source_row_hash TEXT,
    etl_run_id BIGINT NOT NULL REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS movies (
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

CREATE INDEX IF NOT EXISTS idx_movies_display_title_trgm
    ON movies USING gin (display_title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_movies_primary_title_trgm
    ON movies USING gin (primary_title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_movies_score
    ON movies (weighted_score DESC NULLS LAST, display_title ASC, tconst ASC);

CREATE TABLE IF NOT EXISTS movie_external_ids (
    source_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    source_snapshot_id BIGINT REFERENCES source_snapshots(source_snapshot_id),
    etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_name, source_id),
    UNIQUE (source_name, tconst)
);

CREATE TABLE IF NOT EXISTS people (
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

CREATE TABLE IF NOT EXISTS person_external_ids (
    source_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    person_id BIGINT NOT NULL REFERENCES people(person_id),
    source_snapshot_id BIGINT REFERENCES source_snapshots(source_snapshot_id),
    etl_run_id BIGINT REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_name, source_id),
    UNIQUE (source_name, person_id)
);

CREATE TABLE IF NOT EXISTS movie_credits (
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
    UNIQUE (tconst, person_id, role_type, credit_order, source_name)
);

CREATE INDEX IF NOT EXISTS idx_movie_credits_tconst_role
    ON movie_credits (tconst, role_type, credit_order);

CREATE INDEX IF NOT EXISTS idx_movie_credits_person
    ON movie_credits (person_id, role_type);

CREATE TABLE IF NOT EXISTS movie_text_features (
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
    UNIQUE (
        text_feature_id,
        tconst,
        feature_name,
        feature_version,
        source_text_sha256
    ),
    UNIQUE (tconst, feature_name, feature_version, source_text_sha256)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_movie_text_features_one_active
    ON movie_text_features (tconst, feature_name, feature_version)
    WHERE active;

CREATE TABLE IF NOT EXISTS movie_embeddings (
    movie_embedding_id BIGSERIAL PRIMARY KEY,
    text_feature_id BIGINT NOT NULL REFERENCES movie_text_features(text_feature_id),
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    feature_name TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    vector_dimension INTEGER NOT NULL,
    embedding vector NOT NULL,
    embedding_sha256 TEXT,
    source_text_sha256 TEXT NOT NULL,
    embedding_etl_run_id BIGINT NOT NULL REFERENCES etl_runs(etl_run_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT true,
    CHECK (vector_dims(embedding) = vector_dimension),
    FOREIGN KEY (
        text_feature_id,
        tconst,
        feature_name,
        feature_version,
        source_text_sha256
    )
        REFERENCES movie_text_features(
            text_feature_id,
            tconst,
            feature_name,
            feature_version,
            source_text_sha256
        ),
    UNIQUE (text_feature_id, model_name, model_version, vector_dimension)
);

CREATE INDEX IF NOT EXISTS idx_movie_embeddings_lookup
    ON movie_embeddings (
        tconst,
        active,
        feature_name,
        feature_version,
        model_name,
        model_version,
        vector_dimension
    );

CREATE INDEX IF NOT EXISTS idx_movie_embeddings_serving_slice
    ON movie_embeddings (
        active,
        feature_name,
        feature_version,
        model_name,
        model_version,
        vector_dimension
    );
