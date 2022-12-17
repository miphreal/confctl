from pathlib import Path

from confctl.deps.action import action, Action


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
