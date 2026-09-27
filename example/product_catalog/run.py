"""Run the Product Catalog Golden Path example over HTTP.

Usage::

    python example/product_catalog/run.py

Serves the REST API on http://127.0.0.1:5000/api/products using SQLite
(``product_catalog.db`` in the current directory).  The script makes the
project root importable so it works from a checkout without installing.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from example.product_catalog.app import create_flask_app  # noqa: E402


def main() -> int:
    """Build the catalog app and serve it with Flask's dev server."""
    flask_app = create_flask_app()
    flask_app.run(host="127.0.0.1", port=5000, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
