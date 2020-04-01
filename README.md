<p align="center">
    <a href="https://pypi.org/project/confctl/">
        <img src="https://badge.fury.io/py/confctl.svg" alt="Package version">
    </a>
</p>

# confctl

Helps to organize you configs and how they generated, installed.

```sh
$ confctl configure i3 rofi
```

![Example execution](https://github.com/miphreal/confctl/raw/master/docs/example_output.png)


```sh
$ confctl --help
Usage:
  confctl configure [self] [<configuration>...]
                   [--target=<target-system>|--nb|--pc|--srv]
                   [--flags=<list-of-flags>] [--machine-id=<unique-node-id>]

Commands:
  configure       Cofiugre software on the host system (e.g. i3)

Options:
  -h --help       Show this help
  -v --version    Show version

Options for `confctl configure`:
  --target=<target>  Current system type (nb, pc, srv)
  --machine-id=<node-id>  Current system unique id (e.g. work.pc)
  --flags=<flags>    A comma separated list of extra flags
  ```

## Getting started

1. Create a virtual env specially for your configuration (use any tool you prefer for managing/creating python virtual envs)

```sh
$ pyenv virtualenv 3.8.2 confctl
```

2. Activate & install `confctl`
```sh
$ pyenv shell confctl
$ pip install confctl
$ confctl configure self --target=laptop --machine-id=dellxps
```

Note, we pass `--target` to specify the "type" of device and `--machine-id` to identify current device.
This info will be remembered in `~/.config/confctl/config` file. It might be usefull to understand
during configuration what it's applied to (e.g. to render differend configs for pc and laptop as
they might have differnt parameters).

3. Create a couple configs

Go to `~/.config/confctl/user-configs` and create there a folder with `__init__.py` inside.
`__init__.py` must define `Configuration` class (inherited from `Base`, which btw also provides some handy utils to run sh commands, render templates, etc).

```py
# ~/.config/confctl/user-configs/console/__init__.py
from confctl import Base, Param


class Configuration(Base):
    HOME = Param.PATH("~")
    TARGET = Param()
    tmux_plugin_manager_dir = Param.PATH("~/.tmux/plugins/tpm")
    tpm_repo = "https://github.com/tmux-plugins/tpm"
    fonts_repo = "https://github.com/ryanoasis/nerd-fonts"
    prezto_repo = "https://github.com/sorin-ionescu/prezto"

    def configure(self):
        # patched fonts
        fonts_dir = self.CACHE_DIR / "fonts"
        if not (fonts_dir / ".git").exists():
            self.run_sh(f"git clone --depth 1 {self.fonts_repo} {fonts_dir}")
            self.run_sh(f'bash {fonts_dir / "install.sh"}')

        # tmux
        self.ensure_folders(self.tmux_plugin_manager_dir)
        if not (self.tmux_plugin_manager_dir / ".git").exists():
            self.run_sh(f"git clone {self.tpm_repo} {self.tmux_plugin_manager_dir}")
        self.template("tmux.conf.j2", symlink=self.HOME / ".tmux.conf")

        # prezto
        prezto_dir = self.HOME / ".zprezto"
        if not (prezto_dir / ".git").exists():
            self.run_sh(f'git clone --recursive {self.prezto_repo} "{prezto_dir}"')

        if not (self.HOME / ".zpreztorc").exists():
            init_zprezto = """
setopt EXTENDED_GLOB
for rcfile in "${ZDOTDIR:-$HOME}"/.zprezto/runcoms/^README.md(.N); do
ln -s "$rcfile" "${ZDOTDIR:-$HOME}/.${rcfile:t}"
done
"""
            self.warning(
                f"You may need to manually setup `zprezto`: \n{init_zprezto}"
            )
```

The folder with configuration can contain any assets/templates used during configuration.
In this example, there should be `tmux.conf.j2`.


4. Then you simply run this configuration

```sh
$ confctl configure console
```

Or just

```sh
$ confctl configure
```
which will apply all defined configurations.

## API

TBD


## Internals

TBD

