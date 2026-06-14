"""
Loader fuer die Skripte (render-config.py, find-shared-models.py),
die nicht als Module geschrieben sind (haben keinen if __name__ == '__main__'
innerhalb einer Klasse/Function-Wrapper).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_script(name: str):
    """Laedt ein Skript aus dem Repo-Root als importierbares Modul."""
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
