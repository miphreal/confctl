from __future__ import annotations

import time
from multiprocessing.connection import Connection
from pathlib import Path

import typing as t
import traceback
from contextvars import ContextVar
from contextlib import contextmanager

if t.TYPE_CHECKING:
    from confctl.worker import TargetCtl

OpPath = tuple[str, ...]

active_op_path: ContextVar[OpPath] = ContextVar("active_op_path", default=())


class Event(t.NamedTuple):
    ev_type: str
    ev_data: t.Any


class OpWrapper:
    ops: OpsTracking
    op_path: OpPath

    def __init__(self, ops: OpsTracking, op_path: OpPath) -> None:
        self.ops = ops
        self.op_path = op_path

    def log(self, log_msg: str):
        self.ops.track_event("op/log", (self.op_path, log_msg))

    def progress(self, **data):
        self.ops.track_event("op/progress", (self.op_path, data))


class OpsTracking:
    _ev_channel: Connection

    seq_id = iter(range(10**10))

    def __init__(self, events_channel: Connection):
        self._ev_channel = events_channel

    def track_event(self, ev_type: str, ev_data: t.Any):
        self._ev_channel.send(Event(ev_type, ev_data))

    @contextmanager
    def op(self, op_name: str, **data):
        op_path = (*active_op_path.get(), self.get_op_id(op_name))

        self.track_event("op/start", (op_path, op_name, data, time.time()))

        _reset_token = active_op_path.set(op_path)

        try:
            yield OpWrapper(self, op_path)
        except Exception as e:
            self.track_event("op/error", (op_path, repr(e), traceback.format_exc()))
        finally:
            self.track_event("op/finish", (op_path, op_name, time.time()))
            active_op_path.reset(_reset_token)

    def get_op_id(self, op_name: str, prefix: str | None = None) -> str:
        next_id = f"{op_name}-{next(self.seq_id)}"
        if prefix:
            return f"{prefix}--{next_id}"
        return next_id

    def debug(self, log: str):
        self.track_event("internal/debug", (active_op_path.get(), log))

    def track_build(self, target: TargetCtl):
        return self.op(
            "build/target", target_fqn=str(target.fqn), target_name=str(target.name)
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
