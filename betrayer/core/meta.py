"""Framework identity and version constants.

Single source of truth for the values surfaced by the CLI, the machine
readable manifest (``.betrayer/manifest.json``) and the AI documentation.
Nothing else in the framework should hardcode these strings.
"""

from __future__ import annotations

FRAMEWORK_NAME: str = "Betrayer"
FRAMEWORK_SLUG: str = "betrayer"
FRAMEWORK_DESCRIPTION: str = "LLM-first Python framework for coding agents"
__version__: str = "0.1.0"
FOUNDATION_VERSION: str = "0.1.0"
ARCHITECTURE_VERSION: str = "1.0.0"

__all__ = [
    "FRAMEWORK_NAME",
    "FRAMEWORK_SLUG",
    "FRAMEWORK_DESCRIPTION",
    "__version__",
    "FOUNDATION_VERSION",
    "ARCHITECTURE_VERSION",
]
