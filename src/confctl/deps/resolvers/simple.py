from __future__ import annotations

import re
import typing as t

from confctl.deps.actions import action
from confctl.deps.ctx import Ctx
from confctl.deps.dep import Dep
from confctl.deps.spec import parse_spec

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry


# Contrib resolvers (brew/pipx/uvx/asdf/mise) interpolate spec.spec directly
# into `shell=True` commands. Allow only characters that are safe as a single
# shell token — no separators, substitution, redirects, globs, or quotes.
SAFE_SPEC_RE = re.compile(r"^[A-Za-z0-9._@/+\-]+$")


class SimpleResolver:
    def __init__(self, name: str, fn: t.Callable):
        self.name = name
        self.run_action = action(f"run/{name}")(fn)
        self.run_action.__name__ = "run"

    def can_resolve(self, raw_spec: str, ctx: Ctx):
        return raw_spec.startswith(f"{self.name}::")

    def resolve(self, raw_spec: str, ctx: Ctx):
        spec = parse_spec(
            raw_spec=raw_spec, default_resolver_name="<unknown-resolver>"
        )
        if spec.resolver_name != self.name:
            raise RuntimeError(f"Spec {raw_spec} is not supported by this resolver.")

        if not SAFE_SPEC_RE.match(spec.spec):
            raise RuntimeError(
                f"{self.name}::{spec.spec!r} contains characters that are unsafe "
                "to pass to a shell. Allowed: letters, digits, and . _ @ / + -"
            )

        dep = Dep(spec=spec, ctx=ctx.new_child(), actions=[self.run_action])

        return dep.run()


def simple_resolver(name: str):
    def _wrapper(fn):
        resolver = SimpleResolver(name, fn)

        def _setup(registry: Registry):
            registry.register_resolver(resolver)

        return _setup

    return _wrapper
