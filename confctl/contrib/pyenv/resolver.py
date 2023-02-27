from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from confctl.deps.ctx import Ctx
from confctl.deps.dep import Dep
from .actions import install, state
from .spec import parse_pyenv_spec, PyEnvSpec

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry


@dataclass
class PyEnvDep(Dep):
    spec: PyEnvSpec
    env_state: dict = field(default_factory=dict)

    def __call__(self, *state):
        for s in state:
            if isinstance(s, dict):
                self.state(**s)
            if isinstance(s, (tuple, list)):
                self.state(*s)
        return self

    def __hash__(self) -> int:
        return hash(self.spec)


class PyEnvResolver:
    name = "pyenv"

    _resolved: dict[str, PyEnvDep]

    def __init__(self) -> None:
        self._resolved = {}

    def can_resolve(self, raw_spec: str, ctx: Ctx):
        if raw_spec.startswith(f"{self.name}::"):
            return True
        return False

    def resolve(self, raw_spec: str, ctx: Ctx) -> PyEnvDep:
        spec = parse_pyenv_spec(raw_spec)

        if spec.fqn in self._resolved:
            return self._resolved[spec.fqn]

        self._resolved[spec.fqn] = d = PyEnvDep(
            spec=spec, ctx=ctx.new_child(), actions=[install, state]
        )

        if spec.target == "python":
            d.install()

        return d


def setup(registry: Registry):
    registry.register_resolver(PyEnvResolver())
