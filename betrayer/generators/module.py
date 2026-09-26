"""Module generator for Betrayer Framework.

Creates a new module within an existing Betrayer application.
Modules are structural units that group related functionality.

Example usage:
    betrayer generate module users
    betrayer generate module orders --with-tests
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from betrayer.generators.base import GeneratorResult, TemplateGenerator, GeneratorError