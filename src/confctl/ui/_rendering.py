from __future__ import annotations

from pathlib import Path

from rich.console import ConsoleRenderable

CWD = str(Path.cwd().absolute())
HOME = str(Path.home().absolute())


class RenderFn(ConsoleRenderable):
    def __init__(self, render):
        self.render = render

    def __rich_console__(self, *args):
        yield self.render()


def render_path(path: str | Path, home_color="medium_purple4", cwd_color="steel_blue"):
    path_obj = Path(path)
    is_dir = path_obj.exists() and path_obj.is_dir()

    path = str(path).rstrip("/")

    if path.startswith(CWD):
        path = path.removeprefix(CWD).lstrip("/")
        path = f"[i {cwd_color}].[/]/{path}"

    elif path.startswith(HOME):
        path = path.removeprefix(HOME).lstrip("/")
        path = f"[i {home_color}]~[/]/{path}"

    if "/" in path:
        parent, name = path.rsplit("/", 1)
        path = f"[i]{parent}[/]/[b]{name}[/]"

    if is_dir:
        path = f"{path}[grey78 not bold]/[/]"

    return path
