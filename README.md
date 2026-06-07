# MovieRecommender
Recommends movies based on cast, director, genres, and IMDB rating.

Since the dataset is so big, `movies.py` is first used to reduce the data using an IMDb weighted rating formula and the desired quantile to a more manageable level. The recommendation system then runs with this data via `recommender.py`.

Both scripts now rely on the `MovieDatasetReducer` and `MovieRecommender` classes located in the `src` package.

## Quickstart

Use Python 3.11+ from the repository root. `make setup` creates `.venv` with
`uv` when available, otherwise it installs into the active Python environment:

```bash
make setup
```

Run the canonical test suite:

```bash
make test
```

Run a lightweight Django configuration check:

```bash
make smoke
```

Run the current Django app:

```bash
make run-web
```

The web app expects a reduced dataset at `movies_10.csv` in the project root
unless `RECOMMENDER_DATASET_PATH` is changed in `webapp/webapp/settings.py`.

## AI-Agent Workflow

Use GitHub issues as the source of truth for scoped changes. The expected loop
is:

1. Read `AGENTS.md`, the issue body, and relevant local code before editing.
2. Implement only the accepted issue scope.
3. Run `make test` from the repository root and capture the real output.
4. Report changed files, verification command output, known blockers, and the
   next suggested issue or review step.
5. Hand off for Juno review, then GitHub PR/project state updates.

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

### Future Work:
- Make into a webapp using Django
- Use database to provide backend data for webapp
- Allow user to add more than one movie at a time

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

The web app looks for the reduced dataset using the `RECOMMENDER_DATASET_PATH`
setting in `webapp/webapp/settings.py`. By default it points to
`movies_10.csv` in the project root. Update this path if your CSV is stored
elsewhere.
