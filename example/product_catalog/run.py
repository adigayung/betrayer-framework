"""Run the Product Catalog Golden Path example over HTTP (+ optional WebSocket).

Usage::

    python example/product_catalog/run.py            # REST only
    python example/product_catalog/run.py --realtime # REST + WebSocket channel

Serves the REST API on http://127.0.0.1:5000/api/products using SQLite
(``product_catalog.db`` in the current directory).  With ``--realtime`` the same
server also exposes the ``/ws/products`` WebSocket channel: creating a product
over HTTP (or WebSocket) emits the ``product.created`` event which the realtime
manager fans out to every connected client — proving Service reuse with no
duplicated business logic.

The script makes the project root importable so it works from a checkout
without installing.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    """Build the catalog app and serve it (REST, optionally with realtime)."""
    import argparse

    parser = argparse.ArgumentParser(description="Product Catalog Golden Path")
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="also mount the WebSocket /ws/products channel",
    )
    args = parser.parse_args()

    if args.realtime:
        from example.product_catalog.app import create_realtime_app

        flask_app = create_realtime_app()
    else:
        from example.product_catalog.app import create_flask_app

        flask_app = create_flask_app()

    flask_app.run(host="127.0.0.1", port=5000, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
