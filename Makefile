BASE_PYTHON ?= python
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
UV_CACHE_DIR ?= .uv-cache

.PHONY: setup test run-web smoke clean

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
	$(PYTHON) webapp/manage.py runserver

smoke:
	$(PYTHON) webapp/manage.py check

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
	rm -rf .uv-cache
