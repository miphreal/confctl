from __future__ import annotations

import typing as t

from confctl.deps.ctx import Ctx
from .actions import default_actions
from .spec import parse_pyenv_spec, PyEnvDep

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry


class PyEnvResolver:
    name = "pyenv"

    _resolved: dict[str, PyEnvDep]

    def __init__(self) -> None:
        self._resolved = {}

    @classmethod
    def setup(cls, registry: Registry):
        registry.register_resolver(cls())

    def can_resolve(self, raw_spec: str, ctx: Ctx):
        if raw_spec.startswith(f"{self.name}::"):
            return True
        return False

    def resolve(self, raw_spec: str, ctx: Ctx) -> PyEnvDep:
        spec = parse_pyenv_spec(raw_spec)

        if spec.fqn in self._resolved:
            return self._resolved[spec.fqn]

        self._resolved[spec.fqn] = d = PyEnvDep(
            spec=spec, ctx=ctx.new_child(), actions=default_actions.copy()
        )

        if spec.target == 'python':
            d.install()

        return d
