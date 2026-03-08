from __future__ import annotations

import typing as t
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

if t.TYPE_CHECKING:
    from confctl.deps.ctx import Ctx
    from confctl.deps.dep import Dep
    from confctl.deps.registry import Registry
    from confctl.wire.events import OpsTracking


@dataclass
class RuntimeServices:
    ops: OpsTracking
    registry: Registry
    configs_root: Path


active_services: ContextVar[RuntimeServices] = ContextVar("active_services")
active_ctx: ContextVar[Ctx] = ContextVar("active_ctx")
active_caller: ContextVar[Dep | None] = ContextVar("active_caller", default=None)
