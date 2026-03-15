from __future__ import annotations

import json
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
    ret = run_sh("uv tool list --format json 2>/dev/null", log_progress=False)
    if ret:
        tools_info = json.loads(ret.output)
        for tool in tools_info:
            if tool.get("name") == package:
                installed_version = tool.get("version", "")
                if not installed_version.startswith(version or ""):
                    if run_sh(f"uv tool install --force {package_spec}"):
                        act.progress(status="installed")
                        return "installed"

                act.progress(status="unchanged")
                return "unchanged"

    # Not installed yet
    if run_sh(f"uv tool install {package_spec}"):
        act.progress(status="installed")
        return "installed"

    act.progress(status="failed")
    return "failed"


setup = simple_resolver("uvx")(uvx)
