from __future__ import annotations

import typing as t

from confctl.deps.actions import action
from confctl.deps.ctx import Ctx
from confctl.deps.dep import Dep
from confctl.deps.spec import parse_spec

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry


def simple_resolver(name: str):
    def _wrapper(fn):
        run = action(f"run/{name}")(fn)
        run.__name__ = 'run'

        class _Resolver:
            def can_resolve(self, raw_spec: str, ctx: Ctx):
                if raw_spec.startswith(f"{name}::"):
                    return True
                return False

            def resolve(self, raw_spec: str, ctx: Ctx):
                spec = parse_spec(
                    raw_spec=raw_spec, default_resolver_name="<unknown-resolver>"
                )
                if spec.resolver_name != name:
                    raise RuntimeError(f"Spec {raw_spec} is not supported by this resolver.")

                dep = Dep(spec=spec, ctx=ctx.new_child(), actions=[run])

                return dep.run()


        def _setup(registry: Registry):
            registry.register_resolver(_Resolver())

        return _setup
    return _wrapper