from __future__ import annotations

import typing as t

from dataclasses import dataclass, field
from difflib import get_close_matches

from confctl.utils.py_module import load_python_obj
from .ctx import Ctx


class Resolver(t.Protocol):
    def can_resolve(self, raw_spec: str, ctx: Ctx) -> bool:
        ...

    def resolve(self, raw_spec: str, ctx: Ctx) -> t.Any:
        ...


class SpecNotFoundError(RuntimeError):
    """Raised when no resolver can handle a given spec.

    Carries the `user_facing` marker so the event pipeline knows to show a
    clean message instead of a full traceback.
    """

    user_facing = True

    def __init__(self, raw_spec: str, suggestions: t.Sequence[str] = ()):
        self.raw_spec = raw_spec
        self.suggestions = list(suggestions)
        super().__init__(self._format())

    def _format(self) -> str:
        msg = f"Cannot find a handler for '{self.raw_spec}' spec."
        if self.suggestions:
            options = "\n".join(f"  {s}" for s in self.suggestions)
            msg = f"{msg}\nDid you mean:\n{options}"
        return msg


@dataclass
class Registry:
    global_ctx: Ctx
    resolvers: list[Resolver] = field(default_factory=list)

    def resolve(self, raw_spec: str, ctx: Ctx | None = None) -> t.Any:
        ctx = ctx or self.global_ctx
        for resolver in self.resolvers:
            if resolver.can_resolve(raw_spec=raw_spec, ctx=ctx):
                return resolver.resolve(raw_spec=raw_spec, ctx=ctx)

        raise SpecNotFoundError(raw_spec, self._suggest(raw_spec))

    def _suggest(self, raw_spec: str, n: int = 3) -> list[str]:
        known: list[str] = []
        for resolver in self.resolvers:
            list_specs = getattr(resolver, "list_specs", None)
            if callable(list_specs):
                try:
                    known.extend(list_specs())
                except Exception:
                    continue
        # Dedupe while preserving order
        seen: set[str] = set()
        unique = [s for s in known if not (s in seen or seen.add(s))]
        return get_close_matches(raw_spec, unique, n=n, cutoff=0.4)

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
