from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from collections import ChainMap
from typing import Callable, Literal, Mapping
from urllib.parse import parse_qsl

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

    def __getattr__(self, name):
        return getattr(self.ctx, name)

    def __repr__(self):
        return f"Target({self.fqn})"

    def build(self):
        if self.building_stage != "initialized":
            return
        self.building_stage = "building"
        self.fn(self)
        self.building_stage = "built"

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

    def sh(self, *commands: str):
        import subprocess

        outputs = []
        for cmd in commands:
            cmd = self.render_str(cmd)
            try:
                output = subprocess.check_output(cmd, shell=True)
                outputs.append(output)
            except subprocess.SubprocessError:
                outputs.append(None)

        return outputs

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

    # Run targets
    for target in build_plan:
        target.build()


if __name__ == "__main__":
    main()
