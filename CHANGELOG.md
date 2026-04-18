# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-04-19

### Added
- MCP server (`confctl mcp`) for running specs from LLM clients.
- `mise` contrib resolver with auto-bootstrap support.
- Fuzzy-match suggestions when a spec can't be resolved — `Registry` now
  queries each resolver's optional `list_specs()` and returns the closest
  matches via `difflib`.
- `ConfResolver.list_specs()` that scans `configs_root` for `.confbuild.py`
  and `*.py` configs.

### Changed
- Unresolved specs now surface as a dedicated red "✗ Error" panel in the TUI
  instead of a raw traceback in the generic logs panel. User-facing errors
  carry a `user_facing` marker so the event pipeline skips the traceback.
- `OpBase` tracks `error_tb` separately from the error message.

## [0.6.0] - 2026-03-25

### Added
- `asdf` contrib resolver with auto-bootstrap support.
- `uvx` contrib resolver with auto-bootstrap support.
- README sections covering the new `uvx` and `asdf` resolvers.

### Fixed
- `uvx` resolver parses text output correctly and handles already-installed
  executables.

## [0.5.0] - 2026-03-08

### Added
- `--version` flag on the CLI.
- Comprehensive README with usage docs and examples.
- Test suite.

### Changed
- Refactored architecture into clearer subsystems (deps, wire, ui).
- Split the monolithic `ui.py` into a `ui/` package and generalized state
  rendering.
