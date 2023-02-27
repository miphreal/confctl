import types
import typing as t

from confctl.deps.actions import action, Action
from confctl.deps.ctx import Ctx
from confctl.utils.py_module import load_python_module


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
    from .resolver import ConfDep

    assert isinstance(act.caller, ConfDep), "Can be called only for `Dep` instance"
    dep = act.caller
    spec = dep.spec

    build_module = load_python_module(spec.conf_path)

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
