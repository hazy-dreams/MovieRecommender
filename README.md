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
