import argparse
import asyncio
import os
import signal
from pathlib import Path

from rich.console import Console
from rich.live import Live

from importlib.metadata import version

from confctl.wire.channel import create_channel
from confctl.deps.worker import run_worker
from confctl.ui import OpsView


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


def main():
    parser = argparse.ArgumentParser(
        prog="confctl",
        description="Configuration management tool",
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
        default=Path(os.getenv("CONFCTL_CONFIGS_ROOT", str(Path.cwd()))),
        help="Root directory for configurations (default: $CONFCTL_CONFIGS_ROOT or cwd)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(tui_app(specs=args.specs, configs_root=args.configs_root))
    except KeyboardInterrupt:
        pass
