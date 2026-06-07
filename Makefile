PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
UV_CACHE_DIR ?= .uv-cache

.PHONY: help setup test run-web smoke

help:
	@echo "MovieRecommender commands:"
	@echo "  make setup    Create/use .venv and install Python dependencies"
	@echo "  make test     Run the pytest suite"
	@echo "  make run-web  Start the Django development server"
	@echo "  make smoke    Run Django's lightweight project check"

setup:
	@if command -v uv >/dev/null 2>&1; then \
		UV_CACHE_DIR=$(UV_CACHE_DIR) uv venv --allow-existing && \
		UV_CACHE_DIR=$(UV_CACHE_DIR) uv pip install --python .venv/bin/python -r requirements.txt; \
	else \
		$(PYTHON) -m pip install -r requirements.txt; \
	fi

test:
	$(PYTHON) -m pytest -q

run-web:
	$(PYTHON) webapp/manage.py runserver

smoke:
	$(PYTHON) webapp/manage.py check
