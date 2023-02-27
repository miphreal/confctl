from __future__ import annotations

import typing as t

from dataclasses import dataclass, field

from confctl.utils.py_module import load_python_obj
from .ctx import Ctx


class Resolver(t.Protocol):
    def can_resolve(self, raw_spec: str, ctx: Ctx) -> bool:
        ...

    def resolve(self, raw_spec: str, ctx: Ctx) -> t.Any:
        ...


@dataclass
class Registry:
    global_ctx: Ctx
    resolvers: list[Resolver] = field(default_factory=list)

    def resolve(self, raw_spec: str, ctx: Ctx | None = None) -> t.Any:
        ctx = ctx or self.global_ctx
        for resolver in self.resolvers:
            if resolver.can_resolve(raw_spec=raw_spec, ctx=ctx):
                return resolver.resolve(raw_spec=raw_spec, ctx=ctx)

        raise RuntimeError(f"Cannot find a handler for '{raw_spec}' spec.")

    def register_resolver(self, resolver: Resolver):
        self.resolvers.append(resolver)

    def setup_resolvers(self, resolvers_refs: list[t.Any]):
        for resolver_setup_ref in resolvers_refs:
            if isinstance(resolver_setup_ref, str):
                resolver_setup_ref = load_python_obj(resolver_setup_ref)

            if callable(resolver_setup_ref):
                resolver_setup_ref(self)
            else:
                raise RuntimeError(f"{resolver_setup_ref!r} is invalid setup fn.")
