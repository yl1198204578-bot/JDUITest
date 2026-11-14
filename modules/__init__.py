import os
import importlib
import inspect

from modules.base import BaseModule

_modules = []


def discover_modules():
    global _modules
    _modules = []
    modules_dir = os.path.dirname(__file__)
    for f in sorted(os.listdir(modules_dir)):
        if f.endswith(".py") and not f.startswith("_") and f != "base.py":
            module_name = f[:-3]
            try:
                mod = importlib.import_module("modules." + module_name)
                for name, cls in inspect.getmembers(mod, inspect.isclass):
                    if issubclass(cls, BaseModule) and cls is not BaseModule:
                        instance = cls()
                        _modules.append(instance)
            except Exception as e:
                print("Failed to load module {}: {}".format(module_name, e))


def get_modules():
    if not _modules:
        discover_modules()
    return _modules


def get_module(name):
    for m in get_modules():
        if m.name == name:
            return m
    return None
