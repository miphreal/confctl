from __future__ import annotations

import typing as t
from dataclasses import dataclass

from confctl.deps import actions
from confctl.deps.ctx import Ctx
from confctl.deps.dep import Dep
from confctl.utils.py_module import load_python_module, load_module_level_config
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

    def force_stop(self, reason: str, data: dict | None = None):
        self.ctx.ops.force_stop(reason, data)


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
    global_ctx = registry.global_ctx
    configs_root = global_ctx.configs_root
    root_conf = configs_root / ".confbuild.py"
    if root_conf.exists():
        root_conf = load_python_module(root_conf)
        # set global default actions
        global_ctx.update(
            {
                actions.get_action_name(a): actions.prep_action_as_fn(a, ctx=global_ctx)
                for a in vars(actions).values()
                if actions.is_action(a)
            }
        )
        # set configuration from root `root_conf`
        conf(
            **load_module_level_config(root_conf),
            __ctx=global_ctx,
        )
        # load extra resolvers
        confctl_resolvers = getattr(global_ctx, "CONFCTL_RESOLVERS", [])
        registry.setup_resolvers(confctl_resolvers)


