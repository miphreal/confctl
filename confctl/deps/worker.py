from __future__ import annotations

import typing as t

from multiprocessing import Process
from multiprocessing.connection import Connection
from pathlib import Path

from confctl.wire.channel import Channel
from confctl.wire.events import OpsTracking

from .dep import Ctx, Registry


def build_deps(deps: list[str], configs_root: Path, events_channel: Connection):
    ops_tracking = OpsTracking(events_channel)

    with ops_tracking.op("build/configs") as op:
        global_ctx = Ctx()

        registry = Registry(configs_root=configs_root, global_ctx=global_ctx)

        global_ctx["global_ctx"] = global_ctx
        global_ctx["ops"] = ops_tracking
        global_ctx["registry"] = registry

        op.debug("Setup resolvers")
        registry.setup_resolvers()

        op.debug("Resolving deps...")
        for dep in map(registry.dep, deps):
            op.debug(f"Start building {dep.spec.fqn}")
            dep.resolve()

        op.debug("Finished.")


def run_worker(deps: list[str], configs_root: Path, events_channel: Channel):
    proc = Process(
        target=build_deps,
        kwargs={
            "deps": deps,
            "configs_root": configs_root,
            "events_channel": events_channel,
        },
        daemon=True,
    )
    proc.start()

    def _stop():
        if proc.is_alive():
            proc.terminate()

    return _stop
