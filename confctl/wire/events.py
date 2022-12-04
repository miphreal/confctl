from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import partial
from multiprocessing.connection import Connection
from pathlib import Path

import typing as t
import traceback
from contextvars import ContextVar
from contextlib import contextmanager

if t.TYPE_CHECKING:
    from confctl.worker import Target

OpPath = tuple[str, ...]

active_op_path: ContextVar[OpPath] = ContextVar("active_op_path", default=())

Op = (
    t.Literal[
        "build/configs",
        "build/target",
        "use/dep",
        "use/dirs",
        "use/conf",
        "run/sh",
        "run/sudo",
        "render/str",
        "render/file",
    ]
    | str
)


@dataclass
class Ev:
    typ: str


@dataclass
class EvOp(Ev):
    op: Op
    op_path: OpPath


@dataclass
class EvOpStart(EvOp):
    typ: t.Literal["op/start"] = field(default="op/start", init=False)
    data: dict
    ts: float = field(default_factory=time.time, init=False)


@dataclass
class EvOpLog(EvOp):
    typ: t.Literal["op/log"] = field(default="op/log", init=False)
    log: str


@dataclass
class EvOpProgress(EvOp):
    typ: t.Literal["op/progress"] = field(default="op/progress", init=False)
    data: dict


@dataclass
class EvOpError(EvOp):
    typ: t.Literal["op/error"] = field(default="op/error", init=False)
    error: str
    tb: str


@dataclass
class EvOpFinish(EvOp):
    typ: t.Literal["op/finish"] = field(default="op/finish", init=False)
    ts: float = field(default_factory=time.time)


@dataclass
class EvDebug(Ev):
    typ: t.Literal["internal/debug"] = field(default="internal/debug", init=False)
    op_path: OpPath
    log: str


Event: t.TypeAlias = t.Union[
    EvOpStart,
    EvOpLog,
    EvOpProgress,
    EvOpError,
    EvOpFinish,
    EvDebug,
]


@dataclass
class OpWrapper:
    ops: "OpsTracking"
    op: Op
    op_path: OpPath

    has_error: bool = False

    def log(self, log: str):
        self.ops.ev(EvOpLog(op=self.op, op_path=self.op_path, log=log))

    def debug(self, log: str):
        self.ops.ev(EvDebug(op_path=self.op_path, log=log))

    def progress(self, **data):
        self.ops.ev(EvOpProgress(op=self.op, op_path=self.op_path, data=data))


class OpsTracking:
    _ev_channel: Connection

    seq_id = iter(range(10**10))

    def __init__(self, events_channel: Connection):
        self._ev_channel = events_channel

    def ev(self, ev: Event):
        self._ev_channel.send(ev)

    @contextmanager
    def op(self, op_name: str, **data):
        op_path = (*active_op_path.get(), self.get_op_id(op_name))

        self.ev(EvOpStart(op=op_name, op_path=op_path, data=data))

        _reset_token = active_op_path.set(op_path)

        op_wrapper = OpWrapper(self, op_name, op_path)
        try:
            yield op_wrapper
        except Exception as e:
            tb = traceback.format_exc()
            self.ev(EvOpError(op=op_name, op_path=op_path, error=repr(e), tb=tb))
            op_wrapper.has_error = True
        finally:
            self.ev(EvOpFinish(op=op_name, op_path=op_path))
            active_op_path.reset(_reset_token)

    def get_track_fn(self, action: str):
        return partial(self.op, action)

    def get_op_id(self, op_name: Op, prefix: str | None = None) -> str:
        next_id = f"{op_name}-{next(self.seq_id)}"
        if prefix:
            return f"{prefix}--{next_id}"
        return next_id

    def debug(self, log: str):
        self.ev(EvDebug(op_path=active_op_path.get(), log=log))

    def track_build_configs(self):
        return self.op("build/configs")

    def track_build(self, target: Target):
        return self.op(
            "build/target",
            target_fqn=str(target.fqn),
            target_name=str(target.name),
            ui_options=dict(target.ui_options),
        )

    def track_dep(self, target: str):
        return self.op("use/dep", name=str(target))

    def track_conf(self, fqn: str, kw: dict):
        return self.op("use/conf", fqn=fqn, config=list(kw.keys()))

    def track_ensure_dirs(self, dirs: tuple[str | Path, ...]):
        return self.op("use/dirs", dirs=[str(d) for d in dirs])

    def track_sh(self, cmd: str):
        return self.op("run/sh", cmd=str(cmd))

    def track_sudo(self, cmd: str):
        return self.op("run/sudo", cmd=str(cmd))

    def track_render_str(self, template: str, ctx: dict):
        return self.op("render/str", template=template)

    def track_render(self, src: str | Path, dst: str | Path):
        return self.op("render/file", src=str(src), dst=str(dst))
