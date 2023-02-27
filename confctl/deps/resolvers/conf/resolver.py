from __future__ import annotations

import typing as t
from dataclasses import dataclass

from confctl.deps.ctx import Ctx
from confctl.deps.dep import Dep
from .actions import conf, build
from .conf_spec import CONF_RESOLVER_NAME, parse_conf_spec, ConfSpec

if t.TYPE_CHECKING:
    from confctl.deps.registry import Registry


@dataclass
class ConfDep(Dep):
    spec: ConfSpec

    def __hash__(self) -> int:
        return hash(self.spec)

    def __call__(self, **configs):
        """
        Allows syntax sugar to set configuration.

        For instance,
            conf(
                font_name="Helvetica",
                font_size=12,
            )
        """
        self.conf(**configs)
        return self

    def __getitem__(self, key):
        """
        Allows a syntax sugar on a configuration to request one or more other
        dependencies.

        For instance,
            path1, path2 = conf[
                "dir:/tmp/a",
                "path:/tmp/b/c",
            ]
        """
        dep_action = self.get_action("dep")
        if isinstance(key, str):
            return dep_action(key)
        if isinstance(key, (tuple, str)):
            return list(map(dep_action, key))
        raise TypeError(f"`key` must be string or list of strings")


class ConfResolver:
    root_conf_dep = "conf:::main"

    _resolved: dict[str, ConfDep]

    def __init__(self) -> None:
        self._resolved = {}

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
                actions=[conf, build],
                # Do not fail if root resolver func is not defined
                failsafe=True,
                ui_options={"visibility": "hidden"},
            )
        else:
            d = ConfDep(spec=spec, ctx=ctx.new_child(), actions=[conf, build])

        self._resolved[spec.fqn] = d

        d.build()

        return d


def setup(registry: Registry):
    conf_resolver = ConfResolver()
    registry.register_resolver(conf_resolver)

    # Handle root configuration
    configs_root = registry.global_ctx.configs_root
    root_conf = configs_root / ".confbuild.py"
    if root_conf.exists():
        root_conf = conf_resolver.resolve(
            ConfResolver.root_conf_dep, registry.global_ctx
        )

        confctl_resolvers = getattr(root_conf, "CONFCTL_RESOLVERS", [])
        registry.setup_resolvers(confctl_resolvers)
