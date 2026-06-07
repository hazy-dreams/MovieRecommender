# MovieRecommender
Recommends movies based on cast, director, genres, and IMDB rating.

Since the dataset is so big, `movies.py` is first used to reduce the data using an IMDb weighted rating formula and the desired quantile to a more manageable level. The recommendation system then runs with this data via `recommender.py`.

Both scripts now rely on the `MovieDatasetReducer` and `MovieRecommender` classes located in the `src` package.

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

## Canonical Dataset Artifact

The app and CLI consume the reduced CSV artifact `movies_10.csv` in the project
root by default. The reducer does not download IMDb data; place these IMDb TSV
files in a local directory first:

```text
title.basics.tsv
title.crew.tsv
title.ratings.tsv
name.basics.tsv
title.principals.tsv
```

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

For a quick Django configuration check, run:

```bash
make smoke
```

## Implementation reports

When reporting completed implementation work, include the changed files, exact
verification command(s), real command output, and any blockers such as missing
dependencies or unavailable data.
