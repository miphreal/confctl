from __future__ import annotations

import typing as t

from confctl.deps.ctx import Ctx
from .actions import default_actions
from .conf_spec import CONF_RESOLVER_NAME, parse_conf_spec, ConfDep

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry


class ConfResolver:
    root_conf_dep = "conf:::main"

    _resolved: dict[str, ConfDep]

    def __init__(self) -> None:
        self._resolved = {}

    @classmethod
    def setup(cls, registry: Registry):
        configs_root = registry.global_ctx.configs_root
        conf_resolver = cls()

        registry.register_resolver(conf_resolver)

        root_conf = configs_root / ".confbuild.py"
        if root_conf.exists():
            conf_resolver.resolve(cls.root_conf_dep, registry.global_ctx)

    def can_resolve(self, raw_spec: str, ctx: Ctx):
        if raw_spec.startswith(f"{CONF_RESOLVER_NAME}::"):
            return True

        try:
            spec = parse_conf_spec(raw_spec, ctx)
            if spec.resolver_name == CONF_RESOLVER_NAME and spec.conf_path.exists():
                return True
        except AssertionError:
            return False

        return False

    def resolve(self, raw_spec: str, ctx: Ctx) -> ConfDep:
        spec = parse_conf_spec(raw_spec, ctx)

        if spec.fqn in self._resolved:
            return self._resolved[spec.fqn]

        if spec.fqn == self.root_conf_dep:
            d = ConfDep(
                spec=spec,
                ctx=ctx.global_ctx,
                actions=default_actions.copy(),
                # Do not fail if root resolver func is not not defined
                failsafe=True,
                ui_options={"visibility": "hidden"},
            )
        else:
            d = ConfDep(spec=spec, ctx=ctx.new_child(), actions=default_actions.copy())

        self._resolved[spec.fqn] = d

        d.build()

        return d
