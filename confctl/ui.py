from __future__ import annotations

import asyncio
import time
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

from rich import tree
from rich.console import Group, RenderableType, ConsoleRenderable
from rich.status import Status
from rich.columns import Columns
from rich.panel import Panel

from confctl.wire import events
from confctl.wire.channel import AsyncChannel

CWD = str(Path.cwd().absolute())
HOME = str(Path.home().absolute())


def render_path(path: str | Path, home_color="medium_purple4", cwd_color="steel_blue"):
    path_obj = Path(path)
    is_dir = path_obj.exists() and path_obj.is_dir()

    path = str(path).rstrip("/")

    if path.startswith(CWD):
        path = path.removeprefix(CWD).lstrip("/")
        path = f"[i {cwd_color}].[/]/{path}"

    elif path.startswith(HOME):
        path = path.removeprefix(HOME).lstrip("/")
        path = f"[i {home_color}]~[/]/{path}"

    if "/" in path:
        parent, name = path.rsplit("/", 1)
        path = f"[i]{parent}[/]/[b]{name}[/]"

    if is_dir:
        path = f"{path}[grey78 not bold]/[/]"

    return path


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
    show_logs_lines: int = 5
    progress_data: dict = field(default_factory=dict)

    bubble_ops_deps: bool = False

    HIDDEN_OPS: t.ClassVar[tuple[str, ...]] = tuple()

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

    def _walk_ops(
        self, ops: list["OpBase"], lookup_fn
    ) -> t.Generator[OpBase, None, None]:
        for op in ops:
            if lookup_fn(op):
                yield op
            else:
                yield from self._walk_ops(op.ops, lookup_fn)

    def _visible_ops(self):
        return [op for op in self.ops if op.op_name not in self.HIDDEN_OPS]

    def _build_header(self):
        return f"{self.op_name}: {self.op_data}"

    def _build_content(self):
        if not self.render_node:
            return

        for op in self._visible_ops():
            op.build_ui(self.render_node)

        if self.show_logs and self.logs:
            if not self.render_logs:
                self.render_logs = self.render_node.add(UIOpLogs(self))
            elif self.render_node:
                # make sure logs are at the end
                self.render_node.children.remove(self.render_logs)
                self.render_node.children.append(self.render_logs)

    def _render_deps(self):
        if self.render_node:
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

        self.render_node.expanded = self.show_content
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

    def handle_progress(self, **data):
        self.progress_data.update(data)

    def handle_error(self, error, tb):
        """Tracks an exception/error caught during op execution."""
        self.error = error
        self.logs.append(tb)

    def handle_finish(self, op_time: float):
        """Called after operation is finished (even if error has happened)."""
        self.finished_at = op_time
        self.on_finish()

    def on_finish(self):
        # self.show_content = False  # TODO: uncomment
        pass

    def __rich_console__(self, *args):
        if self.render_node:
            yield self.render_node


class UIBuildTargetHeader(ConsoleRenderable):
    op: OpBuildDep

    def __init__(self, op: OpBuildDep):
        self.op = op

    def render_target_state(self):
        op = self.op
        name = f"[i grey50]{op.base_name}[/]:[b]{op.target_name}[/]"
        resolver = self.op.resolver
        if resolver:
            name = f"[i grey70]{resolver}::[/]{name}"

        _build_time = round(op.elapsed, 1)
        if _build_time >= 0.1:
            build_time = f"[i grey70 not bold]({_build_time:.1f}s)[/]"
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
            yield self.render_logs(self.op.logs, max_output=self.op.show_logs_lines)


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
        rendered = self.op.progress_data.get("rendered")
        if rendered is not None and self.op.template != rendered:
            yield self.render(self.op.template, rendered)


@dataclass
class OpBuildDep(OpBase):
    op_name: str = "build/dep"
    fqn: str = "unset"
    name: str = "unset"
    ui_options: dict = field(default_factory=dict)
    show_content: bool = True

    bubble_ops_deps: bool = True

    HIDDEN_OPS = (
        "use/conf",
        "render/str",
    )

    @property
    def target_name(self):
        return self.progress_data.get("actual_target", self.name)

    @property
    def resolver(self):
        parts = self.fqn.split("::", 1)
        if len(parts) == 2:
            return parts[0]
        return ""

    @property
    def base_name(self):
        fqn = self.fqn.split("::", 1)[-1]
        return fqn.replace(f":{self.target_name or '...'}", "")

    def _build_header(self):
        return UIBuildTargetHeader(self)

    def build_ui(self, parent_node: tree.Tree):
        super().build_ui(parent_node)

        if (
            self.render_node
            and self.ui_options.get("visibility", "visible") == "hidden"
            and self.render_node in parent_node.children
        ):
            parent_node.children.remove(self.render_node)

    def on_finish(self):
        self.show_content = True


@dataclass
class OpRender(OpBase):
    op_name: str = "render/file"
    src: str = "unset"
    dst: str = "unset"
    show_content: bool = False

    def _build_header(self):
        src = render_path(self.progress_data.get("rendered_src", self.src))
        dst = render_path(self.progress_data.get("rendered_dst", self.dst))
        return f"📝 [grey50]{src} [grey70]⤏[/] {dst}[/]"


@dataclass
class OpRenderStr(OpBase):
    op_name: str = "render/str"
    template: str = "unset"
    show_content: bool = False

    def _build_header(self):
        return UIRenderStr(self)


@dataclass
class OpRunSh(OpBase):
    op_name: str = "run/sh"
    cmd: str = "unset"
    show_content: bool = True
    show_logs: bool = True
    sudo: bool = False

    def _build_header(self):
        elapsed_time = round(self.elapsed, 1)
        if elapsed_time >= 1:
            run_time = f"[grey70 i]({elapsed_time:.1f}s)[/]"
        else:
            run_time = ""

        command = self.progress_data.get("cmd", self.cmd)

        exit_code = self.progress_data.get("exitcode")
        finish_state = "⏳"
        if isinstance(exit_code, int):
            if exit_code == 0:
                finish_state = "🆗"
            else:
                finish_state = "💢"
                command = f"[indian_red]{command} [{exit_code}][/]"
        else:
            pid = self.progress_data.get("pid")
            if pid is not None:
                command = f"{command} [grey70 i][pid {pid}][/]"

        if self.sudo:
            command = f"[b]\\[sudo][/] {command}"
        return f"📜{finish_state} [grey50]{command}[/] {run_time}"

    def on_finish(self):
        exit_code = self.progress_data.get("exitcode")
        self.show_content = bool(exit_code is not None and exit_code != 0)


@dataclass
class OpUseDep(OpBase):
    op_name: str = "use/dep"
    name: str = "unset"

    def _build_header(self):
        return f"📎 {self.name}"


@dataclass
class OpUseDirs(OpBase):
    op_name: str = "use/dirs"
    dirs: list[str] | None = None
    folders: list[str] = field(default_factory=list)

    def _build_header(self):
        if len(self.folders) == 1:
            return f"📁 [grey50]{render_path(self.folders[0])}[/]"
        return Group(*[f"️📁 [grey50]{render_path(f)}[/]" for f in self.folders])

    def handle_progress(self, folder):
        self.folders.append(folder)


@dataclass
class OpBuildConfigs(OpBase):
    op_name: str = "build/specs"
    HIDDEN_OPS = ("use/conf",)

    # Debug
    # show_logs: bool = True
    # show_logs_lines: int = 1000

    def build_ui(self):
        if self.render_node is None:
            self.render_node = tree.Tree(
                "🚀 [b green]Building configurations...",
                highlight=False,
                guide_style="grey70",
            )
        self._build_content()

    def __rich_console__(self, *args):
        self.show_logs = bool(self.error)
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
            case ("build/specs", _):
                return OpBuildConfigs()
            case (
                "build/dep",
                {
                    "target_fqn": str(fqn),
                    "target_name": str(name),
                    "ui_options": dict(ui_options),
                },
            ):
                return OpBuildDep(fqn=fqn, name=name, ui_options=ui_options)
            case ("render/file", {"src": str(src), "dst": str(dst)}):
                return OpRender(src=src, dst=dst)
            case ("render/str", {"template": str(template)}):
                return OpRenderStr(template=template)
            case ("run/sh", {"cmd": str(cmd)}):
                return OpRunSh(cmd=cmd)
            case ("run/sudo", {"cmd": str(cmd)}):
                return OpRunSh(cmd=cmd, sudo=True)
            case ("use/dep", {"name": str(name)}):
                return OpUseDep(name=name)
            case ("use/dirs", {"dirs": dirs}):
                return OpUseDirs(dirs=dirs)
        return OpBase(op_name=op_name, op_data=op_data)

    async def listen_to_channel(self, channel: AsyncChannel):
        async for event in channel.recv():
            match event:
                case events.EvOpStart() as ev:
                    op = self.build_op(op_name=ev.op, op_data=ev.data)

                    if self.root_op is None and isinstance(op, OpBuildConfigs):
                        self.root_op = op

                    parent = self.get_parent_node(ev.op_path)
                    if self.root_op and isinstance(op, OpBuildDep):
                        self.root_op.ops.append(op)
                    elif parent:
                        parent.ops.append(op)

                    self.ops_map[ev.op_path] = op

                    op.handle_start(ev.ts)

                case events.EvOpLog(op_path=op_path, log=log):
                    op = self.ops_map[op_path]
                    op.handle_log(log)
                case events.EvOpProgress(op_path=op_path, data=data):
                    op = self.ops_map[op_path]
                    op.handle_progress(**data)
                case events.EvOpError(op_path=op_path, error=error, tb=tb):
                    op = self.ops_map[op_path]
                    op.handle_error(error, tb)
                case events.EvOpFinish(op_path=op_path, op=op_name, ts=ts):
                    op = self.ops_map[op_path]
                    op.handle_finish(ts)
                    if op_name == "build/specs":
                        return
                case events.EvDebug(op_path=op_path, log=log):
                    op = self.root_op if self.root_op else self.ops_map[op_path]
                    op.handle_log(f"DEBUG: {log}\n")

    def __rich_console__(self, *args):
        yield self.root_op if self.root_op else "Loading..."
