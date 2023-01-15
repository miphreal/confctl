from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from confctl.deps.action import action, Action, is_action


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

    render_str_fn = act.resolve_action("render/str")
    spec = render_str_fn(spec)

    act.progress(spec=spec)

    d = act.global_ctx.registry.resolve(spec, act.execution_ctx)
    return d


@action("use/dirs")
def ensure_dirs(act: Action, *dirs: str | Path):
    """Ensures `dirs` exist."""
    render_str_fn = act.resolve_action("render/str")
    for f in dirs:
        folder = Path(render_str_fn(f)).expanduser()
        act.progress(folder=folder)
        folder.mkdir(parents=True, exist_ok=True)


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


default_actions = [fn for fn in globals().values() if is_action(fn)]
