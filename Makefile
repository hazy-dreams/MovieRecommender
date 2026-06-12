BASE_PYTHON ?= python
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
UV_CACHE_DIR ?= .uv-cache
IMDB_DATA_DIR ?= .
IMDB_BOOTSTRAP_DIR ?= data/imdb
TMDB_CACHE ?= data/tmdb/tmdb_enrichment.sqlite
DATASET_OUTPUT ?= movies_10
DATASET_PERCENTAGE ?= 0.90
DATASET_MIN_VOTES ?= 1000
WEB_BIND ?= 127.0.0.1:8000

.PHONY: setup test run-web smoke imdb-bootstrap canonical-dataset tmdb-enrichment evaluate-recommendations clean

setup:
	@if [ ! -x "$(VENV)/bin/python" ]; then \
		if $(BASE_PYTHON) -m venv $(VENV); then \
			:; \
		elif command -v uv >/dev/null 2>&1; then \
			UV_CACHE_DIR=$(UV_CACHE_DIR) uv venv --python $(BASE_PYTHON) $(VENV); \
		else \
			echo "Could not create $(VENV). Install venv support or uv, then rerun make setup."; \
			exit 1; \
		fi; \
	fi
	@if $(PYTHON) -m pip --version >/dev/null 2>&1; then \
		$(PYTHON) -m pip install -r requirements.txt; \
	elif command -v uv >/dev/null 2>&1; then \
		UV_CACHE_DIR=$(UV_CACHE_DIR) uv pip install --python $(PYTHON) -r requirements.txt; \
	else \
		echo "pip is not available for $(PYTHON). Install pip or uv, then rerun make setup."; \
		exit 1; \
	fi

test:
	$(PYTHON) -m pytest -q

run-web:
	$(PYTHON) webapp/manage.py runserver $(WEB_BIND)

smoke:
	$(PYTHON) webapp/manage.py check

imdb-bootstrap:
	$(PYTHON) imdb_bootstrap.py --output-dir "$(IMDB_BOOTSTRAP_DIR)" $(ARGS)

canonical-dataset:
	$(PYTHON) movies.py --input-dir "$(IMDB_DATA_DIR)" --percentage "$(DATASET_PERCENTAGE)" --min-votes "$(DATASET_MIN_VOTES)" --output "$(DATASET_OUTPUT)"

tmdb-enrichment:
	$(PYTHON) tmdb_enrichment.py --input "$(DATASET_OUTPUT).csv" --cache "$(TMDB_CACHE)" $(ARGS)

evaluate-recommendations:
	$(PYTHON) evaluate_recommendations.py $(ARGS)

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
	rm -rf .uv-cache
