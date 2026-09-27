# Golden Path — Product Catalog

The canonical, end-to-end Betrayer flow, proven by one small runnable app.

```
Project → Module → Model → Migration → Database → Repository → Service → Resource/API → Run → Test → Debug
```

Every step uses an existing framework API — nothing new is invented here.

## Component order (canonical)

| # | Step | Component | Where |
|---|------|-----------|-------|
| 1 | Project | `BetrayerApplication` + `Bootstrap` + `Config` | `app.py::build_application` |
| 2 | Database | `install_database(app)` → container service `"database"` | `betrayer.data.bootstrap` |
| 3 | Module | `ProductCatalogModule` registered on `app.modules` | `module.py` |
| 4 | Model | `Product(ORMModel)` (`id`, `name`, `price`, `stock`) | `models.py` |
| 5 | Migration | `CreateProductsTableMigration` via `MigrationRegistry.apply` | `migrations/` |
| 6 | Repository | `ProductRepository(BaseRepository[Product])` | `repository.py` |
| 7 | Service | `ProductService` (business rules + write transactions) | `service.py` |
| 8 | Resource/API | `ProductResource(CrudApiResource)` + `ProductSchema` | `routes.py`, `schemas.py` |
| 9 | Run | `FlaskAdapter` + `create_flask_app()` | `app.py` |

The wire flow is always
`HTTP → Resource → (parse + validate) → Service → Repository → ORM → SQLite`.
Request validation runs in the Resource/API layer through the canonical
pipeline (`ProductSchema`), so the service never repeats basic validation
(see `betrayer/ai/VALIDATION.md`).

## Commands / APIs used

```bash
# 1. project + module + migration (reusable generators)
bet create shop
cd shop && bet make module inventory
bet make migration create_products_table
```

```python
# 2. application wiring (composition root)
from betrayer import BetrayerApplication, Bootstrap, Config
from betrayer.data.bootstrap import install_database

app = BetrayerApplication(name="catalog", config=Config({
    "database.default.driver": "sqlite",
    "database.default.database": "catalog.db",
}))
Bootstrap(app).build()
install_database(app)                     # container service "database"

# 3. module -> repository + service; then migrations
app.modules.register(ProductCatalogModule)
app.modules.initialize_all()
apply_migrations(app)                      # MigrationRegistry.apply(database)
```

```python
# 4. serve the REST API
from example.product_catalog.app import create_flask_app
flask_app = create_flask_app(app)          # FlaskAdapter mounts ProductResource
```

Key APIs: `ORMModel`/`ORMField`, `BaseRepository`, `MigrationRegistry.apply`,
`create_table_sql(model, dialect)`, `CrudApiResource`, `FlaskAdapter`,
`install_database`, container `resolve("database")`.

## HTTP API

| Method | Path | Behaviour |
|--------|------|-----------|
| `GET` | `/api/products` | list (`200`, `meta.count`) |
| `GET` | `/api/products/<id>` | one item (`200` or `404`) |
| `POST` | `/api/products` | create (`201`; `422` when `name` missing) |
| `PUT` | `/api/products/<id>` | update (`200` or `404`) |
| `DELETE` | `/api/products/<id>` | delete (`204` or `404`) |

Errors use the framework envelope `{"success", "data", "error"}` with a stable
`error.code` (`VALIDATION_FAILED`, `RESOURCE_NOT_FOUND`, `BAD_REQUEST`, ...).

## Run / test / debug

```bash
# run the HTTP server on http://127.0.0.1:5000
python example/product_catalog/run.py

# end-to-end test (CLI generators + real SQLite + HTTP CRUD + persistence)
python -m pytest tests/test_golden_path.py -q

# try it by hand
curl -X POST http://127.0.0.1:5000/api/products -H "Content-Type: application/json" \
     -d '{"name":"Widget","price":9.5,"stock":3}'
curl http://127.0.0.1:5000/api/products
```

Debug with the existing mechanisms (no new debug subsystem):

```python
app.status()                 # lifecycle state + environment
app.core.report()            # registry / container / modules / extensions / events
app.inspect()                # full read-only snapshot
# CLI: bet doctor  /  bet validate --json
```

A failure in the data layer surfaces as a controlled JSON error carrying a
machine-readable `error.code` — never a leaked traceback.

## What the framework owns (no manual workaround)

- connecting a configured database and exposing it as container service `"database"` (`betrayer.data.bootstrap`);
- basic CRUD over the ORM (`BaseRepository`);
- schema DDL derived from the model + dialect (`betrayer.data.create_table_sql`);
- applying migrations in `sequence` order (`MigrationRegistry.apply`);
- the shared REST CRUD flow and error envelope (`CrudApiResource`, `FlaskAdapter`).
