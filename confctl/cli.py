import logging
import logging.config

import docopt

from confctl import self_conf
from confctl.conf import Base, Param
from confctl.constants import (
    DEFAULT_CONFCTL_CACHE_DIR,
    DEFAULT_CONFCTL_CONFIG_FILE,
    DEFAULT_CONFCTL_USER_CONFIGS,
)

command_doc = """
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
"""


logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "simple": {
                "format": "[{asctime}] {message}",
                "datefmt": "%H:%M:%S",
                "style": "{",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "simple",
                "level": "DEBUG",
            }
        },
        "loggers": {
            "": {"level": "WARNING", "handlers": ["console"]},
            "configs": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        },
    }
)


def _extract_settings(args):
    options = {}

    if args.get("configure", False):
        options["configurations"] = args["<configuration>"] + (
            ["self"] if args.get("self") else []
        )
        flags = args["--flags"]
        machine_id = args["--machine-id"]
        target = (
            args["--nb"]
            and "nb"
            or args["--pc"]
            and "pc"
            or args["--srv"]
            and "srv"
            or args["--target"]
        )
        if target:
            options["TARGET"] = target
        if machine_id:
            options["MACHINE_ID"] = machine_id
        if flags:
            options["flags"] = flags

    return options


class _Conf(Base):
    TARGET = Param()
    MACHINE_ID = Param()
    CONFCTL_CONFIG_FILE = Param.PATH(DEFAULT_CONFCTL_CONFIG_FILE)
    CONFCTL_USER_CONFIGS = Param.PATH(DEFAULT_CONFCTL_USER_CONFIGS)
    CONFCTL_CACHE_DIR = Param.PATH(DEFAULT_CONFCTL_CACHE_DIR)

    flags = Param({"no:full"})
    configurations = Param([])

    def __init__(self):
        super().__init__("confctl", "/tmp", "/tmp")

    def __str__(self):
        return "confctl"

    def _load_configuration(self, name, path):
        import importlib.util

        if name == "self":
            return self_conf

        if not path.exists():
            self.error("Configuration does not exist.", operation=f"configs/{name}")
            return

        conf_path = path / "__init__.py"
        spec = importlib.util.spec_from_file_location(f"configs.{name}", conf_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _get_configurations(self):
        return self.configurations or [
            d.name
            for d in self.CONFCTL_USER_CONFIGS.iterdir()
            if d.is_dir() and (d / "__init__.py").exists()
        ]

    def configure(self):
        self.info(
            'Configuring "%s" target with %s flags...',
            self.text.t(self.TARGET),
            self.flags,
        )

        self.ensure_folders(self.CONFCTL_CACHE_DIR, silent=True)

        for conf_name in self._get_configurations():
            skip_flag = f"no:{conf_name}"
            if skip_flag in self.flags:
                self.debug(
                    "[configs/%s] Skipped because of %s flag", conf_name, skip_flag
                )
                continue

            self.info("[configs/%s] Configuring...", conf_name)

            conf_dir = self.CONFCTL_USER_CONFIGS / conf_name
            conf_cache_dir = (
                self.CONFCTL_CACHE_DIR / f"{self.TARGET}-{self.MACHINE_ID}/{conf_name}"
            )

            conf_module = self._load_configuration(conf_name, conf_dir)
            if not conf_module:
                continue

            conf = conf_module.Configuration(
                configuration_name=conf_name,
                configuration_dir=conf_dir,
                cache_dir=conf_cache_dir,
                msg_indent="    ",
            )

            conf.load_file(self.CONFCTL_CONFIG_FILE)
            conf.load_env()
            conf.load(
                "cli-args",
                {
                    "flags": self.flags,
                    "configurations": self.configurations,
                    "TARGET": self.TARGET,
                    "MACHINE_ID": self.MACHINE_ID,
                },
            )
            conf.configure()
            self.info("[configs/%s] Configured.", conf_name)


def main():
    args = docopt.docopt(command_doc, version="confctl v1.0")

    conf = _Conf()
    conf.load_file(conf.CONFCTL_CONFIG_FILE)
    conf.load_env()
    conf.load("cli-args", _extract_settings(args))

    if args.get("configure"):
        conf.configure()


if __name__ == "__main__":
    main()
