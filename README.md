<p align="center">
    <a href="https://pypi.org/project/confctl/">
        <img src="https://badge.fury.io/py/confctl.svg" alt="Package version">
    </a>
</p>

# confctl

A build-system-like tool for managing system configurations declaratively. Write Python functions that describe *what* your system should look like, and confctl resolves dependencies, installs packages, renders templates, and runs commands to make it happen.

```sh
$ confctl tools/kitty
```

## Install

```sh
# Run directly (no install)
$ uvx confctl tools/kitty

# Or install permanently
$ uv tool install confctl
# or
$ pipx install confctl
```

## Quick start

Create a directory for your configurations and add a `.confbuild.py` file:

```
my-configs/
├── .confbuild.py
└── zsh/
    ├── .confbuild.py
    └── .zshrc.j2
```

The root `.confbuild.py` sets up global context and registers resolvers:

```python
# .confbuild.py (root)
import os

CONFCTL_RESOLVERS = ["confctl.contrib.homebrew"]

user = {
    "config": os.path.expanduser("~/.config"),
    "bin": os.path.expanduser("~/.local/bin"),
}
```

Module-level variables (like `user` above) become context available to all configs. `CONFCTL_RESOLVERS` registers additional resolvers (homebrew, pipx, pyenv, etc.).

A config for zsh might look like:

```python
# zsh/.confbuild.py

def main(conf):
    conf["brew::zsh-syntax-highlighting", "brew::zsh-autosuggestions"]
    conf(editor="nvim")
    conf.render(".zshrc.j2", "~/.zshrc")
```

And the template:

```jinja2
# ~/.zshrc (managed by confctl)
export EDITOR={{ editor }}

source $(brew --prefix)/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh
source $(brew --prefix)/share/zsh-autosuggestions/zsh-autosuggestions.zsh
```

Apply it:

```sh
$ confctl zsh
```

## How it works

confctl follows a build-system model:

1. **Specs** identify what to build: `tools/kitty`, `brew::neovim`, `uvx::ruff`, `asdf::nodejs@18`
2. **Resolvers** know how to handle each spec type
3. **Dependencies** are resolved recursively before the current target builds
4. A **worker process** executes the build graph while the **main process** renders a live TUI showing progress

## Writing configurations

### The `.confbuild.py` file

Each configuration lives in a `.confbuild.py` file. confctl loads it as a Python module, finds the target function, and calls it with a `conf` object (a `ConfDep` instance).

```python
def main(conf):
    # This function is the default target.
    # "conf" provides actions for installing, configuring, and running commands.
    pass
```

**Target resolution:** When you run `confctl zsh`, confctl looks for `zsh/.confbuild.py` and calls the function named after the directory (`zsh`), falling back to `main`. You can have multiple targets in one file:

```python
def kitty(conf):
    """Default target (matches directory name)."""
    conf[":theme"]  # depend on the "theme" target below
    conf.render("kitty.conf.j2", "~/.config/kitty/kitty.conf")

def theme(conf):
    """Secondary target, invoked as kitty:theme or as a dependency."""
    conf.sh("git clone --depth 1 https://github.com/dexpota/kitty-themes.git ~/.config/kitty/themes")
```

### Module-level variables

Variables defined at the top level of a `.confbuild.py` file are loaded into context automatically:

```python
# git/.confbuild.py
GIT_NAME = "Your Name"
GIT_EMAIL = "you@example.com"

def git(conf):
    conf.render(".gitconfig.j2", "~/.gitconfig")
```

Inside `.gitconfig.j2`, `{{ GIT_NAME }}` and `{{ GIT_EMAIL }}` are available.

The special variable `CONFCTL_RESOLVERS` (only in the root config) registers additional resolver modules.

### Actions

The `conf` object exposes these actions:

#### Setting context variables — `conf(...)`

```python
conf(editor="nvim", shell="zsh")
conf(paths={"bin": "~/.local/bin", "config": "~/.config"})
```

Sets variables accessible in templates and child configs. Nested dicts become scoped contexts. String values support lazy Jinja2 evaluation — they're rendered when first accessed, not when set.

#### Declaring dependencies — `conf[specs]`

```python
# Single dependency
conf["brew::ripgrep"]

# Multiple dependencies
conf["brew::git", "brew::gh", "brew::lazygit"]

# Internal target (same file)
conf[":theme"]

# Subdirectory config
conf["./kitty"]

# Relative path
conf["../fonts"]
```

Dependencies are resolved and built before execution continues. The return value is the resolver result (e.g., a `Path` for path specs, status info for brew specs).

#### Rendering templates — `conf.render(src, dst)`

```python
conf.render("kitty.conf.j2", "~/.config/kitty/kitty.conf")
```

Renders a Jinja2 template from `src` (relative to the current config directory) to `dst`. All context variables are available in the template. Parent directories are created automatically.

#### Rendering strings — `conf.render_str(template)`

```python
result = conf.render_str("Hello {{ name }}")
```

Renders a Jinja2 template string and returns the result.

#### Running shell commands — `conf.sh(cmd)`

```python
conf.sh("killall kitty || true")
conf.sh("git clone {{ repo_url }} {{ dest_dir }}")
```

Executes a shell command. The command string is rendered as a Jinja2 template first. Returns a result object that supports:

```python
result = conf.sh("brew list --versions")
if "neovim" in result:    # check if string appears in output
    ...
if result:                 # truthy if exit code == 0
    ...
```

#### Running with sudo — `conf.sudo(cmd)`

```python
conf.sudo("cp {{ src }} /etc/target")
```

Same as `conf.sh()` but with interactive sudo password prompt.

#### Showing messages — `conf.msg(text)`

```python
conf.msg("Configuration complete!")
```

Displays a message in the TUI output.

### Accessing dependency context

In templates, use the `dep()` function to access variables from other configs:

```jinja2
# In .zshrc.j2
{{ dep('../brew').zsh_profile }}
{{ dep('../nvm').zsh_rc }}
{{ dep('./starship').zsh_rc }}
```

This is how shell configs compose — each tool defines a `zsh_rc` snippet, and the shell template pulls them all together.

### Special template variables

These are always available in templates:

| Variable | Description |
|----------|-------------|
| `current_config_dir` | Absolute path to the directory containing the current `.confbuild.py` |
| `env` | Access to environment variables (`{{ env.HOME }}`, `{{ env.USER }}`) |
| `dep(path)` | Function to access another config's context |

Plus any variables set via `conf(...)` or module-level definitions, and everything from parent contexts.

## Specs and resolvers

A **spec** tells confctl *what* to resolve. The format is `resolver::spec_value`.

### Built-in resolvers

| Resolver | Spec format | What it does |
|----------|-------------|--------------|
| `conf` | `path/to/config[:target]` | Loads and builds a `.confbuild.py` configuration |
| `path` | `path::~/some/file` | Returns a `Path` object, creates parent directories |
| `dir` | `dir::~/some/dir` | Returns a `Path` object, creates the directory |

The `conf` resolver is the default — you don't need the `conf::` prefix:

```python
conf["tools/kitty"]          # same as conf["conf::tools/kitty"]
conf["tools/kitty:theme"]    # call the "theme" target
```

### Contrib resolvers

Register these in your root `.confbuild.py`:

```python
CONFCTL_RESOLVERS = [
    "confctl.contrib.homebrew",
    "confctl.contrib.pipx",
    "confctl.contrib.pyenv",
    "confctl.contrib.uvx",
    "confctl.contrib.asdf",
    "confctl.contrib.mise",
]
```

| Resolver | Spec format | What it does |
|----------|-------------|--------------|
| `brew` | `brew::package`, `brew::package@version` | Installs a Homebrew formula/cask (skips if already installed) |
| `pipx` | `pipx::package`, `pipx::package@version` | Installs a Python tool via pipx |
| `pyenv` | `pyenv::python@version` | Installs a Python version via pyenv |
| `uvx` | `uvx::package`, `uvx::package@version` | Installs a Python tool via `uv tool install` |
| `asdf` | `asdf::plugin@version`, `asdf::plugin` | Installs a tool version via asdf (defaults to latest) |
| `mise` | `mise::tool@version`, `mise::tool` | Installs a tool version via mise (defaults to latest) |

All contrib resolvers auto-bootstrap their underlying tool if it's not found — installing via Homebrew first, then falling back to official install scripts.

## Project organization patterns

### Pattern: tool installation + configuration

The most common pattern — install a tool and render its config:

```python
def kitty(conf):
    conf["brew::kitty"]
    conf(font="FiraCode Nerd Font", font_size="11.0")
    conf.render("kitty.conf.j2", "~/.config/kitty/kitty.conf")
```

### Pattern: shell integration

Tools that need shell integration export a `zsh_rc` variable:

```python
# starship/.confbuild.py
def main(conf):
    conf["brew::starship"]
    conf(zsh_rc='eval "$(starship init zsh)"')
    conf.render("starship.toml", "~/.config/starship.toml")
```

Then the shell config pulls it in:

```jinja2
{# zsh/.zshrc.j2 #}
{{ dep('../starship').zsh_rc }}
```

### Pattern: conditional setup

Use regular Python for conditional logic:

```python
def main(conf):
    conf["brew::neovim"]

    themes_dir = Path("~/.config/kitty/themes").expanduser()
    if not themes_dir.exists():
        conf.sh("git clone --depth 1 https://github.com/dexpota/kitty-themes.git {{ themes_dir }}")
```

### Pattern: orchestrator config

A top-level config that aggregates sub-configs:

```python
# macos/.confbuild.py
def macos(conf):
    conf[
        ":common",
        "./brew",
        "./git",
        "./kitty",
        "./tmux",
        "./zsh",
    ]
```

### Pattern: file iteration

Process multiple files from a directory:

```python
from pathlib import Path

def commands(conf):
    conf(scripts_dir=conf["dir::~/.local/opt/scripts"])

    for f in Path(__file__).parent.rglob("*.sh"):
        dest = conf.scripts_dir / f.name
        conf.render(f, dest)
        dest.chmod(0o700)
```

## CLI usage

```sh
# Build specific configs
confctl tools/kitty
confctl tools/kitty tools/tmux

# Specify configs root directory
confctl -C ~/my-configs tools/kitty

# Use environment variable for configs root
export CONFCTL_CONFIGS_ROOT=~/my-configs
confctl tools/kitty
```

## MCP server

confctl ships with an optional MCP (Model Context Protocol) server so LLM clients (Claude Code, Claude Desktop, etc.) can discover and run your configs directly.

Install with the `mcp` extra:

```sh
uv tool install 'confctl[mcp]'
# or: pipx install 'confctl[mcp]'
```

Run over stdio:

```sh
confctl mcp -C ~/my-configs
# or
CONFCTL_CONFIGS_ROOT=~/my-configs confctl mcp
```

Exposed tools:

| Tool | Arguments | Description |
|------|-----------|-------------|
| `list_specs` | `configs_root?` | Scans the configs root for `.confbuild.py` files and returns discovered specs. |
| `run_specs` | `specs: list[str]`, `configs_root?` | Runs the given specs in a worker process and returns a human-readable summary of the op tree. Empty list runs the root config's `main` target. |
| `run_specs_json` | same as `run_specs` | Same as `run_specs` but returns raw JSON (ops, logs, errors). |

Register with Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "confctl": {
      "command": "confctl",
      "args": ["mcp", "-C", "/Users/you/my-configs"]
    }
  }
}
```

Or with Claude Code:

```sh
claude mcp add confctl -- confctl mcp -C ~/my-configs
```

## Development

Requires Python >= 3.12 and [uv](https://github.com/astral-sh/uv).

```sh
uv venv && source .venv/bin/activate && uv sync

# Lint & format
ruff check src/
ruff format src/

# Type check
mypy src/confctl/

# Tests (Docker)
docker build -f Dockerfile.test -t confctl-test . && docker run --rm confctl-test
```
