"""
Loader for the scripts (render-config.py, find-shared-models.py) that
aren't written as modules (they have no if __name__ == '__main__' inside
a class/function wrapper).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_script(name: str):
    """Loads a script from the repo root as an importable module."""
    path = REPO_ROOT / name
    if not path.exists():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(
        name.replace(".py", ""), path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod
