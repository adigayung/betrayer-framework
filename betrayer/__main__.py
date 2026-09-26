"""Module entry point: ``python -m betrayer <command>``."""

from __future__ import annotations

from betrayer.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
