import logging
from pathlib import Path
import os


class text:
    RGB = lambda r, g, b: f"\033[38;2;{r};{g};{b}m"
    TITLE = "\033[95m"
    DEBUG = RGB(169, 169, 169)
    INFO = RGB(0, 64, 133)  # alt "\033[94m"
    OPERATION = RGB(12, 84, 96)
    WARNING = "\033[93m"
    ERROR = "\033[91m"
    REVERSE = "\033[7m"
    FADE = "\033[1m"
    BOLD = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    ENDC = "\033[0m"

    def __init__(self, code, text, prev_code="", ensure_code_after=("%s", "}")):
        self.code = code
        self.prev_code = prev_code
        self.text = text
        self.ensure_code_after = ensure_code_after

    @classmethod
    def b(cls, text):
        return cls(cls.BOLD, text)

    @classmethod
    def i(cls, text):
        return cls(cls.ITALIC, text)

    @classmethod
    def u(cls, text):
        return cls(cls.UNDERLINE, text)

    @classmethod
    def t(cls, text):
        return cls(cls.TITLE, text)

    @classmethod
    def err(cls, text):
        return cls(cls.ERROR, text)

    @classmethod
    def info(cls, text):
        return cls(cls.INFO, text)

    @classmethod
    def debug(cls, text):
        return cls(cls.DEBUG, cls(cls.FADE, text, prev_code=cls.DEBUG))

    @classmethod
    def warning(cls, text):
        return cls(cls.WARNING, text)

    def __str__(self):
        text = str(self.text)
        if self.ensure_code_after:
            for entry in self.ensure_code_after:
                text = text.replace(entry, f"{entry}{self.code}")

        return f"{self.code}{text}{self.ENDC}{self.prev_code}"


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

    def __set_name__(self, conf, name):
        self._name = name
        conf.register_option(name, self)

    def __get__(self, obj, obj_type, dump=False):
        value = obj.__dict__.get(self._name, self.take_default)
        if self._name not in obj.__dict__:
            value = self._handle_value(value)
            obj.debug(
                "[%s:use:default-value] %s = %s",
                str(obj),
                text.i(self._name),
                text.i(value),
            )
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
    def __init__(self, name, msg_indent=""):
        self.logger = logging.getLogger(f"configs.{name}")
        self.msg_indent = msg_indent

    def _handle_msg_indent(self, msg):
        return f"{self.msg_indent}{msg}"

    def log(self, msg, *args, **kwargs):
        msg = self._handle_msg_indent(msg)
        self.logger.info(text(text.OPERATION, msg), *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        msg = self._handle_msg_indent(msg)
        self.logger.debug(text.debug(msg), *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        msg = self._handle_msg_indent(msg)
        self.logger.info(text.info(msg), *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        msg = self._handle_msg_indent(msg)
        self.logger.error(text.warning(msg), *args, **kwargs)

    def error(self, *args):
        msg = self._handle_msg_indent(msg)
        self.logger.error(*args)

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
            self.debug("[%s:load:%s] %s = %s", str(self), source_name, k, v)
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
    def __init__(self, configuration_name, configuration_dir, cache_dir, **kwargs):
        self.name = configuration_name
        super().__init__(self.name, **kwargs)

        self.CONFIGURATION_DIR = Path(configuration_dir)
        self.CACHE_DIR = Path(cache_dir)
        self.ensure_folders(self.CACHE_DIR, silent=True)

    def __str__(self):
        return f"configs/{self.name}"

    def _op_prefix(self, op, sign="✔"):
        return f"[ {sign} {op:<10} ]"

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

    def ensure_folders(self, *folders, silent=False):
        for f in folders:
            folder = Path(f).expanduser()
            if not silent:
                self.log("%s Ensure exists %s", self._op_prefix("folder"), folder)
            folder.mkdir(parents=True, exist_ok=True)

    def _template(self, src, dst, **context):
        from jinja2 import Template

        src = Path(src).expanduser()
        dst = Path(dst).expanduser()

        with open(src) as _in:
            template = Template(_in.read())
            self.log(
                "%s Rendering %s --> %s", self._op_prefix("template"), src.name, dst
            )
            template.stream(**context).dump(str(dst))

        return dst

    def template(self, src, dst=None, symlink=None):
        if dst is None and Path(src).suffix == ".j2":
            dst = Path(str(src)[:-3])
        src, dst = self._handle_src_dst(src, dst)
        self.ensure_folders(dst.parent)
        dst = self._template(src, dst, **self)
        if symlink:
            self.symlink(symlink, dst)
        return dst

    def install_packages(self, packages):
        if isinstance(packages, str):
            packages = packages.splitlines()
            packages = [p.strip() for p in packages if not p.strip().startswith("#")]

        packages = " ".join(packages)
        self.run_sh(f"sudo apt install -y {packages}")

    def run_sh(self, *commands):
        import subprocess
        import shlex

        outputs = []
        any_failed = False
        for cmd in commands:
            if not any_failed:
                self.log("%s %s", self._op_prefix("sh"), cmd)
                try:
                    output = subprocess.check_output(cmd, shell=True)
                    outputs.append(output)
                except subprocess.SubprocessError:
                    self.error("%s %s", self._op_prefix("sh:failed", "❌"), cmd)
                    outputs.append(None)
                    any_failed = True
            else:
                self.warning("%s %s", self._op_prefix("sh:skipped", "⚠"), cmd)

        return outputs

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
