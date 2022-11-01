import asyncio
import os
import signal
import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live

from confctl.channel import create_channel
from confctl.worker import run_worker
from confctl.ui import OpsView


async def tui_app():
    targets: list[str] = sys.argv[1:]
    configs_root = Path(os.getenv("CONFCTL_CONFIGS_ROOT", str(Path.cwd())))

    ui_channel_end, worker_channel_end = create_channel()

    ui = OpsView()

    stop_worker = run_worker(
        targets=targets, configs_root=configs_root, events_channel=worker_channel_end
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
    try:
        asyncio.run(tui_app())
    except KeyboardInterrupt:
        pass
