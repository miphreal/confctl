from __future__ import annotations

import typing as t

from rich.columns import Columns
from rich.console import Group, RenderableType, ConsoleRenderable
from rich.panel import Panel
from rich.status import Status

if t.TYPE_CHECKING:
    from confctl.ui._base import OpBase


class StateHeader(ConsoleRenderable):
    """Base widget for rendering op state with emoji + styled name + elapsed time.

    Subclass and override ``get_name()`` to provide the display name.
    Override individual ``render_*`` methods for custom per-state rendering.
    """

    def __init__(self, op: OpBase):
        self.op = op

    def get_name(self) -> str:
        raise NotImplementedError

    def _format_build_time(self) -> tuple[str, float]:
        raw = round(self.op.elapsed, 1)
        if raw >= 0.1:
            text = f"[i grey70 not bold]({raw:.1f}s)[/]"
        else:
            text = ""
        return text, raw

    def render_init(self, name: str) -> RenderableType:
        return f"⏳ [sky_blue3 i]{name}"

    def render_in_progress(self, name: str, build_time: str) -> RenderableType:
        return Columns([f"🚀 {name}", Status(""), build_time])

    def render_succeeded(self, name: str, build_time: str, raw_time: float) -> RenderableType:
        if build_time and raw_time == int(raw_time):
            build_time = f"[i]({int(raw_time)}s)[/]"
        return f"✅ [green]{name} {build_time}"

    def render_failed(self, name: str, build_time: str) -> RenderableType:
        return f"💢 [red]{name} {build_time}"

    def render_state(self) -> RenderableType:
        name = self.get_name()
        build_time, raw_time = self._format_build_time()
        match self.op.state:
            case "init":
                return self.render_init(name)
            case "in-progress":
                return self.render_in_progress(name, build_time)
            case "succeeded":
                return self.render_succeeded(name, build_time, raw_time)
            case "failed":
                return self.render_failed(name, build_time)
        return f"? {name}"

    def __rich_console__(self, *args):
        yield self.render_state()


class UIBuildTargetHeader(StateHeader):
    def get_name(self):
        op = self.op
        name = f"[i grey50]{op.base_name}[/]:[b]{op.target_name}[/]"
        resolver = op.resolver
        if resolver:
            name = f"[i grey70]{resolver}::[/]{name}"
        return name


class UIRunBrewHeader(StateHeader):
    def get_name(self):
        spec = self.op.data['action_src'].partition('::')[-1]
        return f"[b]{spec}[/]"

    def render_succeeded(self, name, build_time, raw_time):
        if build_time and raw_time == int(raw_time):
            build_time = f"[i]({int(raw_time)}s)[/]"
        status = self.op.data['status']
        match status:
            case 'unchanged':
                return f"🔶 [yellow]{name} [i grey70]{status}[/] {build_time}"
            case 'installed':
                return f"✅ [green]{name} [i grey70]{status}[/] {build_time}"
            case 'failed':
                return f"💢 [red]{name} {build_time}"
        return f"[green]{name} {build_time}"


class UIOpLogs(ConsoleRenderable):
    op: OpBase

    def __init__(self, op: OpBase):
        self.op = op

    def render_logs(self, logs: list[str], max_output=5):
        logs_text = "".join(logs)
        nl_count = logs_text.count("\n")
        logs_text.find("\n")

        logs = logs_text.rsplit('\n', maxsplit=max_output+1)

        log_lines = (
            f"... truncated {nl_count - max_output} line(s) ...\n"
            if nl_count > max_output
            else ""
        ) + ("\n".join(logs[-max_output:]))
        return Panel(log_lines.strip(), title="Logs", title_align="left")

    def __rich_console__(self, *args):
        if self.op.logs:
            yield self.render_logs(self.op.logs, max_output=self.op.show_logs_lines)


class UIRenderStr(ConsoleRenderable):
    op: OpBase

    def __init__(self, op: OpBase):
        self.op = op

    def render(self, template: str, rendered: str | None):
        renderables: list[RenderableType] = []

        if len(template) > 100:
            template = f"{template[:100]}...{len(template)-100} chars more..."
            renderables.append(
                Panel(template, title="Template str", title_align="left")
            )
        else:
            renderables.append(f"Template string: {template}")

        if rendered is not None and template != rendered:
            if len(rendered) > 100:
                rendered = f"{rendered[:100]}...{len(rendered)-100} chars more..."
                renderables.append(
                    Panel(rendered or "", title="Rendered as", title_align="left")
                )
            else:
                renderables.append(f"    [grey70 i]Rendered as:[/] {rendered}")

        return Group(*renderables)

    def __rich_console__(self, *args):
        rendered = self.op.data.get("rendered")
        if rendered is not None and self.op.data.template != rendered:
            yield self.render(self.op.data.template, rendered)
