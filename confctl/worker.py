from __future__ import annotations

import os
import pty
import shlex
import typing as t

from collections import ChainMap
from dataclasses import dataclass
from functools import cached_property, cache
from multiprocessing import Process
from multiprocessing.connection import Connection
from pathlib import Path
from urllib.parse import parse_qsl

from confctl.wire.channel import Channel
from confctl.wire.events import OpsTracking
from confctl.template import Template, LazyTemplate


ROOT_TARGET = "conf::.main"


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


class Ctx(ChainMap):
    def __getattr__(self, name):
        try:
            val = self[name]
        except KeyError:
            raise AttributeError(name)

        if isinstance(val, LazyTemplate):
            val = str(val)
            self[name] = val
        return val


def load_python_module(path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("tmp", path)
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    raise ImportError(f"{path} cannot be loaded or found.")


class DepState:
    ...


class Resolver:
    ...


@dataclass
class Dep:
    resolver: Resolver
    spec: str
    state: DepState

    @cache
    def build(self):
        ...


class Target:
    registry: Registry
    ops: OpsTracking

    build_file: Path
    current_config_dir: Path
    fqn: str
    base_name: str
    name: str
    fn: t.Callable
    ctx: Ctx

    ui_options: dict

    def __init__(
        self,
        registry: Registry,
        ops: OpsTracking,
        build_file: Path,
        fqn: str,
        base_name: str,
        name: str,
        fn: t.Callable,
        ctx: Ctx,
        ui_options: dict | None = None,
    ):
        self.registry = registry
        self.ops = ops
        self.build_file = build_file
        self.current_config_dir = build_file.parent
        self.fqn = fqn
        self.base_name = base_name
        self.name = name
        self.fn = fn
        self.ctx = ctx
        self.ui_options = ui_options or {}

        self.ctx["fqn"] = self.fqn
        self.ctx["target_name"] = self.name
        self.ctx["current_config_dir"] = self.current_config_dir

    def __getattr__(self, name):
        """Proxies attribute access to target's configuration."""
        return getattr(self.ctx, name)

    def __repr__(self):
        return f"Target({self.fqn})"

    def __call__(self, *deps: str, **conf):
        self.conf(**conf)

        for dep in deps:
            self.dep(dep)

    @cache
    def build(self):
        with self.ops.track_build(self):
            self.fn(self)

    def dep(self, target: str):
        """Requests a dependency."""

        # Resolve relative target
        if target.startswith("./"):
            target = f"{self.base_name}/{target.removeprefix('./')}"

        with self.ops.track_dep(target):
            t = self.registry.resolve(self.render_str(target))
            t.build()
            return t

    def conf(self, **kw):
        """
        Declares target configuration.

        Can be called multiple times. The last call overwrites configs with the same name.
        """

        def _nest_ctx(val):
            if isinstance(val, t.Mapping):
                return Ctx({k: _nest_ctx(v) for k, v in val.items()})
            if isinstance(val, str):
                return LazyTemplate(val, self.render_str)
            return val

        with self.ops.track_conf(fqn=self.fqn, kw=kw):
            for k, v in kw.items():
                self.ctx[k] = _nest_ctx(v)

    def ensure_dirs(self, *folders: str | Path):
        """Ensures `folders` exist."""
        with self.ops.track_ensure_dirs(folders) as _op:
            for f in folders:
                folder = Path(self.render_str(f)).expanduser()
                _op.progress(folder=folder)
                folder.mkdir(parents=True, exist_ok=True)

    def sudo(self, command: str):
        """
        Runs command with super user perms.
        """
        with self.ops.track_sudo(cmd=command) as _op:
            cmd = self.render_str(command)
            _op.progress(cmd=cmd)

            cmd = [
                "/usr/bin/sudo",
                "-p",
                "SUDO_USER_PASSWORD_PROMPT",
                *shlex.split(command),
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

                _op.log(data.decode("utf8"))
                return data

            exitcode = pty.spawn(cmd, read)
            _op.progress(exitcode=exitcode)

            return CommandExecutionResult(exitcode=exitcode, logs=logs)

    def sh(self, command: str, env: dict | None = None):
        import subprocess

        logs: list[str] = []

        with self.ops.track_sh(cmd=command) as _op:
            cmd = self.render_str(command)
            _op.progress(cmd=cmd)

            with subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,
                text=True,
                env=env,
            ) as process:
                _op.progress(pid=process.pid)

                while process.poll() is None:
                    if process.stdout is not None:
                        for log in process.stdout.readlines():
                            _op.log(log)
                            logs.append(log)

                if process.stdout is not None:
                    for log in process.stdout.readlines():
                        _op.log(log)
                        logs.append(log)

                _op.progress(exitcode=process.returncode)

        return CommandExecutionResult(exitcode=process.returncode, logs=logs)

    def render_str(self, template, **extra_context):
        if isinstance(template, str):
            ctx = self.ctx
            if extra_context:
                ctx = ctx.new_child(extra_context)
            with self.ops.track_render_str(template=template, ctx=dict(ctx)) as _op:
                compiled_template = Template(template)
                compiled_template.globals["dep"] = self.dep
                # compiled_template.filters["arg"] = shlex.quote

                rendered = compiled_template.render(ctx)
                _op.progress(rendered=rendered)
                return rendered
        return template

    def _try_relative_path(self, path: str | Path) -> Path:
        return self.current_config_dir.joinpath(Path(path).expanduser())

    def render(self, src: str | Path, dst: str | Path, **extra_context):
        with self.ops.track_render(src=src, dst=dst) as _op:
            src = self._try_relative_path(self.render_str(src))
            dst = Path(self.render_str(dst)).expanduser()
            _op.progress(rendered_src=src, rendered_dst=dst)

            self.ensure_dirs(dst.parent)

            with src.open("rt") as f_in, dst.open("wt") as f_out:
                f_out.write(self.render_str(f_in.read(), **extra_context))


def normalize_target_name(name: str):
    name = name.removeprefix("./")
    if not name.startswith("//"):
        name = f"//{name}"
    return name


class Registry:
    targets_map: dict[str, Target]

    def __init__(self) -> None:
        self.targets_map = {}

    def __contains__(self, name: str):
        return name in self.targets_map

    def add(self, *targets: Target):
        for t in targets:
            self.targets_map[t.fqn] = t

            # if target name matches base folder name, we consider this target as the
            # main folder target.
            if t.base_name.endswith(f"/{t.name}"):
                # do not overwrite if already set
                self.targets_map.setdefault(t.base_name, t)

            # if target name is "main", it's considered as the main folder target.
            if t.name == "main":
                self.targets_map[t.base_name] = t

    def resolve(self, target: str):
        try:
            target = normalize_target_name(target)
            return self.targets_map[target]
        except KeyError:
            raise RuntimeError(f"Target '{target}' cannot be found.")


def parse_target(t: str):
    t = t.strip()
    parts = t.split("?", 1)
    extra_ctx = {}
    if len(parts) == 2:
        t, params = parts
        extra_ctx = dict(
            parse_qsl(params, keep_blank_values=True), __raw_extra_ctx__=params
        )

    return normalize_target_name(t), extra_ctx


def gen_targets(
    build_file: Path,
    global_ctx: Ctx,
    root_path: Path,
    registry: Registry,
    ops_tracking: OpsTracking,
):
    build_module = load_python_module(build_file)

    is_root_build_file = False

    base_name = str(build_file.parent.relative_to(root_path))
    if base_name == ".":
        # it's a root `.confbuild.py`
        base_name = ""
        is_root_build_file = True

    targets_fns = [
        fn
        for fn in vars(build_module).values()
        if callable(fn) and not fn.__name__.startswith("_")
    ]

    root_target: Target | None = None

    for fn in targets_fns:
        target_name = fn.__name__
        base_name = normalize_target_name(base_name)
        fqn = normalize_target_name(f"{base_name}:{target_name}")
        ui_options = {}
        ops_tracking.debug(f"Found target: {fqn}")
        ctx = global_ctx.new_child()

        if fqn == "//:main":
            ctx = global_ctx
            ui_options["visibility"] = "hidden"

        t = Target(
            registry=registry,
            ops=ops_tracking,
            build_file=build_file,
            name=target_name,
            base_name=base_name,
            fqn=fqn,
            ctx=ctx,
            fn=fn,
            ui_options=ui_options,
        )

        if fqn == "//:main":
            root_target = t

        yield t

    if is_root_build_file:
        if not root_target:
            root_target = Target(
                registry=registry,
                ops=ops_tracking,
                build_file=build_file,
                name="main",
                base_name="//",
                fqn="//:main",
                ctx=global_ctx,
                fn=lambda _: None,
                ui_options={"visibility": "hidden"},
            )

        root_target.conf(
            **{k: v for k, v in vars(build_module).items() if not k.startswith("_")}
        )


def build_plan(
    targets: list[str], registry: Registry, ops: OpsTracking
) -> list[Target]:
    # Build a plan to run targets
    planned_targets: list[Target] = []

    # - root main target is always executed
    if "//:main" in registry:
        root_target = registry.resolve("//:main")
        planned_targets.append(root_target)
        ops.debug(f"Added //:main to plan")

    # - collect all requested targets
    for target in targets:
        ops.debug(f"Loading {target} target...")
        t_name, extra_ctx = parse_target(target)
        t = registry.resolve(t_name)
        ops.debug(f"Resolved {t.fqn} {extra_ctx}")
        if extra_ctx:
            t.conf(**extra_ctx)
        ops.debug(f"Added {t.fqn} to plan")
        planned_targets.append(t)

    return planned_targets


def build_targets(targets: list[str], configs_root: Path, events_channel: Connection):
    ops_tracking = OpsTracking(events_channel)

    with ops_tracking.op("build/configs") as op:

        paths = list(configs_root.rglob(".confbuild.py"))

        op.debug(f"Found {len(paths)} configs...")

        global_ctx = Ctx()
        registry = Registry()

        for path in paths:
            op.debug(f"Looking up for targets in: {path}")
            registry.add(
                *gen_targets(
                    path,
                    global_ctx=global_ctx,
                    root_path=configs_root,
                    registry=registry,
                    ops_tracking=ops_tracking,
                )
            )

        op.debug("Building plan...")
        plan = build_plan(targets, registry=registry, ops=ops_tracking)

        op.debug("Executing plan...")
        for target in plan:
            op.debug(f"Start building {target.fqn}")
            target.build()

        op.debug("Finished.")


def run_worker(targets: list[str], configs_root: Path, events_channel: Channel):
    proc = Process(
        target=build_targets,
        kwargs={
            "targets": targets,
            "configs_root": configs_root,
            "events_channel": events_channel,
        },
        daemon=True,
    )
    proc.start()

    def _stop():
        if proc.is_alive():
            proc.terminate()

    return _stop
