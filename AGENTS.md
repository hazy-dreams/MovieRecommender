# MovieRecommender Agent Guide

Use this as the working contract for AI agents touching this repo. The project is small, but it has a few sharp edges; do not cargo-cult new architecture into it just because the README says "recommender" and your inner platform engineer woke up.

## Project shape

```text
MovieRecommender/
├── movies.py                 # CLI: reduce raw IMDb TSV data into a smaller CSV
├── recommender.py            # CLI: load a reduced CSV and print recommendations
├── requirements.txt          # Python runtime/test dependencies
├── conftest.py               # Adds repo root to sys.path for pytest
├── src/
│   ├── dataset_reducer.py    # IMDb TSV reduction and weighted-rating logic
│   └── movie_recommender.py  # Current content-based recommender
└── webapp/
    ├── manage.py             # Django entrypoint
    ├── movies/               # Django app, views, template, tests
    └── webapp/               # Django settings and URL config
```

The current recommender is a learning-era content recommender: it builds a text "soup" from actors, director, and genres, vectorizes it, and ranks by cosine similarity. Treat it respectfully, but do not mistake it for the target architecture.

## Local agent notes

Local project-scoped notes, plans, tradeoff discussions, lessons learned, and handoff context may exist under `.local-notes/`.

Rules:

- Read relevant notes in `.local-notes/` before planning non-trivial work.
- Never commit `.local-notes/`; it is intentionally gitignored.
- Keep durable project context there instead of bloating global assistant memory.
- If a note conflicts with tracked code or the user's latest instruction, the latest instruction and actual code win.

## Development setup

Use Python 3.11+.

Prefer a virtual environment. On this host, `uv` is available and is the least-annoying route:

```bash
make setup
```

`make setup` creates `.venv` with `uv` when available, otherwise it installs
`requirements.txt` into the active Python environment. If `make` is unavailable,
run:

```bash
UV_CACHE_DIR=.uv-cache uv venv --allow-existing
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python -r requirements.txt
```

Without `uv`, run `python -m pip install -r requirements.txt`.

The older `venv/` directory name and the common `.venv/` directory are both ignored. Do not commit virtualenvs, generated CSVs, caches, or local databases.

## Running the app and CLIs

Reduce IMDb data into a smaller CSV:

```bash
python movies.py -p 0.90 -o movies_10
```

Run CLI recommendations:

```bash
python recommender.py movies_10.csv "Inception"
```

Run the Django app:

```bash
make run-web
```

The web app reads `RECOMMENDER_DATASET_PATH` from `webapp/webapp/settings.py`; by default it expects `webapp/movies_10.csv`.

Run a lightweight Django configuration check:

```bash
make smoke
```

## Tests and verification

There are tests. Not many, but enough to be offended if ignored:

- `webapp/movies/test_movies.py` covers reducer/recommender utility behavior.
- `webapp/movies/test_search_view.py` covers the Django search view.
- `webapp/movies/test_views.py` covers recommender caching in the Django view layer.

Run from the repo root after installing dependencies:

```bash
make test
```

`make test` is the canonical test command for agent reports. It runs
`python -m pytest -q`.

You can also run Django tests directly:

```bash
cd webapp
python manage.py test
```

If `python -m pytest` fails with `ModuleNotFoundError: No module named 'django'`, that means the current environment does not have dependencies installed. Fix the environment; do not pretend the repo has no tests.

For docs-only or gitignore-only changes, it is acceptable to report that tests were not runnable because dependencies were missing, but still be explicit about the command and failure.

## Coding guidance

- Keep CLI files thin; reusable logic belongs in `src/` or the Django app as appropriate.
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
- Expected loop: GitHub issue to local Codex implementation to `make test` output to PR to Juno review to project state update.
- Prefer a temporary full clone for local Codex implementation work; clean it up after the PR merges or closes.
- Use GitHub `@codex` for automated PR review and review-feedback follow-ups on the existing PR branch.
- Codex may create PRs for review, but only after the canonical tests actually run and pass.
- If tests cannot run because dependencies, network, data, or tooling are unavailable, stop and report the blocker instead of creating a review-ready PR.
- Move implemented work to `Review`; completed work to `Manual E2E` when Ramon needs to test app behavior, or to `Done` when fully verified.

When pushing changes or creating a PR, include:

- Summary of changed files.
- Exact verification command(s) and real output, especially `make test`.
- Any known blocker, especially missing dependencies or unavailable data.
- Next suggested issue or review step when it is clear from the current work.
