import os

from confctl.conf import Base, Param
from confctl.constants import (
    DEFAULT_CONFCTL_CONFIG_FILE,
    DEFAULT_CONFCTL_USER_CONFIGS,
    DEFAULT_CONFCTL_BIN,
)


class Configuration(Base):
    MACHINE_ID = Param()
    TARGET = Param()
    CONFCTL_BIN = Param.PATH(DEFAULT_CONFCTL_BIN)
    CONFCTL_CONFIG_FILE = Param.PATH(DEFAULT_CONFCTL_CONFIG_FILE)
    CONFCTL_USER_CONFIGS = Param.PATH(DEFAULT_CONFCTL_USER_CONFIGS)
    CONFCTL_VENV = Param.PATH()
    CONFCTL_VENV_DEPS = Param("confctl")
    flags = Param(set())

    config_options_to_save = [
        "MACHINE_ID",
        "TARGET",
        "CONFCTL_USER_CONFIGS",
        "CONFCTL_VENV",
        "CONFCTL_VENV_DEPS",
    ]

    def configure(self):
        try:
            CONFCTL_VENV = self.CONFCTL_VENV
        except ValueError:
            CONFCTL_VENV = os.getenv("VIRTUAL_ENV")

        if not CONFCTL_VENV:
            self.error("`CONFCTL_VENV` or `VIRTUAL_ENV` env variable is not specified.")

        self.CONFCTL_VENV = CONFCTL_VENV

        self.ensure_folders(
            self.CONFCTL_CONFIG_FILE.parent, self.CONFCTL_BIN.parent,
        )

        if self.CONFCTL_CONFIG_FILE.exists() and not "full" in self.flags:
            self.warning(
                "%s No need to create config: already exists", self._op_prefix("config")
            )
        else:
            self.info("%s Creating blackcat config", self._op_prefix("config"))
            with (self.CACHE_DIR / "config").open("w") as cf:
                for k, v in self.dump().items():
                    if k not in self.config_options_to_save:
                        continue
                    cf.write(f"{k} = {v}\n")

        if self.CONFCTL_VENV_DEPS:
            self.run_sh(
                f"{self.CONFCTL_VENV}/bin/python -m pip -q --disable-pip-version-check install {self.CONFCTL_VENV_DEPS}"
            )

        self.symlink(self.CONFCTL_CONFIG_FILE, self.CACHE_DIR / "config")
        self.symlink(self.CONFCTL_VENV / "bin/confctl", self.CONFCTL_BIN)
