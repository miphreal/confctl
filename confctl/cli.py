from importlib import import_module
import logging
import logging.config

import docopt

from confctl.conf import Base, Param


logger = logging.getLogger(__name__)

command_doc = """
Usage:
  confctl configure [<configuration>...]
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
            "confctl": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        },
    }
)


def _extract_settings(args):
    options = {}

    if args.get("configure", False):
        options["configurations"] = args["<configuration>"]
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
    CONFCTL_CONFIG_DIR = Param.PATH("~/.config/confctl")
    CONFCTL_CONFIG_FILE = Param.PATH("~/.config/confctl/config")
    CONFCTL_USER_CONFIGS = Param.PATH("~/.config/confctl/configs")
    CONFCTL_CACHE_DIR = Path.home() / ".cache/confctl"

    flags = Param({"no:full"})
    configurations = Param([])

    def __str__(self):
        return "confctl"

    def _load_configuration(self, path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(f"configs.{name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _get_configurations(self):
        return self.configurations or [
            d.name
            for d in slef.CONFCTL_USER_CONFIGS.iterdir()
            if d.is_dir() and (d / "__init__.py").exists()
        ]

    def configure(self):
        logger.info('Configuring "%s" target with %s flags...', self.TARGET, self.flags)

        ensure_folders(self.CONFCTL_CONFIG_DIR, self.CONFCTL_CACHE_DIR, silent=True)

        for conf_name in self._get_configurations():
            skip_flag = f"no:{conf_name}"
            if skip_flag in self.flags:
                logger.debug(
                    "[configs/%s] Skipped because of %s flag", conf_name, skip_flag
                )
                continue

            logger.info("[configs/%s] Configuring...", conf_name)

            conf_dir = self.CONFCTL_CONFIGS / conf_name
            conf_cache_dir = (
                self.CONFCTL_CACHE_DIR / f"{self.TARGET}-{self.MACHINE_ID}/{conf_name}"
            )

            conf_module = self._load_configuration(conf_dir)
            conf = conf_module.Configuration(
                configuration_name=conf_name,
                configuration_dir=conf_dir,
                cache_dir=conf_cache_dir,
            )

            conf.load_file(self.CONFCTL_CONFIG_FILE)
            conf.load_env()
            conf.load(str(self), self)
            conf.configure()
            logger.info("[configs/%s] Configured.", conf_name)


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
