from dataclasses import dataclass


@dataclass
class Spec:
    raw_spec: str

    resolver_name: str
    spec: str

    def __str__(self) -> str:
        return self.fqn

    @property
    def fqn(self):
        return f"{self.resolver_name}::{self.spec}"

    def __hash__(self) -> int:
        return hash(self.fqn)


def parse_spec(raw_spec: str, default_resolver_name: str):
    """General spec parser

    Spec examples:

        resolver::resolver-specific-spec

        conf::tools/kitty:main
        conf::tools/kitty
        tools/kitty

        pipx::confctl@1.0.0
        pyenv::python@3.10.4
        asdf::python@3.10.4
        asdf::python@3.10.4
        conf::tools/i3:i3?no-restart

    """

    spec = raw_spec.strip()

    # Extract resolver name
    parts = spec.split("::", 1)
    resolver_name = default_resolver_name
    if len(parts) == 2:
        resolver_name, spec = parts
        resolver_name = resolver_name.strip()
        spec = spec.strip()

    resolver_name = resolver_name or default_resolver_name

    return Spec(raw_spec=raw_spec, resolver_name=resolver_name, spec=spec)
