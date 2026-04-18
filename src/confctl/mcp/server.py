from __future__ import annotations

import json
import sys
from pathlib import Path

from .runner import list_available_specs, run_specs_headless


def _format_run_result(result: dict) -> str:
    lines: list[str] = []
    lines.append(
        f"specs: {result['specs'] or '(default: main)'}  root: {result['configs_root']}"
    )
    lines.append(
        f"status: {'succeeded' if result['succeeded'] else 'FAILED'}  ops: {len(result['ops'])}  errors: {len(result['errors'])}"
    )
    lines.append("")

    for op in result["ops"]:
        depth = max(len(op["op_path"]) - 1, 0)
        indent = "  " * depth
        data_bits = []
        for k, v in (op.get("data") or {}).items():
            s = str(v)
            if len(s) > 80:
                s = s[:77] + "..."
            data_bits.append(f"{k}={s}")
        data_str = f" [{', '.join(data_bits)}]" if data_bits else ""
        lines.append(f"{indent}- {op['op']} ({op['status']}){data_str}")
        for log in op.get("logs", []):
            for log_line in str(log).rstrip().splitlines():
                lines.append(f"{indent}    | {log_line}")
        if op["status"] == "failed":
            lines.append(f"{indent}    ! error: {op.get('error')}")

    if result["errors"]:
        lines.append("")
        lines.append("Errors:")
        for err in result["errors"]:
            lines.append(f"- at {'/'.join(err['op_path'])}: {err['error']}")
            if err.get("traceback"):
                for tb_line in err["traceback"].rstrip().splitlines():
                    lines.append(f"    {tb_line}")

    return "\n".join(lines)


def run_mcp_server(configs_root: Path) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        sys.stderr.write(
            "MCP SDK not installed. Install with: pip install 'confctl[mcp]'\n"
            "or: uv tool install 'confctl[mcp]'\n"
        )
        sys.exit(1)

    default_root = configs_root.resolve()

    mcp = FastMCP("confctl")

    def _resolve_root(configs_root_arg: str | None) -> Path:
        if configs_root_arg:
            return Path(configs_root_arg).expanduser().resolve()
        return default_root

    @mcp.tool()
    async def run_specs(
        specs: list[str] | None = None,
        configs_root: str | None = None,
    ) -> str:
        """Run one or more confctl specs and return a human-readable summary.

        Specs follow the `resolver::spec` format (e.g. `tools/kitty`,
        `conf::tools/shell:zsh`, `brew::neovim`). The default resolver is
        `conf`, so plain paths like `tools/kitty` work. When `specs` is empty
        or omitted, the root config's `main` target is built.

        Args:
            specs: List of specs to build. If empty, builds the root `main` target.
            configs_root: Absolute path to the configs root. Defaults to the
                root the server was started with.
        """
        root = _resolve_root(configs_root)
        result = await run_specs_headless(specs or [], root)
        return _format_run_result(result)

    @mcp.tool()
    async def list_specs(configs_root: str | None = None) -> str:
        """List available confctl specs by scanning the configs root for
        `.confbuild.py` files. Returns one spec per line."""
        root = _resolve_root(configs_root)
        entries = list_available_specs(root)
        if not entries:
            return f"No .confbuild.py files found under {root}"
        lines = [f"configs_root: {root}", ""]
        for entry in entries:
            lines.append(f"{entry['spec']}\t{entry['path']}")
        return "\n".join(lines)

    @mcp.tool()
    async def run_specs_json(
        specs: list[str] | None = None,
        configs_root: str | None = None,
    ) -> str:
        """Same as `run_specs` but returns the raw structured result as JSON."""
        root = _resolve_root(configs_root)
        result = await run_specs_headless(specs or [], root)
        return json.dumps(result, indent=2, default=str)

    mcp.run()
