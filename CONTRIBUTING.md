# Contributing

## Setup

```bash
uv sync
prek install --hook-type pre-commit --hook-type commit-msg
```

## Checks

```bash
uv run pytest
uv run mypy
uv run ruff check
uv run ruff format --check
uv run lint-imports
```

Integration tests need `tmux`; skip them with `-m "not integration"`.

## Commits

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `build:`, `docs:`, ...),
with no attribution trailers. The `commit-msg` hook enforces this.
