from __future__ import annotations

import typing as t
from dataclasses import dataclass
from pathlib import Path

from confctl.deps.action import action, Action, is_action
from confctl.deps.ctx import Ctx
from confctl.deps.dep import Dep
from confctl.deps.spec import parse_spec, Spec
from .actions import render_str, render, dep

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry


@dataclass
class PathSpec(Spec):
    path: Path

    def __hash__(self) -> int:
        return hash(self.raw_spec)


@dataclass
class PathDep(Dep):
    spec: PathSpec

    def __hash__(self) -> int:
        return hash(self.spec)

    def __str__(self):
        if self.path:
            return str(self.path)
        raise RuntimeError(f"Path is not set.")


def parse_path_spec(raw_spec: str):
    spec = parse_spec(raw_spec, "path")

    return PathSpec(
        raw_spec=raw_spec,
        resolver_name=spec.resolver_name,
        spec=spec.spec,
        path=Path(spec.spec).expanduser(),
    )


@action("mkpath")
def mkpath(act: Action):
    if act.caller:
        spec: PathSpec = act.caller.spec
        if spec.resolver_name == "path":
            spec.path.parent.mkdir(exist_ok=True, parents=True)
        elif spec.resolver_name == "dir":
            spec.path.mkdir(exist_ok=True, parents=True)


class PathResolver:
    @classmethod
    def setup(cls, registry: Registry):
        registry.register_resolver(cls())

    def can_resolve(self, raw_spec: str, ctx: Ctx):
        spec = parse_spec(raw_spec, "path")
        if spec.resolver_name in ("path", "dir"):
            return True
        return False

    def resolve(self, raw_spec: str, ctx: Ctx):
        spec = parse_path_spec(raw_spec)

        if spec.resolver_name in ("path", "dir"):
            d = PathDep(
                spec=spec,
                ctx=ctx.new_child(),
                actions=[mkpath, render, render_str, dep],
            )
            d.mkpath()
            return d.spec.path

        raise RuntimeError(f"Cannot resolve {raw_spec} as path or dir")