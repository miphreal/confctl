import logging
from pathlib import Path
import os

from confctl import utils

logger = logging.getLogger(__name__)


def load_list(v):
    if isinstance(v, str):
        return list(filter(bool, (v or "").split(",")))
    return v


def load_set(v):
    if isinstance(v, str):
        return set(filter(bool, (v or "").split(",")))
    return v


def dump_iterable(v):
    if isinstance(v, (set, list, tuple)):
        return ",".join(map(str, v))
    return str(v)


class Param:
    undefined = object()
    take_default = object()

    @classmethod
    def PATH(cls, default=undefined, *args, **kwargs):
        kwargs["load"] = lambda value: Path(value).expanduser()
        if default is not cls.undefined:
            return cls(Path(default).expanduser(), *args, **kwargs)
        return cls(default, *args, **kwargs)

    def __init__(
        self, default=undefined, load=undefined, dump=str, empty_values=("", None)
    ):
        self._name = None
        self._default = default
        self.load = load
        if (
            load is self.undefined
            and default is not self.undefined
            and default is not None
        ):
            if isinstance(default, set):
                self.load = load_set
                if dump is str:
                    dump = dump_iterable
            elif isinstance(default, (list, tuple)):
                self.load = load_list
                if dump is str:
                    dump = dump_iterable
            else:
                self.load = type(default)

        self.dump = dump
        self._empty_values = empty_values

    def _handle_value(self, value):
        if value in self._empty_values:
            if self._default is not self.undefined:
                return self._default
        if value is self.take_default:
            if self._default is not self.undefined:
                return self._default
            else:
                raise ValueError(f'"{self._name}" is required and was not set')
        return value

    def __set_name__(self, obj_type, name):
        self._name = name
        obj_type.register_option(name, self)

    def __get__(self, obj, obj_type, dump=False):
        value = obj.__dict__.get(self._name, self.take_default)
        if self._name not in obj.__dict__:
            value = self._handle_value(value)
            logger.debug("[%s:load:default-value] %s = %s", str(obj), self._name, value)
        obj.__dict__[self._name] = value
        if dump:
            return self.dump(value)
        return value

    def __set__(self, obj, value):
        if self.load is not self.undefined:
            value = self.load(value)
        value = self._handle_value(value)
        obj.__dict__[self._name] = value

    def __delete__(self, obj):
        del obj.__dict__[self._name]


class _ConfigContainer:
    @classmethod
    def register_option(cls, name, option):
        if not hasattr(cls, "_defined_options"):
            cls._defined_options = []
        cls._defined_options.append(name)

    def keys(self):
        return self._defined_options

    def items(self):
        return [(k, getattr(self, k)) for k in self._defined_options]

    def __iter__(self):
        return iter(self._defined_options)

    def __str__(self):
        return "settings"

    def __getitem__(self, key):
        return getattr(self, key)

    def dump(self):
        return {
            key: self.__class__.__dict__[key].__get__(self, self.__class__, dump=True)
            for key in self.keys()
        }

    def export(self):
        """Exports all settings to os.environ"""
        for k, v in self.items():
            if isinstance(v, (set, list, tuple)):
                v = ",".join(v)
            os.putenv(k, v)

    def load(self, source_name, options):
        for k in sorted(set(self).intersection(options), key=lambda k: k.lower()):
            v = options[k]
            logger.debug("[%s:load:%s] %s = %s", str(self), source_name, k, v)
            setattr(self, k, v)

    def load_file(self, config_file):
        config_file = Path(config_file).expanduser()
        if config_file.exists():
            config = {}
            with config_file.open() as cf:
                for line in cf:
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue
                    k, __, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if k.isupper():
                        config[k] = v
            # TODO. try except
            config_path = config_file.relative_to(Path.home())
            self.load(f"~/{config_path}", config)

    def load_env(self):
        self.load("env", os.environ)


class Base(_ConfigContainer):
    def __init__(self, configuration_name, configuration_dir, cache_dir):
        self.name = configuration_name
        self.logger = logging.getLogger(f"configs.{self.name}")

        self.CONFIGURATION_DIR = Path(directory)
        self.CACHE_DIR = cache_dir
        self.ensure_folders(self.CACHE_DIR, silent=True)

    def __str__(self):
        return f"configs/{self.name}"

    def debug(self, *args):
        self.logger.debug(*args)

    def info(self, *args):
        self.logger.info(*args)

    def error(self, *args):
        self.logger.error(*args)

    def _handle_src_dst(self, src, dst):
        src = Path(src).expanduser()
        if dst is None and not src.is_absolute():
            dst = src
        dst = Path(dst).expanduser()
        if not src.is_absolute():
            src = self.CONFIGURATION_DIR / src
        if not dst.is_absolute():
            dst = self.CACHE_DIR / dst
        return src, dst

    def ensure_folders(self, *args, **kwargs):
        utils.ensure_folders(*args, **kwargs)

    def template(self, src, dst=None, symlink=None):
        if dst is None and Path(src).suffix == ".j2":
            dst = Path(str(src)[:-3])
        src, dst = self._handle_src_dst(src, dst)
        self.ensure_folders(dst.parent)
        dst = utils.template(src, dst, **self)
        if symlink:
            self.symlink(symlink, dst)
        return dst

    def install_packages(self, *args):
        utils.install_packages(*args)

    def run_sh(self, *args):
        return utils.run_sh(*args)

    def run_parallel(self, *args):
        utils.run_parallel(*args)

    def symlink(self, link, target):
        link, target = Path(link).expanduser(), Path(target).expanduser()
        try:
            link.unlink()
        except OSError:
            pass
        link.symlink_to(target)

    def copy_file(self, src, dst=None, symlink=None):
        src, dst = self._handle_src_dst(src, dst)

        self.run_sh(f"cp -f {src} {dst}")
        if symlink:
            self.symlink(symlink, dst)
        return dst

    def configure(self):
        raise NotImplementedError
