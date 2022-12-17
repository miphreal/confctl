import typing as t

from dataclasses import dataclass
from functools import wraps
from inspect import signature

from confctl.wire.events import OpWrapper
from .ctx import Ctx
from .dep import Dep


FN_ACTION_NAME_ATTR = "__confclt_action_name__"


@dataclass
class Action:
    global_ctx: Ctx
    caller: Dep | None
    tracking: t.Callable  # a function that creates context manager
    tracking_op: OpWrapper | None = None

    @property
    def execution_ctx(self):
        return self.caller.ctx if self.caller else self.global_ctx

    def resolve_action(self, action: str):
        if self.caller:
            return self.caller.get_action(action)
        return self.global_ctx[action]

    def log(self, log: str):
        if self.tracking_op:
            self.tracking_op.log(log)

    def debug(self, log: str):
        if self.tracking_op:
            self.tracking_op.debug(log)

    def progress(self, **data):
        if self.tracking_op:
            self.tracking_op.progress(**data)

    def __call__(self, **kwargs):
        return self.tracking(**kwargs)


def action(
    action_name: str,
    *,
    auto_ops_wrapper: bool = True,
    prep_track_data=lambda a, d: d,
    failsafe: bool = False,
):
    def _decorator(fn: t.Callable):
        @wraps(fn)
        def _fn(*args, **kwargs):
            ctx: Ctx = kwargs.pop("__ctx")
            caller: Dep | None = kwargs.pop("__caller", None)
            action_arg = Action(
                global_ctx=ctx.global_ctx,
                caller=caller,
                tracking=ctx.ops.get_track_fn(action=action_name),
            )

            if auto_ops_wrapper:
                action_src = caller.spec.fqn if caller else "(global)"

                # Track what arguments we pass to the action function
                fn_sig = signature(fn)
                _track_kwargs = fn_sig.bind(action_arg, *args, **kwargs)
                _track_kwargs.apply_defaults()
                # the first argument (`action_arg`) should not be tracked
                _first_param_name = list(fn_sig.parameters.keys())[0]
                _track_data = _track_kwargs.arguments.copy()
                _track_data.pop(_first_param_name)
                # modify tracked data if necessary (by calling `prep_track_data`)
                _track_data = prep_track_data(action_arg, _track_data)

                ret = None
                with action_arg(action_src=action_src, **_track_data) as op:
                    action_arg.tracking_op = op
                    ret = fn(action_arg, *args, **kwargs)

                if op.error and isinstance(caller, Dep):
                    if not caller.failsafe and not failsafe:
                        raise op.error
                    ctx.ops.debug(f"Muted {caller.spec} error: {op.error}")

                return ret
            else:
                return fn(action_arg, *args, **kwargs)

        setattr(_fn, FN_ACTION_NAME_ATTR, action_name)

        return _fn

    return _decorator


def is_action(fn):
    return bool(fn and callable(fn) and hasattr(fn, FN_ACTION_NAME_ATTR))


def get_action_name(fn) -> str | None:
    if is_action(fn):
        return getattr(fn, FN_ACTION_NAME_ATTR)
    return None
