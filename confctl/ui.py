from __future__ import annotations

import asyncio
import time
import typing as t
from dataclasses import dataclass, field

from rich import tree
from rich.console import Group, RenderableType, ConsoleRenderable
from rich.status import Status
from rich.columns import Columns
from rich.panel import Panel

from confctl.channel import AsyncChannel


@dataclass
class OpBase(ConsoleRenderable):
    op_name: str
    op_data: dict | None = None
    ops: list[OpBase] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    elapsed_time: float = 0
    render_node: tree.Tree | None = None
    render_logs: tree.Tree | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    show_content: bool = True
    show_logs: bool = False

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
        if self.error is not None:
            return "failed"
        return "succeeded"

    @property
    def is_finished(self):
        return self.state in {"failed", "succeeded"}

    def _build_header(self):
        return f"{self.op_name}: {self.op_data}"

    def _build_content(self):
        if not self.render_node:
            return

        for op in self.ops:
            op.build_ui(self.render_node)

        if self.show_logs and self.logs:
            if not self.render_logs:
                self.render_logs = self.render_node.add(UIOpLogs(self))
            elif self.render_node:
                # make sure logs are at the end
                self.render_node.children.remove(self.render_logs)
                self.render_node.children.append(self.render_node)

    def build_ui(self, parent_node: tree.Tree):
        if self.render_node is None:
            self.render_node = parent_node.add(self._build_header())

        self.render_node.expanded = self.show_content
        if self.show_content:
            self._build_content()

    def handle_log(self, log: str):
        self.logs.append(log)

    def handle_start(self, op_time: float):
        self.started_at = op_time

    def handle_progress(self, **data):
        pass

    def handle_error(self, error, tb):
        self.error = error
        self.logs.append(tb)

    def handle_finish(self, op_time: float):
        self.finished_at = op_time
        self.on_finish()

    def on_finish(self):
        self.show_content = False

    def __rich_console__(self, *args):
        if self.render_node:
            yield self.render_node


class UIBuildTargetHeader(ConsoleRenderable):
    op: OpBuildTarget

    def __init__(self, op: OpBuildTarget):
        self.op = op

    def render_target_state(self):
        op = self.op
        name = f"[i grey70]{op.base_name}[/]:[b]{op.name}"

        _build_time = round(op.elapsed, 1)
        if _build_time >= 0.1:
            build_time = f"[i]({_build_time:.1f}s)[/]"
        else:
            build_time = ""

        match op.state:
            case "init":
                return f"⏳ [sky_blue3 i]{name}"
            case "in-progress":
                return Columns([f"🚀 {name}", Status(""), build_time])
            case "succeeded":
                if build_time and _build_time == int(_build_time):
                    build_time = f"[i]({int(_build_time)}s)[/]"
                return f"✅ [green]{name} {build_time}"
            case "failed":
                return f"💢 [red]{name} {build_time}"
        return f"? {name}"

    def __rich_console__(self, *args):
        yield self.render_target_state()


class UIOpLogs(ConsoleRenderable):
    op: OpBase

    def __init__(self, op: OpBase):
        self.op = op

    def render_logs(self, logs: list[str], max_output=5):
        len_log = len(logs)
        log_lines = (
            f"... truncated {len_log- max_output} line(s) ...\n"
            if len_log > max_output
            else ""
        ) + ("".join(logs[-max_output:]))
        return Panel(log_lines.strip(), title="Logs", title_align="left")

    def __rich_console__(self, *args):
        if self.op.logs:
            yield self.render_logs(self.op.logs)


class UIRenderStr(ConsoleRenderable):
    op: OpRenderStr

    def __init__(self, op: OpRenderStr):
        self.op = op

    def render(self, template: str, rendered: str | None):
        renderables: list[RenderableType] = []

        if len(template) > 100:
            template = f"{template[:100]}...{len(template)-100} chars more..."
            renderables.append(
                Panel(template, title="Template str", title_align="left")
            )
        else:
            renderables.append(f"Template string: {template}")

        if rendered is not None and template != rendered:
            if len(rendered) > 100:
                rendered = f"{rendered[:100]}...{len(rendered)-100} chars more..."
                renderables.append(
                    Panel(rendered or "", title="Rendered as", title_align="left")
                )
            else:
                renderables.append(f"    [grey70 i]Rendered as:[/] {rendered}")

        return Group(*renderables)

    def __rich_console__(self, *args):
        if self.op.template != self.op.rendered:
            yield self.render(self.op.template, self.op.rendered)


@dataclass
class OpBuildTarget(OpBase):
    op_name: str = "build/target"
    fqn: str = "unset"
    name: str = "unset"
    show_content: bool = True

    @property
    def base_name(self):
        return self.fqn.replace(f":{self.name}", "")

    def _build_header(self):
        return UIBuildTargetHeader(self)

    def on_finish(self):
        self.show_content = True


@dataclass
class OpRender(OpBase):
    op_name: str = "build/target"
    src: str = "unset"
    dst: str = "unset"

    def _build_header(self):
        return f"Render {self.src} ⤏ {self.dst}"


@dataclass
class OpRenderStr(OpBase):
    op_name: str = "build/target"
    template: str = "unset"
    rendered: str | None = None
    show_content: bool = False

    def _build_header(self):
        return UIRenderStr(self)

    def handle_progress(self, rendered: str):
        self.rendered = rendered


@dataclass
class OpBuildConfigs(OpBase):
    op_name: str = "build/configs"

    def build_ui(self):
        if self.render_node is None:
            self.render_node = tree.Tree(
                "🚀 [b green]Building configurations...",
                highlight=True,
                guide_style="grey70",
            )
        self._build_content()

    def __rich_console__(self, *args):
        self.build_ui()
        yield self.render_node


class OpsView(ConsoleRenderable):
    root_op: OpBuildConfigs | None = None

    def __init__(self) -> None:
        self.ops_map: dict[tuple[str, ...], OpBase] = {}

    def get_parent_node(self, op_path: tuple[str, ...]):
        for l in range(len(op_path), 0, -1):
            node = self.ops_map.get(tuple(op_path[:l]))
            if node is not None:
                return node
        return None

    def build_op(self, op_name: str, op_data):
        match (op_name, op_data):
            case ("build/configs", _):
                return OpBuildConfigs()
            case ("build/target", {"target_fqn": str(fqn), "target_name": str(name)}):
                return OpBuildTarget(fqn=fqn, name=name)
            case ("render/file", {"src": str(src), "dst": str(dst)}):
                return OpRender(src=src, dst=dst)
            case ("render/str", {"template": str(template)}):
                return OpRenderStr(template=template)
        return OpBase(op_name=op_name, op_data=op_data)

    async def listen_to_channel(self, channel: AsyncChannel):
        async for event in channel.recv():
            match event:
                case ("op/start", (op_path, op_name, op_data, op_time)):
                    op = self.build_op(op_name=op_name, op_data=op_data)

                    parent = self.get_parent_node(op_path)
                    if parent:
                        parent.ops.append(op)
                    elif self.root_op is None and isinstance(op, OpBuildConfigs):
                        self.root_op = op

                    self.ops_map[op_path] = op

                    op.handle_start(op_time)

                case ("op/log", (op_path, log)):
                    op = self.ops_map[op_path]
                    op.handle_log(log)
                case ("op/progress", (op_path, dict(data))):
                    op = self.ops_map[op_path]
                    op.handle_progress(**data)
                case ("op/error", (op_path, error, tb)):
                    op = self.ops_map[op_path]
                    op.handle_error(error, tb)
                case ("op/finish", (op_path, op_name, op_time)):
                    op = self.ops_map[op_path]
                    op.handle_finish(op_time)
                    if op_name == "build/configs":
                        return

    def __rich_console__(self, *args):
        yield self.root_op if self.root_op else "Loading..."


def render_operations(t_node: tree.Tree, operations: list):
    for _op in operations:
        match _op:
            case ops_info.DepOperation(target=target) as dep_op:
                if callable(target):
                    target = f"fn: {target.__name__}"
                render_operations(
                    t_node.add(f"Requested dependency: {target}"), dep_op.nested
                )
            case ops_info.RenderStrOperation(
                template=template, ctx=ctx, rendered=rendered
            ) as render_str_op:
                if rendered is not None and template != rendered:
                    if len(template) > 100:
                        template = (
                            f"{template[:100]}...{len(template)-100} chars more..."
                        )
                    if len(rendered) > 100:
                        rendered = (
                            f"{rendered[:100]}...{len(rendered)-100} chars more..."
                        )
                    render_operations(
                        t_node.add(
                            Group(
                                Panel(template, title="Template", title_align="left"),
                                Panel(rendered, title="Rendered", title_align="left"),
                            )
                        ),
                        render_str_op.nested,
                    )
            case ops_info.RenderOperation(src=src, dst=dst) as render_op:
                render_operations(t_node.add(), render_op.nested)
            case ops_info.EnsureDirsOperation(folders=folders) as ensure_dirs_op:
                if len(folders) > 1:
                    render_operations(
                        t_node.add(f"🗂️ Ensure {len(folders)} folders exist"),
                        ensure_dirs_op.nested,
                    )
                else:
                    render_operations(t_node, ensure_dirs_op.nested)
            case ops_info.ShOperation(cmd=cmd, logs=logs) as sh_op:
                _node = t_node.add(f"💲 {cmd}")
                render_operations(_node, sh_op.nested)
                _node.add(render_log(logs))
