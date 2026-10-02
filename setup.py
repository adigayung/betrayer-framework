"""Compatibility shim for ``setup.py`` based tooling.

All package metadata (distribution name ``betrayer``, version, dependencies,
console scripts, ...) lives in ``pyproject.toml`` (PEP 621).  This file is
kept so that ``bet check`` project-structure validation still finds a
``setup.py`` and so legacy tooling can invoke ``python setup.py`` without
duplicating - and potentially contradicting - the canonical metadata.
"""

from setuptools import setup

setup()
