from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl

from confctl.deps.ctx import Ctx
from confctl.deps.spec import parse_spec, Spec


CONF_RESOLVER_NAME = "conf"


@dataclass
class ConfSpec(Spec):
    conf_path: Path
    target: str
    extra_ctx: dict

    def __hash__(self) -> int:
        return hash(self.fqn)


def parse_conf_spec(raw_spec: str, ctx: Ctx) -> ConfSpec:
    """
    Parses conf specs, e.g.
        tools/shell:zsh
        ./shell:zsh
        conf::tools/terminal:kitty
        conf::tools/i3?no-restart
    """
    common_spec = parse_spec(
        raw_spec=raw_spec, default_resolver_name=CONF_RESOLVER_NAME
    )
    assert (
        common_spec.resolver_name == CONF_RESOLVER_NAME
    ), f"{common_spec} is unsupported by `ConfResolver`"

    spec = common_spec.spec

    # Extract dependency params
    parts = spec.rsplit("?", 1)
    extra_ctx = {}
    if len(parts) == 2:
        spec, params = parts
        spec = spec.strip()
        params = params.strip()
        extra_ctx = dict(
            parse_qsl(params, keep_blank_values=True), __raw_extra_ctx__=params
        )

    # Extract conf path
    parts = spec.rsplit(":", 1)
    if len(parts) == 2:
        conf_path_part, target_name = parts
    else:
        conf_path_part = spec.strip()
        target_name = ""

    conf_path_part = conf_path_part.strip()

    conf_dir = ctx.configs_root

    if conf_path_part:
        if conf_path_part.startswith(("./", "../")):
            conf_dir: Path = ctx.get("current_config_dir") or conf_dir
        conf_dir = (conf_dir / conf_path_part).resolve()

    if spec.startswith(("./", "../")):
        spec = str(conf_dir.relative_to(ctx.configs_root))
        if target_name:
            spec = f"{spec}:{target_name}"

    return ConfSpec(
        resolver_name=CONF_RESOLVER_NAME,
        raw_spec=raw_spec,
        spec=spec,
        conf_path=conf_dir / ".confbuild.py",
        target=target_name,
        extra_ctx=extra_ctx,
    )
