UV_CACHE_DIR ?= .atlas/cache/uv
export UV_CACHE_DIR

.PHONY: setup format lint type test check validate graph site clean

setup:
	uv sync --group dev

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

type:
	uv run mypy src

test:
	uv run pytest

validate:
	uv run atlas validate --all --strict

graph:
	uv run atlas graph build --all

site:
	npm --prefix site run build

check: lint type test validate

clean:
	uv run atlas cache prune --generated
