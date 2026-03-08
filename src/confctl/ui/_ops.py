from __future__ import annotations

from dataclasses import dataclass

from rich import tree

from confctl.ui._base import OpBase, register_op_ui
from confctl.ui._rendering import render_path
from confctl.ui._widgets import UIBuildTargetHeader, UIRunBrewHeader, UIRenderStr


@register_op_ui
@dataclass
class OpBuildDep(OpBase):
    op_name: str = "build/dep"
    show_content: bool = True

    bubble_ops_deps: bool = True

    HIDDEN_OPS = (
        "use/conf",
        "render/str",
    )

    @property
    def fqn(self):
        return self.data.target_fqn or ""

    @property
    def name(self):
        return self.data.target_name

    @property
    def ui_options(self):
        return self.data.get("ui_options") or {}

    @property
    def target_name(self):
        return self.data.get("actual_target", self.name)

    @property
    def resolver(self):
        parts = self.fqn.split("::", 1)
        if len(parts) == 2:
            return parts[0]
        return ""

    @property
    def base_name(self):
        fqn = self.fqn.split("::", 1)[-1]
        return fqn.replace(f":{self.target_name or '...'}", "")

    def _build_header(self):
        return UIBuildTargetHeader(self)

    def build_ui(self, parent_node: tree.Tree):
        super().build_ui(parent_node)

        if (
            self.render_node
            and self.ui_options.get("visibility", "visible") == "hidden"
            and self.render_node in parent_node.children
        ):
            parent_node.children.remove(self.render_node)


@register_op_ui
@dataclass
class OpRender(OpBase):
    op_name: str = "render/file"
    show_content: bool = False

    def _build_header(self):
        src = render_path(self.data.src)
        dst = render_path(self.data.dst)
        return f"📝 [grey50]{src} [grey70]⤏[/] {dst}[/]"


@register_op_ui
@dataclass
class OpRenderStr(OpBase):
    op_name: str = "render/str"
    show_content: bool = False

    def _build_header(self):
        return UIRenderStr(self)


@register_op_ui
@dataclass
class OpRunSh(OpBase):
    op_name: str = "run/sh"

    def _build_header(self):
        elapsed_time = round(self.elapsed, 1)
        if elapsed_time >= 1:
            run_time = f"[grey70 i]({elapsed_time:.1f}s)[/]"
        else:
            run_time = ""

        command = self.data.cmd
        exit_code = self.data.get("exitcode")
        finish_state = "⏳"
        if isinstance(exit_code, int):
            if exit_code == 0:
                finish_state = "🆗"
            else:
                finish_state = "💢"
                command = f"[indian_red]{command} [{exit_code}][/]"
        else:
            pid = self.data.pid
            if pid is not None:
                command = f"{command} [grey70 i][pid {pid}][/]"

        if self.data.get("sudo"):
            command = f"[b]\\[sudo][/] {command}"
        return f"📜{finish_state} [grey50]{command}[/] {run_time}"

    def on_start(self):
        self.show_logs = True

    def on_finish(self):
        exit_code = self.data.get("exitcode")
        self.show_content = bool(exit_code is not None and exit_code != 0)
        self.show_logs = self.show_content


@register_op_ui
@dataclass
class OpUseDep(OpBase):
    op_name: str = "use/dep"

    @property
    def name(self):
        return self.data.get("spec", "unset")

    def _build_header(self):
        return f"📎 {self.name}"


@register_op_ui
@dataclass
class OpRunBrew(OpBase):
    op_name: str = "run/brew"

    def _build_header(self):
        return UIRunBrewHeader(self)


@register_op_ui
@dataclass
class OpBuildConfigs(OpBase):
    op_name: str = "build/specs"
    HIDDEN_OPS = ("use/conf",)

    def build_ui(self):
        if self.render_node is None:
            self.render_node = tree.Tree(
                "🚀 [b green]Building configurations...",
                highlight=False,
                guide_style="grey70",
            )
        self._build_content()

    def __rich_console__(self, *args):
        self.show_logs = bool(self.error)
        self.build_ui()
        yield self.render_node
