from __future__ import annotations

import os
import sys
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from collections import ChainMap
from typing import Any, Callable, Literal, Mapping
from urllib.parse import parse_qsl
from threading import Timer

from jinja2 import Template


@dataclass
class LazyTemplate:
    template: str
    render: Callable[[str], str]

    def __str__(self) -> str:
        return self.render(self.template)


def load_python_module(path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("tmp", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Ctx(ChainMap):
    def __getattr__(self, name):
        try:
            val = self[name]
        except KeyError:
            raise AttributeError(name)

        if isinstance(val, LazyTemplate):
            val = str(val)
            self[name] = val
        return val


@dataclass
class Operation:
    started: float | None = field(init=False, default=None)
    finished: float | None = field(init=False, default=None)
    state: Literal["init", "in-progress", "succeed", "failed"] = field(
        init=False, default="init"
    )
    error: Exception | None = field(init=False, default=None)
    nested: list[Operation] = field(init=False, default_factory=list)
    _active_operation_state_token: Token | None = field(init=False, default=None)

    @property
    def is_finished(self):
        return self.state in {"succeed", "failed"}

    def track_start_time(self):
        self.started = time.time()

    def track_finish_time(self):
        self.finished = time.time()

    @property
    def elapsed(self) -> float:
        if self.started is not None:
            return (self.finished or time.time()) - self.started
        return 0.0

    def __enter__(self) -> Operation:
        self.track_start_time()
        self.state = "in-progress"
        self._active_operation_state_token = active_operation.set(self)
        return self

    def __exit__(self, exc_type, exc_val, *args):
        if exc_type is not None:
            self.state = "failed"
            self.error = exc_val
        else:
            self.state = "succeed"
        self.track_finish_time()
        active_operation.reset(self._active_operation_state_token)
        self._active_operation_state_token = None

    def log(self, log: str):
        op_log = LogOperation(log=log)
        self.nested.append(op_log)
        return op_log


@dataclass
class LogOperation(Operation):
    log: str


@dataclass
class BuildOperation(Operation):
    target: TargetCtl


@dataclass
class DepOperation(Operation):
    target: str | Callable


@dataclass
class RenderStrOperation(Operation):
    template: str
    ctx: Ctx
    rendered: str | None = None


@dataclass
class ConfOperation(Operation):
    kw: dict


@dataclass
class EnsureDirsOperation(Operation):
    folders: list[str | Path]


@dataclass
class ShOperation(Operation):
    cmd: str
    logs: list[str]


@dataclass
class RenderOperation(Operation):
    src: str | Path
    dst: str | Path


active_operation: ContextVar[Operation | None] = ContextVar(
    "active_operation", default=None
)

OPS_MAP = {
    "log": LogOperation,
    "build": BuildOperation,
    "conf": ConfOperation,
    "dep": DepOperation,
    "render_str": RenderStrOperation,
    "render": RenderOperation,
    "ensure_dirs": EnsureDirsOperation,
    "sh": ShOperation,
}


def op(name: str, **kwargs):
    op_cls = OPS_MAP[name]
    op_obj = op_cls(**kwargs)
    active_op = active_operation.get()
    if active_op is not None:
        active_op.nested.append(op_obj)
    return op_obj


def log(log: str):
    log_op = LogOperation(log=log)
    active_op = active_operation.get()
    if active_op is not None:
        active_op.nested.append(log_op)
    return log_op


class TargetCtl:
    TemplateCls = Template

    registry: Registry
    build_file: Path
    fqn: str
    base_name: str
    name: str
    fn: Callable
    ctx: Ctx

    building_operation: BuildOperation

    def __init__(
        self,
        registry: Registry,
        build_file: Path,
        fqn: str,
        base_name: str,
        name: str,
        fn: Callable,
        ctx: Ctx,
    ):
        self.registry = registry
        self.build_file = build_file
        self.fqn = fqn
        self.base_name = base_name
        self.name = name
        self.fn = fn
        self.ctx = ctx
        self.building_operation = BuildOperation(target=self)

    def __getattr__(self, name):
        return getattr(self.ctx, name)

    def __repr__(self):
        return f"Target({self.fqn})"

    def build(self):
        with self.building_operation:
            self.fn(self)

    def dep(self, target: str | Callable):
        with op("dep", target=target) as _op:
            t = self.registry.resolve(self.render_str(target))
            _op.nested.append(t.building_operation)
            t.build()
        return t

    def conf(self, **kw):
        def _nest_ctx(val):
            if isinstance(val, Mapping):
                return Ctx({k: _nest_ctx(v) for k, v in val.items()})
            if isinstance(val, str):
                return LazyTemplate(val, self.render_str)
            return val

        with op("conf", kw=kw):
            for k, v in kw.items():
                self.ctx[k] = _nest_ctx(v)

    def ensure_dirs(self, *folders: str | Path):
        with op("ensure_dirs", folders=folders):
            for f in folders:
                log(f"📁 Ensure [i]{f}[/] path exists.")
                folder = Path(self.render_str(f)).expanduser()
                folder.mkdir(parents=True, exist_ok=True)

    def sh(self, command: str, failsafe=False):
        import subprocess

        logs: list[str] = []

        with op("sh", cmd=command, logs=logs):
            cmd = self.render_str(command)

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True
            )

            while process.poll() is None:
                log = process.stdout.readline().decode("utf8")
                logs.append(log)
            logs.extend(l.decode("utf8") for l in process.stdout.readlines())
            process.stdout.close()

            return logs

    def render_str(self, template, **extra_context):
        if isinstance(template, str):
            ctx = self.ctx
            if extra_context:
                ctx = ctx.new_child(extra_context)
            with op("render_str", template=template, ctx=ctx) as _op:
                compiled_template = self.TemplateCls(template)
                compiled_template.globals["dep"] = self.dep

                rendered = compiled_template.render(ctx)
                _op.rendered = rendered
                return rendered
        return template

    def _try_relative_path(self, path: str | Path) -> Path:
        return self.build_file.parent.joinpath(Path(path).expanduser())

    def render(self, src: str | Path, dst: str | Path, **extra_context):
        with op("render", src=src, dst=dst):
            src = self._try_relative_path(self.render_str(src))
            dst = Path(self.render_str(dst)).expanduser()
            self.ensure_dirs(dst.parent)

            # with src.open("rt") as f_in, dst.open("wt") as f_out:
            #     f_out.write(self.render_str(f_in.read(), **extra_context))


def normalize_target_name(name: str):
    name = name.removeprefix("./")
    if not name.startswith("//"):
        name = f"//{name}"
    return name


class Registry:
    targets_map: dict[str, TargetCtl]

    def __init__(self) -> None:
        self.targets_map = {}

    def __contains__(self, name: str):
        return name in self.targets_map

    def add(self, targets: TargetCtl):
        for t in targets:
            self.targets_map[t.fqn] = t

            # if target name matches base folder name, we consider this target as the
            # main folder target.
            if t.base_name.endswith(f"/{t.name}"):
                # do not overwrite if already set
                self.targets_map.setdefault(t.base_name, t)

            # if target name is "main", it's considered as the main folder target.
            if t.name == "main":
                self.targets_map[t.base_name] = t

    def resolve(self, target: str | Callable):
        try:
            if isinstance(target, str):
                target = normalize_target_name(target)
                return self.targets_map[target]

            return next(_t for _t in self.targets_map.values() if _t.fn is target)
        except (KeyError, StopIteration):
            raise RuntimeError(f"Target '{target}' cannot be found.")


def parse_target(t: str):
    t = t.strip()
    parts = t.split("?", 1)
    extra_ctx = {}
    if len(parts) == 2:
        t, params = parts
        extra_ctx = dict(
            parse_qsl(params, keep_blank_values=True), __raw_extra_ctx__=params
        )

    return normalize_target_name(t), extra_ctx


def gen_targets(build_file: Path, global_ctx: Ctx, root_path: Path, registry: Registry):
    build_module = load_python_module(build_file)

    base_name = str(build_file.parent.relative_to(root_path))
    if base_name == ".":
        base_name = ""

    targets_fns = [
        fn
        for fn in vars(build_module).values()
        if callable(fn) and not fn.__name__.startswith("_")
    ]

    for fn in targets_fns:
        target_name = fn.__name__
        yield TargetCtl(
            registry=registry,
            build_file=build_file,
            name=target_name,
            base_name=normalize_target_name(base_name),
            fqn=normalize_target_name(f"{base_name}:{target_name}"),
            ctx=global_ctx.new_child(),
            fn=fn,
        )


class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


from rich import tree
from rich.console import Console, Group
from rich.spinner import Spinner
from rich.status import Status
from rich.columns import Columns
from rich.live import Live
from rich.panel import Panel
from rich.align import Align
from rich.pretty import Pretty
from rich.panel import Panel

import time


def draw_target_state(t: TargetCtl):
    name = f"[i grey70]{t.base_name}[/]:[b]{t.name}"

    build_op = t.building_operation

    _build_time = round(build_op.elapsed, 1)
    if _build_time >= 0.1:
        if _build_time == int(_build_time):
            build_time = f"[i]({int(_build_time)}s)[/]"
        else:
            build_time = f"[i]({_build_time:.1f}s)[/]"
    else:
        build_time = "[i](⚡s)"
    match build_op.state:
        case "init":
            return f"⏳ [sky_blue3 i]{name}"
        case "in-progress":
            return Columns([f"🚀 {name}", Status(""), build_time])
        case "succeed":
            return f"✅ [green]{name} {build_time}"
        case "failed":
            return f"💢 [red]{name} {build_time}"
    return f"? {name}"


def draw_operations(t_node: tree.Tree, operations: list[Operation]):
    for _op in operations:
        match _op:
            # case ConfOperation(kw=kw):
            #     t_node.add(Panel(Pretty(kw)))
            case LogOperation(log=log):
                t_node.add(log)
            case BuildOperation(target=target) as build_op:
                draw_operations(
                    t_node.add(draw_target(t_node, target)), build_op.nested
                )
            case DepOperation(target=target) as dep_op:
                if callable(target):
                    target = f"fn: {target.__name__}"
                draw_operations(
                    t_node.add(f"Requested dependency: {target}"), dep_op.nested
                )
            case RenderStrOperation(
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
                    draw_operations(
                        t_node.add(
                            Group(
                                Panel(template, title="Template", title_align="left"),
                                Panel(rendered, title="Rendered", title_align="left"),
                            )
                        ),
                        render_str_op.nested,
                    )
            case RenderOperation(src=src, dst=dst) as render_op:
                draw_operations(t_node.add(f"Render {src} ⤏ {dst}"), render_op.nested)
            case EnsureDirsOperation(folders=folders) as ensure_dirs_op:
                if len(folders) > 1:
                    draw_operations(
                        t_node.add(f"🗂️ Ensure {len(folders)} folders exist"),
                        ensure_dirs_op.nested,
                    )
                else:
                    draw_operations(t_node, ensure_dirs_op.nested)
            case ShOperation(cmd=cmd, logs=logs) as sh_op:
                _node = t_node.add(f"💲 {cmd}")
                draw_operations(_node, sh_op.nested)
                _node.add(draw_log(logs))


def draw_target(parent: tree.Tree, t: TargetCtl):
    target_node = parent.add(draw_target_state(t))
    if not t.building_operation.is_finished:
        draw_operations(target_node, t.building_operation.nested)


def draw_log(log: list[str], max_output=5):
    len_log = len(log)
    log_lines = (
        f"... truncated {len_log- max_output} line(s) ...\n"
        if len_log > max_output
        else ""
    ) + ("".join(log[-max_output:]))
    return Panel(log_lines.strip(), title="Logs", title_align="left")


def draw_info(l: Live, main_targets: list[TargetCtl]):

    targets_tree = tree.Tree("🚀 [b green]Building configurations...", highlight=True)

    for t in main_targets:
        draw_target(targets_tree, t)

    l.update(targets_tree)


def main():
    targets: list[str] = sys.argv[1:]

    registry = Registry()
    root_path = Path(os.getenv("CONFCTL_CONFIGS_ROOT", str(Path.cwd())))

    paths = root_path.rglob(".confbuild.py")

    global_ctx = Ctx()

    for path in paths:
        registry.add(
            gen_targets(
                path, global_ctx=global_ctx, root_path=root_path, registry=registry
            )
        )

    # Build a plant to run targets
    build_plan: list[TargetCtl] = []
    # - root main target is always executed (also it defines global context)
    if "//:main" in registry:
        root_target = registry.resolve("//:main")
        root_target.ctx = global_ctx
        build_plan.append(root_target)

    # - run all requested targets consequently
    for target in targets:
        t_name, extra_ctx = parse_target(target)
        t = registry.resolve(t_name)
        t.conf(**extra_ctx)
        build_plan.append(t)

    try:
        console = Console()
        with Live(console=console) as l:
            timer = RepeatTimer(1, draw_info, (l, build_plan))
            timer.start()

            # Run targets
            for target in build_plan:
                target.build()

            draw_info(l, build_plan)
            timer.cancel()
    except KeyboardInterrupt:
        timer.cancel()
        exit(1)


if __name__ == "__main__":
    main()
