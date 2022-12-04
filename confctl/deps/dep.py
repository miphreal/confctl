from __future__ import annotations

import types
import typing as t

from collections import ChainMap
from dataclasses import dataclass, field
from functools import cache, partial
from pathlib import Path
from urllib.parse import parse_qsl

from confctl.wire.events import OpsTracking
from confctl.template import LazyTemplate

ROOT_CONF_DEP = "conf:::main"


class Ctx(ChainMap):
    # Globally available context values
    global_ctx: "Ctx"
    registry: "Registry"
    ops: "OpsTracking"

    def __getattr__(self, name):
        try:
            val = self[name]
        except KeyError:
            raise AttributeError(name)

        if isinstance(val, LazyTemplate):
            val = str(val)
            self[name] = val
        return val


@dataclass(frozen=True)
class Spec:
    raw_spec: str
    resolver_name: str
    spec: str
    params: dict[str, t.Any]

    def __str__(self) -> str:
        return self.fqn

    @property
    def fqn(self):
        return f"{self.resolver_name}::{self.spec}"

    def __hash__(self) -> int:
        return hash(self.raw_spec)


def parse_spec(raw_spec: str, default_resolver_name: str):
    """Parses dependency spec.

    Spec examples:

        resolver::resolver-specific-spec

        conf::tools/kitty:main
        conf::tools/kitty
        tools/kitty

        pipx::confctl@1.0.0
        pyenv::python@3.10.4
        asdf::python@3.10.4 (installed)
        conf::tools/i3:i3?no-restart

    """

    spec = raw_spec.strip()

    # Extract dependency params
    parts = spec.rsplit("?", 1)
    extra_ctx = {}
    if len(parts) == 2:
        spec, params = parts
        spec = spec.strip()
        params = params.strip()
        extra_ctx = dict(
            parse_qsl(params, keep_blank_values=True), __raw_extra_ctx__=params
        )

    # Extract dependency resolver
    parts = spec.split("::", 1)
    resolver_name = ""
    if len(parts) == 2:
        resolver_name, spec = parts
        spec = spec.strip()
        resolver_name = resolver_name.strip()

    resolver_name = resolver_name or default_resolver_name

    return Spec(
        raw_spec=raw_spec, resolver_name=resolver_name, spec=spec, params=extra_ctx
    )


@dataclass
class Dep:
    # user-defined dependency spec
    spec: Spec
    # context with globally available and dependency-level values
    ctx: Ctx
    # resolver for the spec
    resolver: Resolver
    failsafe: bool = False
    # actions that can be triggered on dependency
    actions: dict[str, t.Callable] = field(default_factory=dict)

    def __getattr__(self, name):
        """Proxies attribute access to target's configuration."""
        if name in self.actions:
            return self.resolve_action(name)
        return getattr(self.ctx, name)

    def __hash__(self) -> int:
        return hash(self.spec)

    def __call__(self, *deps: str, **conf):
        self.conf(**conf)

        for dep in deps:
            self.dep(dep)

    @cache
    def resolve(self):
        return self.resolver.resolve(self)

    @cache
    def resolve_action(self, action_name: str):
        fn = next(
            (
                f
                for f_name, f in self.actions.items()
                if action_name == f_name
                or getattr(f, "__confclt_action_name__", "") == action_name
            ),
            None,
        )

        if fn is None:
            fn = self.ctx[action_name]  # TODO: improve how actions are stored in `ctx`

        if callable(fn):
            return lambda *args, **kwargs: fn(
                *args, **kwargs, __ctx=self.ctx, __caller=self
            )

        raise RuntimeError(
            f"Cannot resolve {action_name} action for {self.spec} dependency."
        )


class Resolver(t.Protocol):
    name: str

    def setup(self, registry: Registry):
        ...

    def create_dep(self, spec: Spec, ctx: Ctx) -> Dep:
        ...

    def resolve(self, dep: Dep, /):
        ...


class ConfResolver:
    name = "conf"

    _loaded_modules: dict[Path, types.ModuleType]
    _root_conf_dir: Path

    def __init__(self, root_conf_dir: Path, global_ctx: Ctx) -> None:
        self._loaded_modules = {}
        self._root_conf_dir = root_conf_dir

    def _load_python_module(self, path: Path):
        import importlib.util

        if path in self._loaded_modules:
            return self._loaded_modules[path]

        spec = importlib.util.spec_from_file_location("tmp", path)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._loaded_modules[path] = module
            return module

        raise ImportError(f"{path} cannot be loaded or found.")

    def _load_module_level_config(self, module: types.ModuleType):
        return {
            k: v
            for k, v in vars(module).items()
            if not k.startswith("_") and not callable(v)
        }

    def setup(self, registry: Registry):
        # Setup `ConfResolver` as default resolver
        registry.default_resolver_name = self.name

        root_conf = self._root_conf_dir / ".confbuild.py"
        if root_conf.exists():
            registry.resolve(ROOT_CONF_DEP)

    def create_dep(self, spec: Spec, ctx: Ctx):
        from confctl.deps.actions import default_actions

        if spec.fqn == ROOT_CONF_DEP:
            return Dep(
                spec=spec,
                ctx=ctx.global_ctx,
                resolver=self,
                actions={**default_actions},
                # Do not fail if root resolver func is not not defined
                failsafe=True,
            )
        return Dep(spec=spec, ctx=ctx, resolver=self, actions={**default_actions})

    @cache
    def resolve(self, dep: Dep):
        spec = dep.spec.spec

        path, *target = spec.rsplit(":", 1)
        conf_dir = (self._root_conf_dir / path) if path else self._root_conf_dir

        build_module = self._load_python_module(conf_dir / ".confbuild.py")

        fn_names = target if target else [path.rsplit("/", 1)[-1], "main"]

        # Try to find the actual
        dep_fn = next(
            (
                _fn
                for fn_name in fn_names
                if (_fn := getattr(build_module, fn_name, None))
            ),
            None,
        )

        dep.conf(
            current_config_dir=conf_dir,
            **self._load_module_level_config(build_module),
            **dep.spec.params,
        )

        if not dep_fn:
            raise RuntimeError(
                f"Cannot find resolver function for {spec} in {conf_dir}/.confbuild.py"
            )
        return dep_fn(dep)


class UnknownResolver:
    name = "unknown"

    def setup(self, registry: Registry):
        """Nothing to setup"""

    def create_dep(self, spec: Spec, *args, **kwargs):
        raise RuntimeError(f"Cannot generate {spec} dep object")

    def resolve(self, dep: Dep):
        raise RuntimeError(f"Cannot resolve {dep.spec}")


def get_resolver(spec: Spec, resolvers: list[Resolver]):
    for resolver in resolvers:
        if resolver.name == spec.resolver_name:
            return resolver
    return UnknownResolver()


@dataclass
class Registry:
    global_ctx: Ctx
    configs_root: Path
    resolvers: list[Resolver] = field(default_factory=list)
    default_resolver_name: str = UnknownResolver.name

    deps_map: dict[str, Dep] = field(default_factory=dict)

    def __contains__(self, name: str):
        return name in self.deps_map

    def dep(self, raw_spec: str) -> Dep:
        spec = parse_spec(raw_spec, self.default_resolver_name)
        if spec.fqn in self.deps_map:
            return self.deps_map[spec.fqn]

        resolver = get_resolver(spec, self.resolvers)

        ctx = self.global_ctx.new_child()
        d = resolver.create_dep(spec=spec, ctx=ctx)

        self.deps_map[spec.fqn] = d
        return d

    def resolve(self, raw_spec: str):
        d = self.dep(raw_spec=raw_spec)
        try:
            return d.resolve()
        except Exception as e:
            if d.failsafe:
                self.global_ctx.ops.debug(f"Muted {raw_spec} error: {e}")
            else:
                raise

    def setup_resolvers(self):
        self.resolvers.append(
            ConfResolver(root_conf_dir=self.configs_root, global_ctx=self.global_ctx)
        )

        for resolver in self.resolvers:
            resolver.setup(registry=self)
