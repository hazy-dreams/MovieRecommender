# MovieRecommender Development Guide

This document provides a quick overview of the repository structure, coding style and testing instructions so AI tools and human contributors can work consistently.

## Repository Overview

```
MovieRecommender/
├── movies.py              # CLI for reducing the IMDb dataset
├── recommender.py         # CLI for running recommendations
├── requirements.txt       # Python package requirements
├── src/                   # Library code used by the CLIs and web app
│   ├── __init__.py
│   ├── dataset_reducer.py # MovieDatasetReducer class
│   └── movie_recommender.py # MovieRecommender class
└── webapp/                # Django project providing a simple UI
    ├── manage.py
    ├── movies/            # Django app with search view
    └── webapp/            # Django configuration
```

* `movies.py` reads raw IMDb TSV files and writes a smaller CSV using `MovieDatasetReducer`.
* `recommender.py` loads the reduced CSV and prints recommended titles using `MovieRecommender`.
* The `webapp` directory contains a minimal Django project that exposes a form for searching movies.

## Coding Conventions

* Use **Python 3.11** or newer.
* Follow **PEP 8** style guidelines and keep functions small and well named.
* Provide docstrings for public classes and functions.
* Keep command line interfaces thin; most logic should live in the `src` package.

## Running the Tools

Install dependencies in a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Dataset Reduction

```bash
python movies.py -p 0.90 -o movies_10
```

### Command Line Recommendations

```bash
python recommender.py movies_10.csv "Inception"
```

### Django Web Application

```bash
cd webapp
python manage.py runserver
```

Visit `http://localhost:8000/` to search for a movie and view recommendations.

## Testing

Run the automated tests before submitting changes:

```bash
# from the repository root
python -m pytest

# or run Django tests directly
cd webapp
python manage.py test
```

Tests currently cover only a small portion of the codebase but should remain passing.

## Pull Requests

When opening a PR, include a short summary of the changes and reference the main files modified. Show the output of the test command you ran. Keep commits focused and avoid unrelated formatting changes.


## Local agent notes

Local notes, plans, tradeoff discussions, lessons learned, and agent handoff context may exist under `.local-notes/`.
These files are intentionally gitignored.
Use them as project-scoped context when present, but never commit them.
