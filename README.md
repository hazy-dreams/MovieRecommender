# MovieRecommender
Recommends movies based on cast, director, genres, and IMDB rating.

Since the dataset is so big, `movies.py` is first used to reduce the data using an IMDb weighted rating formula and the desired quantile to a more manageable level. The recommendation system then imports that reduced CSV into an indexed SQLite preview store and serves recommendations from bounded candidate lookups.

Dataset generation relies on `MovieDatasetReducer`. Runtime recommendations use
`SQLiteMovieRecommender`, which avoids loading the full CSV into pandas or
building an all-pairs similarity matrix at app/CLI runtime.

`Examples:`

| The Dark Knight  | Se7en | The Departed |
| :-------------: | :-------------: | :-------------: |
| Batman Begins  | Gone Girl  | Gangs of New York |
| The Prestige  | The Girl with the Dragon Tattoo  | Mean Streets |
| The Dark Knight Rises  | The Curious Case of Benjamin Button  | Taxi Driver |
| Dunkirk  | Fight Club | Cape Fear |
| Interstellar  | Panic Room  | Casino |
| Following  | The Game  | Shutter Island |
| Insomnia  | Zodiac  | The King of Comedy |
| Inception  | The Social Network  | After Hours |
| Memento  | L.A. Confidential  | Bringing Out the Dead |
| Harsh Times  | Lucky Number Slevin  | Goodfellas |

This program processes a lot of data and requires a 64-bit version of Python.

## Setup

Use Python 3.11+ from the repository root. This creates a local `.venv` if
needed and installs dependencies from `requirements.txt`:

```bash
make setup
```

## Test

Run the existing pytest suite from the repository root:

```bash
make test
```

## Bounded Preview Recommendation Path

The private-preview runtime path is intentionally conservative for an 8 GB VPS:

- `movies.py` still produces a reduced CSV artifact from IMDb TSVs.
- `recommender.py` and the Django app stream that reduced CSV into
  `movies_10.sqlite` when the SQLite store is missing or older than the CSV.
- SQLite stores one `movies` row per title plus indexed `movie_terms` rows for
  actor, director, and genre terms.
- Recommendation lookup starts from an exact indexed title match, retrieves at
  most `RECOMMENDER_CANDIDATE_LIMIT` shared-term candidates, ranks those by term
  overlap and score, then fills any remaining slots by score.

This avoids the old runtime hazards:

- no pandas dataframe load is required by the app or CLI recommendation path,
- no scikit vectorizer is built at app runtime,
- no full all-pairs cosine similarity matrix is allocated,
- raw IMDb TSVs are never read by the app runtime.

The legacy `MovieRecommender` class remains in
`src/movie_recommender/recommenders/legacy_content.py` for small tests and
algorithm comparisons, but it should not be used for full or preview runtime
serving.

Build or refresh the SQLite store by running a recommendation once:

```bash
python recommender.py movies_10.csv "Inception"
```

The default store is `movies_10.sqlite` next to the CSV. Override it when needed:

```bash
python recommender.py movies_10.csv "Inception" --store /tmp/movies_preview.sqlite --candidate-limit 250
```

The Django app uses these settings from `webapp/webapp/settings.py`:

```text
RECOMMENDER_DATASET_PATH = movies_10.csv
RECOMMENDER_STORE_PATH = movies_10.sqlite
RECOMMENDER_CANDIDATE_LIMIT = 500
```

If the SQLite store exists, the app can serve recommendations without the CSV
being present. If neither exists, the app reports that the dataset is missing.

Future serving direction, if development resumes:

- keep the current SQLite path as the bounded local/private preview baseline,
- use a managed Postgres provider such as Neon for pgvector serving storage rather
  than hosting durable database state on the project/Juno VPS,
- keep ETL and embedding generation as explicit offline jobs,
- use a static frontend host such as Cloudflare Pages if the UI is split out,
- choose a thin API layer only after the desired product flow is clear.

Do not add infrastructure just because it is available. The current priority is
figuring out what movie recommendation experience is actually worth building.

## Canonical Dataset Artifact

The app and CLI consume the reduced CSV artifact `movies_10.csv` in the project
root by default. The reducer does not download IMDb data; bootstrap or place
these IMDb TSV files in a local directory first:

```text
title.basics.tsv
title.crew.tsv
title.ratings.tsv
name.basics.tsv
title.principals.tsv
```

## IMDb Source Data Bootstrap

IMDb publishes the required source files at `https://datasets.imdbws.com/`.
This project needs these compressed files:

```text
https://datasets.imdbws.com/title.basics.tsv.gz
https://datasets.imdbws.com/title.crew.tsv.gz
https://datasets.imdbws.com/title.ratings.tsv.gz
https://datasets.imdbws.com/title.principals.tsv.gz
https://datasets.imdbws.com/name.basics.tsv.gz
```

Use the bootstrap command to inspect or fetch the source files. It stores raw
data under `data/imdb` by default, which is ignored by git.

List required files and URLs without network access:

```bash
make imdb-bootstrap ARGS=--list
```

Preview the download plan without downloading anything:

```bash
make imdb-bootstrap ARGS=--dry-run
```

Create a tiny offline fixture set for development and tests:

```bash
make imdb-bootstrap ARGS="--sample --output-dir data/imdb-sample"
make canonical-dataset IMDB_DATA_DIR=data/imdb-sample DATASET_OUTPUT=movies_sample DATASET_PERCENTAGE=0 DATASET_MIN_VOTES=0
```

Fetch the full compressed IMDb source files only when you are ready to perform
the runtime operation with resource monitoring:

```bash
make imdb-bootstrap ARGS=--download
```

The bootstrap command streams compressed downloads to disk in 1 MiB chunks and
fails closed if any compressed file exceeds the configured limit, which defaults
to 2048 MiB per file. It does not decompress TSVs, load them into pandas, build
recommendations, or generate reduced datasets. To change the cap:

```bash
make imdb-bootstrap ARGS="--download --max-file-size-mib 3072"
```

By default, existing compressed source files are skipped. Use `--force` only
when you intentionally want to refresh local compressed sources that already
exist:

```bash
make imdb-bootstrap ARGS="--download --force"
```

Forced refreshes still stream each compressed file to a temporary file in the
output directory and atomically replace the existing file only after the
download completes successfully. They still do not decompress TSVs or load full
IMDb data into memory.

Plan for several GiB of compressed source data and tens of GiB if you later
decompress the TSVs. Keep raw compressed files, decompressed TSVs, reduced CSVs,
SQLite stores, and Parquet artifacts out of git. On a shared 8 GB RAM VPS, do
not run recommendation jobs against raw IMDb files; runtime recommendations
should use the bounded SQLite preview store.

Generate the canonical reduced dataset from the repository root:

```bash
make canonical-dataset IMDB_DATA_DIR=/path/to/imdb-tsvs
```

This writes `movies_10.csv`, which is compatible with `recommender.py` and the
Django app's default `RECOMMENDER_DATASET_PATH`. The CSV includes `tconst`,
`primary_title`, director/cast IMDb ID lists, director/cast name lists, genres,
score, and app-compatible title/director/actor columns. Duplicate primary titles
are disambiguated with their `tconst`.

The same command also attempts to write `movies_10.parquet` as a typed artifact.
Parquet support is optional: if the installed pandas environment lacks a
Parquet engine such as `pyarrow` or `fastparquet`, the reducer logs that typed
output was skipped and still writes the CSV. To skip typed output explicitly:

```bash
python movies.py --input-dir /path/to/imdb-tsvs --output movies_10 --no-typed
```

You can override the artifact prefix and filter settings:

```bash
make canonical-dataset IMDB_DATA_DIR=/path/to/imdb-tsvs DATASET_OUTPUT=movies_10 DATASET_PERCENTAGE=0.90 DATASET_MIN_VOTES=1000
```

Run CLI recommendations:

```bash
python recommender.py movies_10.csv "Inception"
```

This command uses the bounded SQLite preview store by default. It does not load
the full reduced CSV into pandas and does not build an all-pairs similarity
matrix.

## Recommendation Quality Evaluation

The repo includes a tiny offline evaluation harness for the current bounded
SQLite recommendation path. It uses:

- `fixtures/recommendation_eval_movies.csv` as a small tracked movie dataset,
- `fixtures/recommendation_eval_cases.json` as curated seed cases with
  expected-good titles, expected-bad titles, and failure-mode notes,
- a temporary SQLite store by default, so no generated database is written into
  the worktree.

Run it from the repository root:

```bash
make evaluate-recommendations
```

Or pass CLI options directly:

```bash
python evaluate_recommendations.py --top-n 3 --candidate-limit 250
```

The report is intentionally human-readable. `Expected-good hits` counts seed
titles that appeared in the top-N results. `Expected-bad misses` counts titles
that stayed out of the top-N results. `Expected errors` covers known failure
modes, such as a missing query title. The command exits with status 0 only when
all seed cases pass, which makes it usable in local checks or CI without adding
a full benchmark framework.

## Future Work

Development is paused while the product direction is reconsidered. If it resumes,
prioritize a clear recommendation experience before adding more infrastructure.
Likely next decisions are whether the app should remain a personal/private tool,
what dataset size is useful, and whether the eventual UI/API split should use
Cloudflare Pages plus a thin API over managed Postgres.

Information courtesy of
IMDb
(http://www.imdb.com).
Used with permission.

Data location: https://datasets.imdbws.com/

### Web App

After generating a reduced dataset (`movies_10.csv` by default), you can start
the Django development server from the repository root:

```bash
make run-web
```

Navigate to `http://localhost:8000/` to search for a movie and view
recommendations.

The web app looks for the SQLite recommendation store using
`RECOMMENDER_STORE_PATH` and can build it from `RECOMMENDER_DATASET_PATH` when
the reduced CSV is available. By default both point to `movies_10.*` artifacts
in the project root. Update these paths if your artifacts are stored elsewhere.

For a quick Django configuration check, run:

```bash
make smoke
```

For a private VPS preview using an SSH tunnel or trusted private network, see
[`docs/private-vps-preview.md`](docs/private-vps-preview.md).

## Implementation reports

When reporting completed implementation work, include the changed files, exact
verification command(s), real command output, and any blockers such as missing
dependencies or unavailable data.
