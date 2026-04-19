import re
from dataclasses import dataclass

from confctl.deps.spec import parse_spec, Spec

# Same safe-token allowlist used by SimpleResolver — pyenv commands also run
# via `shell=True`, so spec.spec must not contain shell metacharacters.
_SAFE_SPEC_RE = re.compile(r"^[A-Za-z0-9._@/+\-]+$")


@dataclass
class PyEnvSpec(Spec):
    target: str
    version: str
    venv: str | None

    def __hash__(self) -> int:
        return hash(self.fqn)


def parse_pyenv_spec(raw_spec: str) -> PyEnvSpec:
    """
    Parses pyenv specs, e.g.
        pyenv::python/3.10.4
        pyenv::python/3.10.4/env-name
    """
    common_spec = parse_spec(
        raw_spec=raw_spec, default_resolver_name="<unknown-resolver>"
    )
    assert common_spec.resolver_name == "pyenv", (
        f"{common_spec} is unsupported by `PyEnvResolver`"
    )

    spec = common_spec.spec

    if not _SAFE_SPEC_RE.match(spec):
        raise RuntimeError(
            f"pyenv::{spec!r} contains characters that are unsafe to pass to "
            "a shell. Allowed: letters, digits, and . _ @ / + -"
        )

    match spec.split("/"):
        case ["python", version]:
            target = "python"
            venv = None
        case ["python", version, venv]:
            target = "python"
        case _:
            raise RuntimeError(f"Unknown spec: {spec}")

    return PyEnvSpec(
        resolver_name="pyenv",
        raw_spec=raw_spec,
        spec=spec,
        target=target,
        version=version,
        venv=venv,
    )
