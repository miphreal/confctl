from __future__ import annotations

import time
import typing as t
from collections import defaultdict
from dataclasses import dataclass, field

from rich import tree
from rich.console import ConsoleRenderable

from confctl.ui._rendering import RenderFn

# Op UI class registry
_ops_ui_registry: dict[str, type[OpBase]] = {}


def register_op_ui(cls: type[OpBase]) -> type[OpBase]:
    """Register an OpBase subclass for a specific op_name."""
    if op_name := getattr(cls, "op_name", None):
        _ops_ui_registry[op_name] = cls
    return cls


class OpData(defaultdict):
    def __getattr__(self, name):
        return self.get(name, "<unset>")


@dataclass
class OpBase(ConsoleRenderable):
    op_name: str
    ops: list[OpBase] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    elapsed_time: float = 0
    render_node: tree.Tree | None = None
    render_logs: tree.Tree | None = None
    error: str | None = None
    stop_reason: tuple[str, dict | None] | None = None
    logs: list[str] = field(default_factory=list)
    show_content: bool = True
    show_logs: bool = False
    show_logs_lines: int = 5
    data: OpData = field(default_factory=OpData)

    bubble_ops_deps: bool = False

    HIDDEN_OPS: t.ClassVar[tuple[str, ...]] = tuple()

    def __post_init__(self):
        data = OpData()
        if self.data:
            data.update(self.data)
        self.data = data

    @property
    def elapsed(self):
        if self.started_at is not None:
            finished_at = self.finished_at or time.time()
            new_elapsed = finished_at - self.started_at
            # Make sure we get increasing time
            if new_elapsed >= self.elapsed_time:
                self.elapsed_time = new_elapsed
            return self.elapsed_time
        return 0

    @property
    def state(self):
        if self.started_at is None:
            return "init"
        if self.finished_at is None:
            return "in-progress"
        if self.error is not None or self.stop_reason:
            return "failed"
        return "succeeded"

    @property
    def is_finished(self):
        return self.state in {"failed", "succeeded"}

    def _walk_ops(
        self, ops: list[OpBase], lookup_fn
    ) -> t.Generator[OpBase, None, None]:
        for op in ops:
            if lookup_fn(op):
                yield op
            else:
                yield from self._walk_ops(op.ops, lookup_fn)

    def _visible_ops(self):
        return [op for op in self.ops if op.op_name not in self.HIDDEN_OPS]

    def _build_header(self):
        return RenderFn(lambda: f"{self.op_name}: {self.data}")

    def _build_content(self):
        if not self.render_node:
            return

        for op in self._visible_ops():
            op.build_ui(self.render_node)

        if self.show_logs and self.logs:
            from confctl.ui._widgets import UIOpLogs

            if not self.render_logs:
                self.render_logs = self.render_node.add(UIOpLogs(self))
            elif self.render_node:
                # make sure logs are at the end
                self.render_node.children.remove(self.render_logs)
                self.render_node.children.append(self.render_logs)

    def _render_deps(self):
        if self.render_node:
            from confctl.ui._ops import OpUseDep

            deps = self._walk_ops(self.ops, lambda _op: _op.op_name == "use/dep")
            for dep in deps:
                if isinstance(dep, OpUseDep):
                    dep_text = f"📎 {dep.name}"
                    if all(
                        dep_text != node.label for node in self.render_node.children
                    ):
                        self.render_node.add(dep_text)

    def build_ui(self, parent_node: tree.Tree):
        if self.render_node is None:
            self.render_node = parent_node.add(self._build_header())
        else:
            self.render_node.label = self._build_header()

        if self.error:
            self.show_content = True
            self.show_logs = True

        if self.show_content:
            self._build_content()

        if self.bubble_ops_deps:
            self._render_deps()

    def handle_log(self, log: str):
        if not log.endswith("\n"):
            log = f"{log}\n"
        self.logs.append(log)

    def handle_start(self, op_time: float):
        self.started_at = op_time
        self.on_start()

    def on_start(self):
        pass

    def handle_stop(self, reason: str, data: dict | None = None):
        self.stop_reason = reason, data

    def handle_progress(self, **data):
        self.data.update(data)

    def handle_error(self, error, tb):
        """Tracks an exception/error caught during op execution."""
        self.error = error
        if (tb):
            self.logs.append(tb)

    def handle_finish(self, op_time: float):
        """Called after operation is finished (even if error has happened)."""
        self.finished_at = op_time
        self.on_finish()

    def on_finish(self):
        self.show_content = bool(self.error or self.stop_reason)

    def __rich_console__(self, *args):
        if self.render_node:
            yield self.render_node
