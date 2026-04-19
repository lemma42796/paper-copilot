.PHONY: help test lint format typecheck

help:
	@echo "Targets: test | lint | format | typecheck"

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src/
