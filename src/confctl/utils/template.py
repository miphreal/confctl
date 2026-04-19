from dataclasses import dataclass
from typing import Callable

from jinja2.sandbox import SandboxedEnvironment


@dataclass
class LazyTemplate:
    template: str
    render: Callable[[str], str]

    def __str__(self) -> str:
        return self.render(self.template)


# SandboxedEnvironment blocks attribute access to dunder-prefixed names and
# other unsafe operations, mitigating SSTI-style gadgets (e.g. reaching
# `os` via `{{ "".__class__.__mro__[1].__subclasses__() }}`) if an untrusted
# value ever lands inside a template.
_env = SandboxedEnvironment()


def Template(source: str):
    return _env.from_string(source)
