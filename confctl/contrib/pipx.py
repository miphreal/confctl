from __future__ import annotations

import json
import typing as t

from confctl.deps.resolvers.simple import simple_resolver

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action


def pipx(act: Action):
    dep = act.caller
    spec = dep.spec

    run_sh = act.resolve_action("run/sh")

    if '@' in spec.spec:
        package, version = spec.spec.split('@')
    else:
        package = spec.spec
        version = None

    package_spec = f"{package}=={version}" if version else package

    ret = run_sh(f"pipx list --json 2>/dev/null")
    pipx_info = json.loads(ret.output)
    assert pipx_info["pipx_spec_version"] == "0.1"

    package_info = pipx_info["venvs"].get(package)

    if package_info:
        installed_version = package_info["metadata"]["main_package"]["package_version"]
        if not installed_version.startswith(version or ''):
            if run_sh(f"pipx install --force {package_spec}"):
                act.progress(status='installed')
                return 'installed'

        act.progress(status='unchanged')
        return 'unchanged'

    # no info about the package, need to install it
    elif run_sh(f"pipx install {package_spec}"):
        act.progress(status='installed')
        return 'installed'

    act.progress(status='failed')
    return 'failed'


setup = simple_resolver('pipx')(pipx)
