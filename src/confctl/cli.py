import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live

from importlib.metadata import version

from confctl.wire.channel import create_channel
from confctl.deps.worker import run_worker
from confctl.ui import OpsView


def _default_configs_root() -> Path:
    return Path(os.getenv("CONFCTL_CONFIGS_ROOT", str(Path.cwd())))


async def tui_app(specs: list[str], configs_root: Path):
    ui_channel_end, worker_channel_end = create_channel()

    ui = OpsView()

    stop_worker = run_worker(
        specs=specs, configs_root=configs_root, events_channel=worker_channel_end
    )

    try:
        with Live(
            ui, refresh_per_second=10, vertical_overflow="crop", screen=True
        ) as live:

            def _sig_handler():
                stop_worker()
                live.stop()
                exit(1)

            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, _sig_handler)
            loop.add_signal_handler(signal.SIGTERM, _sig_handler)

            await ui.listen_to_channel(ui_channel_end)

        stop_worker()

    finally:
        # Print final state
        Console().print(ui)


def _run_mcp_cli(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="confctl mcp",
        description="Run a confctl MCP server over stdio",
    )
    parser.add_argument(
        "--configs-root",
        "-C",
        type=Path,
        default=_default_configs_root(),
        help="Root directory for configurations (default: $CONFCTL_CONFIGS_ROOT or cwd)",
    )
    args = parser.parse_args(argv)

    from confctl.mcp import run_mcp_server

    run_mcp_server(configs_root=args.configs_root)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        _run_mcp_cli(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        prog="confctl",
        description="Configuration management tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "subcommands:\n"
            "  mcp                   run a confctl MCP server over stdio\n"
            "                        (see `confctl mcp --help`)\n"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('confctl')}"
    )
    parser.add_argument(
        "specs",
        nargs="*",
        default=[],
        help="Specs to build (e.g. tools/kitty, conf::tools/shell:zsh)",
    )
    parser.add_argument(
        "--configs-root",
        "-C",
        type=Path,
        default=_default_configs_root(),
        help="Root directory for configurations (default: $CONFCTL_CONFIGS_ROOT or cwd)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(tui_app(specs=args.specs, configs_root=args.configs_root))
    except KeyboardInterrupt:
        pass
