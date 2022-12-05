import types
import typing as t

from dataclasses import dataclass
from functools import cached_property, cache
from pathlib import Path

from confctl.deps.actions import action, Action
from confctl.deps.ctx import Ctx
from .conf_spec import ConfDep as Dep


@action("use/conf", prep_track_data=lambda a, d: {"configs": list(d["kw"])})
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


@action("use/dirs")
def ensure_dirs(act: Action, *dirs: str | Path):
    """Ensures `dirs` exist."""
    render_str_fn = act.resolve_action("render/str")
    for f in dirs:
        folder = Path(render_str_fn(f)).expanduser()
        act.progress(folder=folder)
        folder.mkdir(parents=True, exist_ok=True)


@action(
    "render/str",
    prep_track_data=lambda a, d: dict(
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
    prep_track_data=lambda a, d: dict(
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

    act.progress(src=src, dst=dst)

    ensure_dirs_fn(dst.parent)

    with src.open("rt") as f_in, dst.open("wt") as f_out:
        rendered_content = render_str_fn(f_in.read(), **extra_context)
        act.progress(rendered_content=rendered_content)
        f_out.write(rendered_content)


@action("use/dep")
def dep(act: Action, spec: str):
    """Requests a dependency."""

    # Resolve relative target
    if spec.startswith("./") and act.caller:
        spec = f"{act.caller.base_name}/{spec.removeprefix('./')}"

    render_str_fn = act.resolve_action("render/str")
    spec = render_str_fn(spec)

    act.progress(spec=spec)

    d = act.global_ctx.registry.resolve(spec, act.execution_ctx)
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
