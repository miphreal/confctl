"""Bootstrapping helpers for contrib resolvers.

Ensures required CLI tools are available, installing them
via brew or official install scripts if missing.
"""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from confctl.deps.actions import Action

# Official install commands (fallback when brew is not available)
INSTALL_SCRIPTS: dict[str, str] = {
    "brew": '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
    "asdf": "git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.16.7",
    "pyenv": "curl -fsSL https://pyenv.run | bash",
    "pipx": "python3 -m pip install --user pipx",
    "uv": "curl -LsSf https://astral.sh/uv/install.sh | sh",
}

# Tools that can be installed via brew
BREW_INSTALLABLE = {"asdf", "pyenv", "pipx", "uv"}


def ensure_tool(tool: str, act: Action) -> bool:
    """Ensure a CLI tool is available, installing it if missing.

    Returns True if the tool is available (already present or just installed).
    """
    run_sh = act.resolve_action("run/sh")

    # Already available?
    if run_sh(f"command -v {tool}", log_progress=False):
        return True

    act.log(f"{tool} not found, attempting to install...")

    # Try brew first (unless we're bootstrapping brew itself)
    if tool != "brew" and tool in BREW_INSTALLABLE:
        if run_sh("command -v brew", log_progress=False):
            if run_sh(f"brew install {tool}"):
                return True

    # Fall back to official install script
    script = INSTALL_SCRIPTS.get(tool)
    if script:
        if run_sh(script):
            return True

    act.log(f"Failed to install {tool}")
    return False
