from multiprocessing import Process
from multiprocessing.connection import Connection
from pathlib import Path

from confctl.wire.channel import Channel
from confctl.wire.events import OpsTracking

from .registry import Registry
from .ctx import Ctx


DEFAULT_RESOLVERS = [
    "confctl.deps.resolvers.path.path",
    "confctl.deps.resolvers.path.dir",
    "confctl.deps.resolvers.conf.setup",
]


def build_specs(specs: list[str], configs_root: Path, events_channel: Connection):
    ops_tracking = OpsTracking(events_channel)

    with ops_tracking.op("build/specs") as op:
        global_ctx = Ctx()

        registry = Registry(global_ctx=global_ctx)

        global_ctx["global_ctx"] = global_ctx
        global_ctx["ops"] = ops_tracking
        global_ctx["registry"] = registry
        global_ctx["configs_root"] = configs_root

        op.debug("Setup resolvers")
        registry.setup_resolvers(DEFAULT_RESOLVERS)

        op.debug("Resolving specs...")
        if not specs:
            specs = ['conf:::main']
        for spec in specs:
            op.debug(f"Start resolving {spec}")
            registry.resolve(spec)

        op.debug("Finished.")


def run_worker(specs: list[str], configs_root: Path, events_channel: Channel):
    proc = Process(
        target=build_specs,
        kwargs={
            "specs": specs,
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
