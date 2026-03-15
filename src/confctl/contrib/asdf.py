from __future__ import annotations

import typing as t

from confctl.deps.resolvers.simple import simple_resolver

from .bootstrap import ensure_tool

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action


def asdf(act: Action):
    """Installs a tool version via asdf.

    Usage: asdf::python@3.10.4
           asdf::nodejs@18.0.0
           asdf::ruby  (installs latest)
    """
    if not ensure_tool("asdf", act):
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

    # Ensure the plugin is added
    result = sh("asdf plugin list", log_progress=False)
    installed_plugins = result.output.splitlines() if result else []
    if tool not in installed_plugins:
        act.log(f"Adding asdf plugin: {tool}")
        sh(f"asdf plugin add {tool}")

    # Check if version is already installed
    result = sh(f"asdf list {tool}", log_progress=False)
    installed_versions = (
        [v.strip().lstrip("*").strip() for v in result.output.splitlines()]
        if result
        else []
    )
    if version != "latest" and version in installed_versions:
        act.progress(status="unchanged")
        return "unchanged"

    act.log(f"Installing {tool}@{version}")
    if sh(f"asdf install {tool} {version}"):
        act.progress(status="installed")
        return "installed"

    act.progress(status="failed")
    return "failed"


setup = simple_resolver("asdf")(asdf)
