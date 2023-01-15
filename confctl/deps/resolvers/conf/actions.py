import types
import typing as t

from functools import cache
from pathlib import Path

from confctl.deps.action import action, Action, is_action
from confctl.deps.ctx import Ctx
from .conf_spec import ConfDep as Dep


@action("use/conf", prep_track_data=lambda a, d: {"configs": list(d["kw"])})
def conf(act: Action, **kw):
    """
    Updates dependency configuration.

    Can be called multiple times. The last call overwrites configs with the same name.
    """
    from confctl.utils.template import LazyTemplate

    render_str_fn = act.resolve_action("render/str")
    execution_ctx = act.execution_ctx

    def _nest_ctx(val):
        if isinstance(val, t.Mapping):
            return Ctx({k: _nest_ctx(v) for k, v in val.items()})
        if isinstance(val, str):
            return LazyTemplate(val, render_str_fn)
        return val

    for k, v in kw.items():
        execution_ctx[k] = _nest_ctx(v)


@cache
def _load_python_module(path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("tmp", path)
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    raise ImportError(f"{path} cannot be loaded or found.")


def _load_module_level_config(module: types.ModuleType):
    return {
        k: v
        for k, v in vars(module).items()
        if not k.startswith("_") and not callable(v)
    }


@action(
    "build/dep",
    prep_track_data=lambda a, d: {
        "target_fqn": a.caller.spec.fqn,
        "target_name": a.caller.spec.target,
        "ui_options": a.caller.ui_options,
    },
)
def build(act: Action):
    assert isinstance(act.caller, Dep), "Can be called only for `Dep` instance"
    dep = act.caller
    spec = dep.spec

    build_module = _load_python_module(spec.conf_path)

    fn_names = [spec.target] if spec.target else [spec.conf_path.parent.name, "main"]

    build_fn = next(
        (_fn for fn_name in fn_names if (_fn := getattr(build_module, fn_name, None))),
        None,
    )

    dep.conf(
        current_config_dir=spec.conf_path.parent,
        **_load_module_level_config(build_module),
        **dep.spec.extra_ctx,
    )

    if not build_fn:
        raise RuntimeError(f"Cannot find build function for {spec} in {spec.conf_path}")

    act.progress(actual_target=build_fn.__name__)
    return build_fn(dep)


default_actions = [fn for fn in globals().values() if is_action(fn)]
