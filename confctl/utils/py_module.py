import importlib.util

from functools import cache
from importlib import import_module
from pathlib import Path


@cache
def load_python_module(path: Path | str):
    if isinstance(path, str):
        # expecting a python module path
        return import_module(path)

    # expecting a fs path to a python module
    spec = importlib.util.spec_from_file_location("tmp", path)
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    raise ImportError(f"{path} cannot be loaded or found.")


@cache
def load_python_obj(path: str):
    path, obj_name = path.rsplit(".", 1)
    module = import_module(path)
    return getattr(module, obj_name)
