# MovieRecommender Agent Guide

Use this as the working contract for AI agents touching this repo. The project is small, but it has a few sharp edges; do not cargo-cult new architecture into it just because the README says "recommender" and your inner platform engineer woke up.

## Project shape

```text
MovieRecommender/
├── movies.py                 # CLI: reduce raw IMDb TSV data into a smaller CSV
├── recommender.py            # CLI: load a reduced CSV and print recommendations
├── imdb_bootstrap.py         # CLI: inspect/fetch required IMDb source files
├── evaluate_recommendations.py # CLI: run tiny recommendation quality seeds
├── requirements.txt          # Python runtime/test dependencies
├── conftest.py               # Adds repo root to sys.path for pytest
├── src/
│   └── movie_recommender/
│       ├── data/             # IMDb bootstrap and dataset reduction logic
│       ├── recommenders/     # Legacy content and SQLite recommenders
│       └── cli/              # CLI implementations used by root wrappers
├── tests/                    # Non-Django unit tests
└── webapp/
    ├── manage.py             # Django entrypoint
    ├── movies/               # Django app, views, template, Django tests
    └── webapp/               # Django settings and URL config
```

The current recommender is a learning-era content recommender: it builds a text "soup" from actors, director, and genres, vectorizes it, and ranks by cosine similarity. Treat it respectfully, but do not mistake it for the target architecture.

## Development setup

Use Python 3.11+.

Install dependencies from the repository root. This creates a local `.venv` if
needed and installs `requirements.txt`:

```bash
make setup
```

The older `venv/` directory name and the common `.venv/` directory are both ignored. Do not commit virtualenvs, generated CSVs, caches, or local databases.

## Running the app and CLIs

Reduce IMDb data into a smaller CSV:

```bash
make canonical-dataset IMDB_DATA_DIR=/path/to/imdb-tsvs
```

The input directory must already contain `title.basics.tsv`, `title.crew.tsv`,
`title.ratings.tsv`, `name.basics.tsv`, and `title.principals.tsv`; the project
must not download real IMDb data automatically. By default the generated CSV is
`movies_10.csv` in the repo root, matching the web app's default
`RECOMMENDER_DATASET_PATH`. The reducer also tries to write `movies_10.parquet`
as a typed artifact when optional pandas Parquet dependencies are installed. If
Parquet support is missing, CSV generation still succeeds and typed output is
logged as skipped. Use `python movies.py --input-dir /path/to/imdb-tsvs --output movies_10 --no-typed`
to skip typed output explicitly.

Run CLI recommendations:

```bash
python recommender.py movies_10.csv "Inception"
```

Run the Django app:

```bash
make run-web
```

The web app reads `RECOMMENDER_DATASET_PATH` from `webapp/webapp/settings.py`; by default it expects `movies_10.csv` in the repo root.

## Tests and verification

There are tests. Not many, but enough to be offended if ignored:

- `tests/recommenders/test_movies.py` covers reducer/recommender utility behavior.
- `tests/data/test_imdb_bootstrap.py` covers the IMDb bootstrap helper.
- `tests/recommenders/test_recommendation_evaluation.py` covers the seed evaluation harness.
- `webapp/movies/test_search_view.py` covers the Django search view.
- `webapp/movies/test_views.py` covers recommender caching in the Django view layer.

Run from the repo root after installing dependencies:

```bash
make test
```

You can also run Django tests directly:

```bash
cd webapp
python manage.py test
```

If `python -m pytest` fails with `ModuleNotFoundError: No module named 'django'`, that means the current environment does not have dependencies installed. Fix the environment; do not pretend the repo has no tests.

For a quick Django configuration check, run:

```bash
make smoke
```

For docs-only or gitignore-only changes, it is acceptable to report that tests were not runnable because dependencies were missing, but still be explicit about the command and failure.

## Coding guidance

- Keep root CLI files thin; reusable logic belongs in `src/movie_recommender/` or the Django app as appropriate.
- Use canonical imports under `movie_recommender.*`; do not add top-level shim modules under `src/`.
- Avoid broad rewrites unless the task explicitly asks for them.
- Prefer small, reviewable commits with a clear verification step.
- Preserve public behavior unless the issue/plan says otherwise.
- Add or update tests when changing recommender logic, data loading, or web behavior.
- Do not commit generated datasets such as `movies_*.csv`.
- Do not add secrets, API keys, or machine-specific absolute paths.

## Roadmap posture

The repo is moving toward a more useful recommender and a runnable app/API, but broad roadmap ideas are not automatically Codex-ready implementation tasks.

Before implementing larger changes, clarify:

1. What behavior changes?
2. What data format or schema changes?
3. What command or UI path verifies it?
4. What test should fail before the fix and pass after it?

Good near-term improvements are usually boring and valuable: stable movie IDs, better data loading, clearer test fixtures, less brittle title lookup, and a runnable local/private test path. Save the grand architecture parade for after the basics work.

## GitHub workflow

- Use GitHub Issues/Projects as the source of truth for roadmap and implementation tasks.
- `Roadmap` means discussion/scoping/tradeoffs.
- `Codex Ready` plus the `codex-ready` label means scoped, accepted, and verifiable.
- Move implemented work to `Review`; completed work to `Done`.

When pushing changes, include:

- Summary of changed files.
- Exact verification command(s) and real output.
- Any known blocker, especially missing dependencies or unavailable data.

### Code review follow-ups

When GitHub Codex or another reviewer leaves feedback on a pull request, keep fixes on the existing PR head branch. Prefer resuming the same local Codex session/worktree that produced the commit so it has the original implementation context. Do not create a separate follow-up PR unless Ramon explicitly asks for one.
