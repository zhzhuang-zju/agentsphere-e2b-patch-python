PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: build install test clean

build:
	$(PIP) install -q build
	$(PYTHON) -m build

install:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest

clean:
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache
	rm -rf src/*.egg-info *.egg-info
	find . -type d -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
