import typing as t

from collections import ChainMap
from pathlib import Path


from confctl.utils.template import LazyTemplate

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry
    from confctl.wire.events import OpsTracking


class Ctx(ChainMap):
    # Globally available context values
    global_ctx: "Ctx"
    registry: "Registry"
    ops: "OpsTracking"
    configs_root: Path

    def __getattr__(self, name):
        try:
            val = self[name]
        except KeyError:
            raise AttributeError(name)

        if isinstance(val, LazyTemplate):
            val = str(val)
            self[name] = val
        return val
