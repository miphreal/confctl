from __future__ import annotations

import json
import typing as t

from confctl.deps.resolvers.simple import simple_resolver

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action


class BrewInfo:
    cache: dict[str, list[str]] = {}

    @classmethod
    def check_insstalled(
        cls, package: str, version: str | None, runtime: Action
    ) -> bool:
        run_sh = runtime.resolve_action("run/sh")

        installed_package = None
        installed_versions: list[str] = []

        if package in cls.cache:
            installed_package = package
            installed_versions = cls.cache[package]
        else:
            ret = run_sh("brew list --versions 2>/dev/null", log_progress=False)
            for line in ret.output.splitlines():
                line = line.strip()
                if not line:
                    continue
                pkg, *versions = line.split()
                cls.cache[pkg] = versions
                if pkg == package:
                    installed_package = pkg
                    installed_versions = versions

        if installed_package and installed_versions:
            if version is None:
                return True
            return any(v.startswith(version) for v in installed_versions)

        # Fallback to brew info approach
        ret = run_sh(f"brew info --json=v2 {package} 2>/dev/null", log_progress=False)
        if ret:
            # already installed, retrieving info
            brew_info = json.loads(ret.output)
            match brew_info:
                case {"formulae": [{"installed": [{"version": _ver}, *_]}, *_]}:
                    package_version = _ver
                case {"casks": [{"installed": _ver}, *_]}:
                    package_version = _ver
                case _:
                    package_version = None
            return bool(package_version and package_version.startswith(version or ""))
        return False


def brew(act: Action):
    dep = act.caller
    spec = dep.spec

    if "@" in spec.spec:
        package, version = spec.spec.split("@")
    else:
        package = spec.spec
        version = None

    if BrewInfo.check_insstalled(package, version, runtime=act):
        act.progress(status="unchanged")
        return "unchanged"

    # no info about the package, need to install it
    if run_sh(f"brew install {spec.spec}"):
        act.progress(status="installed")
        return "installed"

    act.progress(status="failed")
    return "failed"


setup = simple_resolver("brew")(brew)

