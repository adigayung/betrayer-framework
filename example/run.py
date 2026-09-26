"""Run the Betrayer example application.

Usage::

    python example/run.py

The script makes the project root importable so it works from a checkout
without installing the package.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from example.app import main  # noqa: E402  (import after sys.path setup)

if __name__ == "__main__":
    raise SystemExit(main())
