from __future__ import annotations

import json
import typing as t

from confctl.deps.resolvers.simple import simple_resolver

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action


def brew(act: Action):
    dep = act.caller
    spec = dep.spec

    run_sh = act.resolve_action("run/sh")

    if '@' in spec.spec:
        package, version = spec.spec.split('@')
    else:
        package = spec.spec
        version = None

    ret = run_sh(f"brew info --json=v2 {package} 2>/dev/null")
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
        if package_version and package_version.startswith(version or ""):
            act.progress(status='unchanged')
            return 'unchanged'
    
    # no info about the package, need to install it
    if run_sh(f"brew install {spec.spec}"):
        act.progress(status='installed')
        return 'installed'
        
    act.progress(status='failed')
    return 'failed'


setup = simple_resolver('brew')(brew)