from __future__ import annotations

import typing as t

from confctl.deps.resolvers.simple import simple_resolver

from .bootstrap import ensure_tool

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action


def uvx(act: Action):
    """Installs a Python tool via uv tool install (uvx).

    Usage: uvx::ruff
           uvx::ruff@0.4.0
    """
    if not ensure_tool("uv", act):
        act.progress(status="failed")
        return "failed"

    dep = act.caller
    spec = dep.spec

    run_sh = act.resolve_action("run/sh")

    if "@" in spec.spec:
        package, version = spec.spec.split("@", 1)
    else:
        package = spec.spec
        version = None

    package_spec = f"{package}=={version}" if version else package

    # Check installed tools
    ret = run_sh("uv tool list 2>/dev/null", log_progress=False)
    if ret:
        for line in ret.output.splitlines():
            if line.startswith(f"{package} v"):
                installed_version = line.split(" v", 1)[1].strip()
                if version and installed_version != version:
                    if run_sh(f"uv tool install --force {package_spec}"):
                        act.progress(status="installed")
                        return "installed"

                act.progress(status="unchanged")
                return "unchanged"

    # Not installed yet (use --force in case executable exists from another tool manager)
    if run_sh(f"uv tool install --force {package_spec}"):
        act.progress(status="installed")
        return "installed"

    act.progress(status="failed")
    return "failed"


setup = simple_resolver("uvx")(uvx)
