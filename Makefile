UV_CACHE_DIR ?= .atlas/cache/uv
export UV_CACHE_DIR

.PHONY: setup format lint type test frontend check validate graph site clean

setup:
	uv sync --group dev
	npm ci --prefix site --cache .atlas/cache/npm

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
	uv run atlas site build

frontend:
	npm run typecheck --prefix site
	npm run test --prefix site
	npm run build --prefix site

check: lint type test validate frontend

clean:
	@echo "Generated build output is ignored; use atlas cache prune for downloaded artifacts."
