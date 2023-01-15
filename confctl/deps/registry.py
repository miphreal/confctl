from __future__ import annotations

import typing as t

from dataclasses import dataclass, field

from .ctx import Ctx


class Resolver(t.Protocol):
    @classmethod
    def setup(cls, registry: Registry):
        ...

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

    def setup_resolvers(self, resolvers_classes: list[t.Type[Resolver]]):
        for cls in resolvers_classes:
            cls.setup(self)
