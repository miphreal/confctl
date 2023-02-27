import typing as t

from dataclasses import dataclass
from functools import cached_property
from functools import wraps
from inspect import signature
from pathlib import Path

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


#
# Common actions
#
@action(
    "render/str",
    prep_track_data=lambda a, d: dict(
        template=d["template"], rest_keys=list(d["extra_context"])
    ),
)
def render_str(act: Action, template: str, **extra_context):
    from confctl.utils.template import Template

    if isinstance(template, str):
        dep_fn = act.resolve_action("use/dep")
        template_ctx = act.execution_ctx

        if extra_context:
            template_ctx = template_ctx.new_child(extra_context)

        compiled_template = Template(template)
        compiled_template.globals["dep"] = dep_fn
        # compiled_template.filters["arg"] = shlex.quote

        rendered = compiled_template.render(template_ctx)
        act.progress(rendered=rendered)
        return rendered
    return template


@action(
    "render/file",
    prep_track_data=lambda a, d: dict(
        src=d["src"], dst=d["dst"], rest_keys=list(d["extra_context"])
    ),
)
def render(act: Action, src: str | Path, dst: str | Path, **extra_context):
    current_config_dir: Path | None = act.execution_ctx.get("current_config_dir")
    render_str_fn = act.resolve_action("render/str")

    src = Path(render_str_fn(src)).expanduser()
    dst = Path(render_str_fn(dst)).expanduser()

    if isinstance(current_config_dir, Path):
        relative_src = current_config_dir / src
        if relative_src.exists():
            src = current_config_dir / src

    act.progress(src=src, dst=dst)

    dst.parent.mkdir(parents=True, exist_ok=True)

    with src.open("rt") as f_in, dst.open("wt") as f_out:
        rendered_content = render_str_fn(f_in.read(), **extra_context)
        act.progress(rendered_content=rendered_content)
        f_out.write(rendered_content)


@action("use/dep")
def dep(act: Action, spec: str, /):
    """Requests a dependency."""
    render_str_fn = act.resolve_action("render/str")
    spec = render_str_fn(spec)
    act.progress(spec=spec)
    return act.global_ctx.registry.resolve(spec, act.execution_ctx)


@dataclass
class CommandExecutionResult:
    exitcode: int
    logs: list[str]

    def __bool__(self) -> bool:
        return self.exitcode == 0

    @cached_property
    def output(self) -> str:
        return "".join(self.logs)

    def __contains__(self, log: str) -> bool:
        return log in self.output


@action("run/sh")
def sh(act: Action, cmd: str, env: dict | None = None):
    import subprocess

    render_str_fn = act.resolve_action("render/str")

    logs: list[str] = []

    cmd = render_str_fn(cmd)
    act.progress(cmd=cmd)

    with subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        text=True,
        env=env,
    ) as process:
        act.progress(pid=process.pid)

        while process.poll() is None:
            if process.stdout is not None:
                for log in process.stdout.readlines():
                    act.log(log)
                    logs.append(log)

        if process.stdout is not None:
            for log in process.stdout.readlines():
                act.log(log)
                logs.append(log)

        act.progress(exitcode=process.returncode)

    return CommandExecutionResult(exitcode=process.returncode, logs=logs)


@action("run/sudo")
def sudo(act: Action, cmd: str):
    """
    Runs command with super user perms.
    """
    import os
    import pty
    import shlex

    render_str_fn = act.resolve_action("render/str")

    cmd = render_str_fn(cmd)
    act.progress(cmd=cmd)

    cmd_parts = [
        "/usr/bin/sudo",
        "-p",
        "SUDO_USER_PASSWORD_PROMPT",
        *shlex.split(cmd),
    ]

    def write(fd, data):
        while data:
            n = os.write(fd, data)
            data = data[n:]

    logs = []

    sent_passwd = False

    def read(fd):
        nonlocal sent_passwd

        data = os.read(fd, 1024)
        logs.append(data.decode("utf8"))

        if not sent_passwd and "SUDO_USER_PASSWORD_PROMPT" in "".join(logs):
            passwd = os.getenv("CONFCTL_SUDO_PASS", "none")
            write(
                fd,
                "{}\n".format(passwd).encode("utf8"),
            )
            sent_passwd = True

        act.log(data.decode("utf8"))
        return data

    exitcode = pty.spawn(cmd_parts, read)
    act.progress(exitcode=exitcode)

    return CommandExecutionResult(exitcode=exitcode, logs=logs)
