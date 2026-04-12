from __future__ import annotations

import typing as t

from confctl.deps.resolvers.simple import simple_resolver

from .bootstrap import ensure_tool

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action


def mise(act: Action):
    """Installs a tool version via mise.

    Usage: mise::python@3.12.0
           mise::nodejs@22
           mise::ruby  (installs latest)
    """
    if not ensure_tool("mise", act):
        act.progress(status="failed")
        return "failed"

    dep = act.caller
    spec = dep.spec

    if "@" in spec.spec:
        tool, version = spec.spec.split("@", 1)
    else:
        tool = spec.spec
        version = "latest"

    sh = act.resolve_action("run/sh")

    # Check if version is already installed
    result = sh(f"mise ls --installed {tool}", log_progress=False)
    if result:
        for line in result.output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == tool:
                installed_version = parts[1]
                if version != "latest" and installed_version == version:
                    act.progress(status="unchanged")
                    return "unchanged"

    act.log(f"Installing {tool}@{version}")
    if sh(f"mise install {tool}@{version}"):
        act.progress(status="installed")
        return "installed"

    act.progress(status="failed")
    return "failed"


setup = simple_resolver("mise")(mise)
