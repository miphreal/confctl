import typing as t

from dataclasses import dataclass
from functools import wraps, cached_property
from pathlib import Path
from inspect import signature

from confctl.wire.events import OpWrapper
from .dep import Dep, Ctx


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
            return self.caller.resolve_action(action)
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
        op = self.tracking_op = self.tracking(**kwargs)
        return op


def action(
    action_name: str,
    auto_ops_wrapper: bool = True,
    prep_track_data=lambda d: d,
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
                fn_sig = signature(fn)
                _track_kwargs = fn_sig.bind(action_arg, *args, **kwargs)
                _track_kwargs.apply_defaults()
                _first_param_name = list(fn_sig.parameters.keys())[0]
                _track_data = _track_kwargs.arguments.copy()
                _track_data.pop(_first_param_name)
                _track_data = prep_track_data(_track_data)
                with action_arg(action_src=action_src, **_track_data) as op:
                    action_arg.tracking_op = op
                    return fn(action_arg, *args, **kwargs)
            else:
                return fn(action_arg, *args, **kwargs)

        _fn.__confclt_action_name__ = action_name

        return _fn

    return _decorator


@action("use/conf", prep_track_data=lambda d: {"configs": list(d["kw"])})
def conf(act: Action, **kw):
    """
    Updates dependency configuration.

    Can be called multiple times. The last call overwrites configs with the same name.
    """
    from confctl.template import LazyTemplate

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


@action("use/dirs")
def ensure_dirs(act: Action, *folders: str | Path):
    """Ensures `folders` exist."""
    render_str_fn = act.resolve_action("render/str")
    for f in folders:
        folder = Path(render_str_fn(f)).expanduser()
        act.progress(folder=folder)
        folder.mkdir(parents=True, exist_ok=True)


@action(
    "render/str",
    prep_track_data=lambda d: dict(
        template=d["template"], rest_keys=list(d["extra_context"])
    ),
)
def render_str(act: Action, template: str, **extra_context):
    from confctl.template import Template

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
    prep_track_data=lambda d: dict(
        src=d["src"], dst=d["dst"], rest_keys=list(d["extra_context"])
    ),
)
def render(act: Action, src: str | Path, dst: str | Path, **extra_context):
    current_config_dir: Path | None = act.execution_ctx.get("current_config_dir")
    render_str_fn = act.resolve_action("render/str")
    ensure_dirs_fn = act.resolve_action("use/dirs")

    src = Path(render_str_fn(src)).expanduser()
    dst = Path(render_str_fn(dst)).expanduser()

    if current_config_dir:
        src = current_config_dir.joinpath(src)

    act.progress(rendered_src=src, rendered_dst=dst)

    ensure_dirs_fn(dst.parent)

    with src.open("rt") as f_in, dst.open("wt") as f_out:
        rendered_content = render_str_fn(f_in.read(), **extra_context)
        act.progress(rendered_content=rendered_content)
        f_out.write(rendered_content)


@action("use/dep")
def dep(act: Action, spec: str, resolve: bool = True):
    """Requests a dependency."""

    # Resolve relative target
    if spec.startswith("./") and act.caller:
        spec = f"{act.caller.base_name}/{spec.removeprefix('./')}"

    render_str_fn = act.resolve_action("render/str")
    spec = render_str_fn(spec)

    act.progress(spec=spec)

    d = act.global_ctx.registry.dep(spec)
    if resolve:
        return d.resolve()
    return d


@dataclass
class CommandExecutionResult:
    exitcode: int
    logs: list[str]

    def __bool__(self) -> bool:
        return self.exitcode == 0

    @cached_property
    def _logs_content(self) -> str:
        return "".join(self.logs)

    def __contains__(self, log: str) -> bool:
        return log in self._logs_content


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


default_actions = {fn_name: fn for fn_name, fn in globals().items() if callable(fn)}
