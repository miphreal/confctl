from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from collections import ChainMap
from time import sleep
from typing import Callable, Literal, Mapping
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


class TargetCtl:
    TemplateCls = Template

    registry: Registry
    build_file: Path
    fqn: str
    base_name: str
    name: str
    fn: Callable
    ctx: Ctx
    deps: list[TargetCtl]

    building_start_time: float | None = None
    building_end_time: float | None = None
    building_log: list[str]

    building_stage: Literal[
        "initialized", "building", "built", "failed"
    ] = "initialized"

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
        self.deps = []
        self.building_stage = "initialized"
        self.building_log = []

    def __getattr__(self, name):
        return getattr(self.ctx, name)

    def __repr__(self):
        return f"Target({self.fqn})"

    def build(self):
        if self.building_stage != "initialized":
            return
        self.building_start_time = time.time()
        self.building_stage = "building"
        self.fn(self)
        self.building_end_time = time.time()
        self.building_stage = "built"

    @property
    def build_time(self):
        if self.building_start_time:
            return (self.building_end_time or time.time()) - self.building_start_time
        return 0

    def dep(self, target: str | Callable):
        t = self.registry.resolve(self.render_str(target))
        self.deps.append(t)
        t.build()
        return t

    def conf(self, **kw):
        def _nest_ctx(val):
            if isinstance(val, Mapping):
                return Ctx({k: _nest_ctx(v) for k, v in val.items()})
            if isinstance(val, str):
                return LazyTemplate(val, self.render_str)
            return val

        for k, v in kw.items():
            self.ctx[k] = _nest_ctx(v)

    def ensure_dirs(self, *folders: str | Path):
        for f in folders:
            folder = Path(self.render_str(f)).expanduser()
            folder.mkdir(parents=True, exist_ok=True)

    def sh(self, command: str, failsafe=False):
        import subprocess

        cmd = self.render_str(command)

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True
        )

        while process.poll() is None:
            log = process.stdout.readline().decode("utf8")
            self.building_log.append(log)
        self.building_log.extend(l.decode("utf8") for l in process.stdout.readlines())
        process.stdout.close()

        return self.building_log

    def render_str(self, template, **extra_context):
        if isinstance(template, str):
            ctx = self.ctx
            if extra_context:
                ctx = ctx.new_child(extra_context)
            return self.TemplateCls(template).render(ctx)
        return template

    def _try_relative_path(self, path: str | Path) -> Path:
        return self.build_file.parent.joinpath(Path(path).expanduser())

    def render(self, src: str | Path, dst: str | Path, **extra_context):
        src = self._try_relative_path(self.render_str(src))
        dst = Path(self.render_str(dst)).expanduser()
        self.ensure_dirs(dst.parent)

        with src.open("rt") as f_in, dst.open("wt") as f_out:
            f_out.write(self.render_str(f_in.read(), **extra_context))


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


from rich import tree, panel
from rich.console import Console, Group
from rich.spinner import Spinner
from rich.status import Status
from rich.columns import Columns
from rich.live import Live
from rich.panel import Panel
from rich.align import Align
import time


def draw_target_state(t: TargetCtl):
    name = f"[i grey70]{t.base_name}[/]:[b]{t.name}"

    _build_time = round(t.build_time, 1)
    if _build_time >= 0.1:
        if _build_time == int(_build_time):
            build_time = f"[i]({int(_build_time)}s)[/]"
        else:
            build_time = f"[i]({_build_time:.1f}s)[/]"
    else:
        build_time = "[i](⚡s)"
    match t.building_stage:
        case "initialized":
            return f"⏳ [sky_blue3 i]{name}"
        case "building":
            return Columns([f"🚀 {name}", Status(""), build_time])
        case "built":
            return f"✅ [green]{name} {build_time}"
        case "failed":
            return f"💢 [red]{name} {build_time}"
    return f"? {name}"


def draw_log(log: list[str], max_output=5):
    len_log = len(log)
    log_lines = (
        f"... truncated {len_log- max_output} line(s) ...\n"
        if len_log > max_output
        else ""
    ) + ("".join(log[-max_output:]))
    return Panel(log_lines.strip())


def draw_target_node(parent_node: tree.Tree, t: TargetCtl):
    t_node = parent_node.add(draw_target_state(t))
    if t.building_stage == "building" and t.building_log:
        t_node.add(draw_log(t.building_log))

    return t_node


def draw_info(l: Live, main_targets: list[TargetCtl], reg: Registry):

    targets_tree = tree.Tree("🚀 [b green]Building configurations...", highlight=True)

    for t in main_targets:
        draw_target_node(targets_tree, t)

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
        console = Console(force_interactive=True, force_terminal=True)
        with Live(console=console) as l:
            timer = RepeatTimer(1, draw_info, (l, build_plan, registry))
            timer.start()

            # Run targets
            for target in build_plan:
                target.build()

            sleep(10)

            timer.cancel()
    except KeyboardInterrupt:
        timer.cancel()
        exit(1)


if __name__ == "__main__":
    main()
