# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

confctl is a configuration management tool that uses a build-system-like approach (similar to Make/Bazel) to declaratively manage system configurations. Users write Python functions (in `.confbuild.py` files) that define dependencies and build steps.

## Development Setup

- **Package manager:** uv (with hatchling build backend)
- **Python:** >= 3.12
- **Environment:** direnv via `.envrc` (auto-creates venv, runs `uv sync`)

```bash
# Manual setup (if not using direnv)
uv venv && source .venv/bin/activate && uv sync
```

## Common Commands

```bash
# Run the tool
confctl <spec>                    # e.g. confctl tools/kitty

# Lint
ruff check src/

# Type check
mypy src/confctl/

# Format
ruff format src/

# Tests (in Docker)
docker build -f Dockerfile.test -t confctl-test . && docker run --rm confctl-test

# Tests (single test)
docker run --rm confctl-test uv run pytest tests/test_actions.py::TestShAction::test_echo_command -v
```

## Architecture

### Multi-Process Design

- **Main process:** Async Rich-based TUI (Live widget at 10fps)
- **Worker process:** Synchronous dependency resolution
- **Communication:** Multiprocessing Pipe with `AsyncConn` wrapper streaming events between processes

### Core Subsystems

**Spec System** — Dependencies use `resolver::spec` format (e.g. `conf::tools/kitty:main`, `brew::neovim`, `pyenv::python@3.10.4`).

**Resolver Pattern** — Each resolver implements `can_resolve(raw_spec, ctx)` and `resolve(raw_spec, ctx)`. Built-in resolvers: `conf`, `path`, `dir`, `brew`, `pipx`, `pyenv`, `uvx`, `asdf`, `mise`. Registry in `deps/registry.py`.

**Action System** — Decorated functions (`@action`) that perform build steps: `render/file`, `run/sh`, `use/dep`, `show/msg`, etc. Defined in `deps/actions.py` and resolver-specific action files.

**Event System** (`wire/`) — Typed events (`EvOpStart`, `EvOpLog`, `EvOpProgress`, `EvOpError`, `EvOpFinish`) flow from worker to main process, driving UI updates.

**Context System** (`deps/ctx.py`) — `ChainMap`-based hierarchical scoping with lazy Jinja2 template evaluation.

**UI** (`ui.py`) — Rich-based operation tree. Each operation tracks state: `init → in-progress → succeeded|failed`.

### Key Entry Points

- `cli.py:main()` — CLI entry point, sets up async TUI + worker process
- `deps/worker.py` — Worker that resolves dependency specs
- `deps/resolvers/conf/resolver.py` — Loads and executes `.confbuild.py` files

## Branches

- `dev` — development branch (feature branches based here)
- `main` — release branch

## Publishing a release

Released to [PyPI](https://pypi.org/project/confctl/) via `uv`. Build
artifacts land in `dist/` (gitignored).

```bash
# 1. Bump version in pyproject.toml (follow semver)
# 2. Add a new section to CHANGELOG.md describing the release
# 3. Commit and tag
git commit -am "Bump version to X.Y.Z"
git tag vX.Y.Z

# 4. Clean previous artifacts, build, publish
rm -rf dist/
uv build
uv publish    # uses UV_PUBLISH_TOKEN or ~/.pypirc; pass --token if needed

# 5. Push commit + tag
git push origin main
git push origin vX.Y.Z
```

Smoke-test the published wheel before moving on:

```bash
uvx --refresh confctl==X.Y.Z --version
```
