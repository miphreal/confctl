from __future__ import annotations

import typing as t
from pathlib import Path

from .simple import simple_resolver

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action


@simple_resolver("path")
def path(act: Action):
    p = Path(act.caller.spec.spec).expanduser()
    # Makes sure the parent folder exist
    p.parent.mkdir(exist_ok=True, parents=True)
    return p


@simple_resolver("dir")
def dir(act: Action):
    p = Path(act.caller.spec.spec).expanduser()
    # Makes sure the given folder exist
    p.mkdir(exist_ok=True, parents=True)
    return p