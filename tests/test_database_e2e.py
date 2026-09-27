"""Task 09.4 — Multi-database End-to-End tests (real engines, no fakes).

This suite proves the full Data Layer pipeline against **real** databases:

    Repository -> ORM Model -> Query Builder -> Compiler/SQLDialect
        -> DatabaseEngine -> Connection -> concrete database

Two concrete engines are exercised through the *same* ORM/Repository code
(no ``if database == ...`` anywhere):

* ``sqlite``  — standard library ``sqlite3`` (always available);
* ``duckdb``  — optional ``duckdb`` package (an in-process analytical engine).

If the optional DuckDB driver is not installed, the parameterized suite simply
runs on SQLite and DuckDB-only tests are skipped — the limitation is
documented, never hidden as a pass.  ``ENGINE_KINDS`` reports the engines the
current environment can actually exercise.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from betrayer.core.config import Config
from betrayer.data import (
    BelongsTo,
    DatabaseManager,
    DatabaseRegistry,
    HasMany,
    ManyToMany,
    Migration,
    MigrationRegistry,
    ORMField,
    ORMModel,
    Query,
    QueryError,
)
from betrayer.data.compiler import QueryCompiler
from betrayer.data.engines import (
    DuckDBDialect,
    DuckDBEngine,
    SQLiteDialect,
    SQLiteEngine,
    duckdb_available,
    register_builtin_engines,
)
from betrayer.data.exceptions import (
    ConnectionError,
    DatabaseConfigurationError,
    DatabaseError,
    UnsupportedDatabaseError,
)
from betrayer.data.query import execute_compiled

# ---------------------------------------------------------------------------
# Models under test (module level so string relationship targets resolve)
# ---------------------------------------------------------------------------


class User(ORMModel):
    __table__ = "users"

    id = ORMField(int, primary_key=True)
    name = ORMField(str, required=True)
    email = ORMField(str, nullable=True)
    active = ORMField(bool, default=True)
    age = ORMField(int, nullable=True)

    posts = HasMany("Post", foreign_key="author_id")


class Post(ORMModel):
    __table__ = "posts"

    id = ORMField(int, primary_key=True)
    title = ORMField(str, required=True)
    author_id = ORMField(int, nullable=True)
    published = ORMField(bool, default=False)

    author = BelongsTo("User")  # FK default: author_id


class Category(ORMModel):
    __table__ = "categories"

    id = ORMField(int, primary_key=True)
    name = ORMField(str, required=True)


class Product(ORMModel):
    __table__ = "products"

    id = ORMField(int, primary_key=True)
    sku = ORMField(str, required=True)

    categories = ManyToMany("Category")  # pivot default: products_categories


class Note(ORMModel):
    __table__ = "notes"

    id = ORMField(int, primary_key=True)
    body = ORMField(str, nullable=True)


MODELS = (User, Post, Category, Product, Note)

#: Table -> ordered columns ``(name, python_type, is_primary_key)``.
SCHEMA: Dict[str, List[tuple]] = {
    "users": [
        ("id", int, True),
        ("name", str, False),
        ("email", str, False),
        ("active", bool, False),
        ("age", int, False),
    ],
    "posts": [
        ("id", int, True),
        ("title", str, False),
        ("author_id", int, False),
        ("published", bool, False),
    ],
    "categories": [("id", int, True), ("name", str, False)],
    "products": [("id", int, True), ("sku", str, False)],
    "products_categories": [
        ("product_id", int, False),
        ("category_id", int, False),
    ],
}

#: Engines the parameterized suite runs on (documented, not silently skipped).
ENGINE_KINDS: List[str] = ["sqlite"] + (["duckdb"] if duckdb_available() else [])

#: Values with characters that break naive string interpolation.
DIRTY_VALUES = [
    "O'Brien",
    'double " quote',
    "semicolon; DROP TABLE users; --",
    "unicode 😀 ünïcödé",
    "percent 100% _wild%",
    "backslash \\ and \\n newline",
    "brackets [x] {y} (z)",
    "null-ish NUL\u0000byte",
]


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


class Database:
    """A registered, connected concrete engine bound to the test models.

    Uses the *public* configuration + registry path so the test proves
    ``Config -> DatabaseRegistry -> concrete engine -> DatabaseManager``
    exactly like an application would.
    """

    def __init__(self, kind: str, path) -> None:
        self.kind = kind
        self.path = str(path)
        self.config = Config(
            {
                "database.default.driver": kind,
                "database.default.database": self.path,
            }
        )
        self.registry = DatabaseRegistry(self.config)
        register_builtin_engines(self.registry)
        self.engine = self.registry.engine("default")
        self.dialect = self.engine.dialect()
        self.manager = DatabaseManager(self.engine)
        self.manager.connect()
        for model in MODELS:
            model.__connection__ = self.manager

    # -- helpers -------------------------------------------------------

    def execute(self, sql: str, parameters=None):
        return self.manager.execute(sql, parameters)

    def connection(self):
        return self.manager.connection

    def create_schema(self) -> None:
        quote = self.dialect.quote_identifier
        for table, columns in SCHEMA.items():
            parts = []
            for name, python_type, is_pk in columns:
                declaration = self.dialect.type_name(python_type)
                if is_pk:
                    declaration += " PRIMARY KEY"
                parts.append(f"{quote(name)} {declaration}")
            self.execute(f"CREATE TABLE {quote(table)} (" + ", ".join(parts) + ")")

    def close(self) -> None:
        try:
            self.manager.disconnect()
        finally:
            self.engine.close()

    def reopen(self) -> "Database":
        """A brand new Database on the same file (durability check)."""
        return Database(self.kind, self.path)


def seed(database: Database) -> None:
    """Insert deterministic rows atomically (commit on success)."""
    with database.engine.transaction():
        User.create(id=1, name="Alice", email="alice@example.com", active=True, age=30)
        User.create(id=2, name="Bob", email="bob@example.com", active=False, age=25)
        Post.create(id=1, title="First", author_id=1, published=True)
        Post.create(id=2, title="Second", author_id=1, published=False)
        Post.create(id=3, title="Third", author_id=2, published=True)


@pytest.fixture(params=ENGINE_KINDS)
def db(request, tmp_path) -> Database:
    kind = request.param
    suffix = "app.db" if kind == "sqlite" else "app.duckdb"
    database = Database(kind, tmp_path / suffix)
    database.create_schema()
    try:
        yield database
    finally:
        database.close()


# ---------------------------------------------------------------------------
# 1. Registration / configuration / multi-connection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ENGINE_KINDS)
def test_concrete_engine_registered_and_resolved(kind, tmp_path):
    database = Database(kind, tmp_path / "registered.db")
    try:
        assert kind in database.registry.registered_drivers()
        assert isinstance(database.engine, (SQLiteEngine, DuckDBEngine))
        assert database.engine.metadata()["driver"] == kind
        assert database.manager.is_connected is True
        info = database.registry.introspect()
        assert info["connections"]["default"]["registered"] is True
        assert info["connections"]["default"]["driver"] == kind
    finally:
        database.close()


def test_registry_supports_multiple_connection_names(tmp_path):
    config = Config(
        {
            "database.default.driver": "sqlite",
            "database.default.database": str(tmp_path / "default.db"),
            "database.analytics.driver": "sqlite",
            "database.analytics.database": str(tmp_path / "analytics.db"),
        }
    )
    registry = DatabaseRegistry(config)
    register_builtin_engines(registry)
    assert registry.names() == ["analytics", "default"]
    default = registry.engine("default")
    analytics = registry.engine("analytics")
    assert isinstance(default, SQLiteEngine) and isinstance(analytics, SQLiteEngine)
    assert default.database_path() != analytics.database_path()
    assert default.name == "default"
    assert analytics.name == "analytics"


def test_registry_unknown_driver_raises_structured_error(tmp_path):
    config = Config(
        {
            "database.default.driver": "does-not-exist",
            "database.default.database": str(tmp_path / "x.db"),
        }
    )
    registry = DatabaseRegistry(config)
    register_builtin_engines(registry)
    with pytest.raises(UnsupportedDatabaseError) as excinfo:
        registry.engine("default")
    assert "does-not-exist" in str(excinfo.value)


def test_registry_missing_connection_raises_configuration_error(tmp_path):
    registry = DatabaseRegistry(
        Config({"database.default.driver": "sqlite", "database.default.database": "x"})
    )
    register_builtin_engines(registry)
    with pytest.raises(DatabaseConfigurationError):
        registry.engine("nope")


def test_registry_configuration_never_leaks_secrets(tmp_path):
    config = Config(
        {
            "database.default.driver": "sqlite",
            "database.default.database": str(tmp_path / "secret.db"),
            "database.default.password": "supersecret",
        }
    )
    registry = DatabaseRegistry(config)
    register_builtin_engines(registry)
    engine = registry.engine("default")
    assert "supersecret" not in repr(registry.introspect())
    assert "supersecret" not in repr(engine.metadata())
    assert "supersecret" not in repr(registry.introspect()["connections"])


# ---------------------------------------------------------------------------
# 2. CRUD end to end (connect -> schema -> model -> repository -> database)
# ---------------------------------------------------------------------------


def test_connect_and_schema(db):
    assert db.manager.is_connected is True
    assert db.manager.connection is not None
    # the schema was created through the Connection contract
    assert User.repository().count() == 0
    assert Post.repository().count() == 0


def test_crud_end_to_end(db):
    seed(db)
    repo = User.repository()

    # count / exists
    assert repo.count() == 2
    assert repo.exists(email="bob@example.com") is True
    assert repo.exists(email="nobody@example.com") is False

    # find (hydration + type coercion)
    alice = repo.find(1)
    assert isinstance(alice, User)
    assert alice.name == "Alice"
    assert alice.email == "alice@example.com"
    assert alice.active is True
    assert alice.age == 30

    # where (composable, parameterized)
    active = repo.where("active", True).order_by("id").get()
    assert [u.name for u in active] == ["Alice"]
    adults = repo.where("age", 25, ">=").order_by("id").get()
    assert [u.name for u in adults] == ["Alice", "Bob"]

    # update
    assert repo.update(2, {"name": "Bobby", "active": True}) == 1
    bob = repo.find(2)
    assert bob.name == "Bobby"
    assert bob.active is True

    # model instance save()
    alice.name = "Alicia"
    alice.save()
    assert repo.find(1).name == "Alicia"

    # delete
    assert repo.delete(2) == 1
    assert repo.find(2) is None
    assert repo.count() == 1


def test_first_and_not_found(db):
    seed(db)
    assert User.repository().find(999) is None
    assert User.repository().find_or_fail(1).name == "Alice"


def test_compiler_to_real_database(db):
    seed(db)
    compiler = QueryCompiler(db.dialect)
    compiled = compiler.compile_select(
        table="users",
        columns=["id", "name"],
        wheres=[{"column": "active", "operator": "=", "value": True}],
        order_by=[("id", "asc")],
    )
    # identifiers are quoted by the dialect; values are bound parameters
    assert '"users"' in compiled.sql
    assert compiled.parameters == (True,)
    result = execute_compiled(db.manager, compiled)
    assert [row["name"] for row in result["rows"]] == ["Alice"]


def test_migration_applies_schema_on_real_database(db):
    """The Migration abstraction drives real schema changes (no new engine)."""

    class CreateMigratedTable(Migration):
        def __init__(self) -> None:
            super().__init__("0001_create_migrated", 1, "create migrated table")

        def up(self, database: DatabaseManager) -> None:
            quote = db.dialect.quote_identifier
            database.execute(
                f"CREATE TABLE {quote('migrated')} ("
                f"{quote('id')} {db.dialect.type_name(int)} PRIMARY KEY, "
                f"{quote('label')} {db.dialect.type_name(str)})"
            )

        def down(self, database: DatabaseManager) -> None:
            database.execute(f"DROP TABLE {db.dialect.quote_identifier('migrated')}")

    registry = MigrationRegistry()
    registry.register(CreateMigratedTable())
    assert [m.name for m in registry.ordered()] == ["0001_create_migrated"]

    for migration in registry.ordered():
        migration.up(db.manager)

    # the migrated table is a real table the Query Builder can use at once
    Query("migrated", database=db.manager).insert({"id": 1, "label": "ok"})
    assert Query("migrated", database=db.manager).get()[0]["label"] == "ok"

    for migration in reversed(registry.ordered()):
        migration.down(db.manager)
    with pytest.raises(DatabaseError):
        Query("migrated", database=db.manager).get()


# ---------------------------------------------------------------------------
# 3. Relationships
# ---------------------------------------------------------------------------


def test_has_many_and_belongs_to(db):
    seed(db)
    alice = User.repository().find(1)
    posts = alice.posts().order_by("id").get()
    assert [p.title for p in posts] == ["First", "Second"]
    assert all(isinstance(p, Post) for p in posts)

    published = alice.posts().where("published", True).get()
    assert [p.title for p in published] == ["First"]

    first = Post.repository().find(1)
    author = first.author().first()
    assert author is not None
    assert author.name == "Alice"

    # a row with no related parent yields an empty (predictable) query
    orphan = Post.create(id=99, title="Orphan", author_id=None)
    assert orphan.author().first() is None


def test_many_to_many(db):
    seed(db)
    Product.create(id=1, sku="P1")
    Category.create(id=1, name="Tools")
    Category.create(id=2, name="Hardware")
    pivot = Query("products_categories", database=db.manager)
    pivot.insert({"product_id": 1, "category_id": 1})
    pivot.insert({"product_id": 1, "category_id": 2})
    db.connection().commit()

    product = Product.repository().find(1)
    assert product is not None
    names = [c.name for c in product.categories().order_by("id").get()]
    assert names == ["Tools", "Hardware"]

    # a product with no pivot rows yields an empty result
    Product.create(id=2, sku="P2")
    assert Product.repository().find(2).categories().get() == []


# ---------------------------------------------------------------------------
# 4. Serialization / hydration / metadata
# ---------------------------------------------------------------------------


def test_serialization_and_hydration(db):
    seed(db)
    alice = User.repository().find(1)
    assert alice.to_dict() == {
        "id": 1,
        "name": "Alice",
        "email": "alice@example.com",
        "active": True,
        "age": 30,
    }
    assert alice.to_jsonable() == alice.to_dict()

    # hydration from a partial select
    partial = User.query().select("id", "name").where("id", 1).first()
    assert partial.name == "Alice"
    assert partial.email is None


def test_model_metadata(db):
    meta = User.meta()
    assert meta["type"] == "orm_model"
    assert meta["table"] == "users"
    assert meta["primary_key"] == "id"
    relationships = {r["name"]: r for r in meta["relationships"]}
    assert relationships["posts"]["type"] == "has_many"
    assert relationships["posts"]["target"] == "Post"


# ---------------------------------------------------------------------------
# 5. Transactions (commit / rollback on a real database)
# ---------------------------------------------------------------------------


def test_transaction_commit_is_durable(db):
    with db.engine.transaction():
        User.create(id=900, name="Committed", email="c@example.com")
    # reopen the same file: the committed row survived the connection closing
    db.close()
    reopened = db.reopen()
    try:
        found = User.repository().find(900)
        assert found is not None and found.name == "Committed"
    finally:
        reopened.close()


def test_transaction_rollback_on_exception(db):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with db.engine.transaction():
            User.create(id=901, name="Rolled back", email="r@example.com")
            assert User.repository().count() == 1
            raise Boom("original exception must be re-raised")

    # the insert was rolled back and never became durable
    db.close()
    reopened = db.reopen()
    try:
        assert User.repository().find(901) is None
    finally:
        reopened.close()


def test_transaction_state_lifecycle(db):
    transaction = db.engine.transaction()
    with transaction:
        User.create(id=902, name="Stateful")
    assert transaction.state.value == "committed"
    assert transaction.is_active is False


# ---------------------------------------------------------------------------
# 6. Parameterization & safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", DIRTY_VALUES)
def test_special_values_are_bound_not_interpolated(db, value):
    seed(db)
    User.create(id=50, name=value, email="dirty@example.com")
    found = User.repository().where("name", value).first()
    assert found is not None, f"value did not round-trip: {value!r}"
    assert found.name == value
    # the table is intact (no injection executed)
    assert User.repository().count() == 3


def test_compiled_sql_never_contains_values(db):
    seed(db)
    dirty = "O'Brien; DROP TABLE users; -- 😀"
    compiled = Query("users", database=db.manager).where("name", dirty).compile()
    assert dirty not in compiled.sql
    assert "?" in compiled.sql
    assert dirty in compiled.parameters


def test_update_and_delete_require_where_clause(db):
    seed(db)
    with pytest.raises(QueryError):
        Query("users", database=db.manager).update({"name": "Nope"})
    with pytest.raises(QueryError):
        Query("users", database=db.manager).delete()
    # nothing was modified
    assert User.repository().count() == 2


# ---------------------------------------------------------------------------
# 7. Diagnostics / errors
# ---------------------------------------------------------------------------


def test_query_error_is_structured_with_original_cause(db):
    with pytest.raises(DatabaseError) as excinfo:
        db.execute('SELECT * FROM "definitely_missing_table"')
    error = excinfo.value
    assert error.code.startswith("DATABASE")
    assert error.context.get("driver") == db.kind
    assert error.context.get("operation") == "select"
    assert error.cause is not None
    # the concrete driver error is preserved as the cause
    assert "missing_table" in str(error.cause) or "missing_table" in str(error)


def test_sqlite_connection_failure_is_structured(tmp_path):
    engine = SQLiteEngine(
        "default",
        {"driver": "sqlite", "database": str(tmp_path / "missing_dir" / "x.db")},
    )
    manager = DatabaseManager(engine)
    with pytest.raises(ConnectionError) as excinfo:
        manager.connect()
    error = excinfo.value
    assert error.context.get("driver") == "sqlite"
    assert error.cause is not None


# ---------------------------------------------------------------------------
# 8. Auto increment (handled by the dialect, on a real database)
# ---------------------------------------------------------------------------


def test_sqlite_orm_auto_increment(tmp_path):
    """ORM ``create()`` without a pk -> SQLite assigns it via AUTOINCREMENT."""
    database = Database("sqlite", tmp_path / "auto.db")
    try:
        dialect = database.dialect
        quote = dialect.quote_identifier
        database.execute(
            f"CREATE TABLE {quote('notes')} ("
            f"{quote('id')} {dialect.auto_increment()}, "
            f"{quote('body')} {dialect.type_name(str)})"
        )
        first = Note.create(body="first")
        second = Note.create(body="second")
        assert first.id == 1
        assert second.id == 2
        assert Note.repository().find(1).body == "first"
        database.connection().commit()
    finally:
        database.close()

    reopened = database.reopen()
    try:
        assert Note.repository().count() == 2
    finally:
        reopened.close()


@pytest.mark.skipif(not duckdb_available(), reason="optional duckdb driver not installed")
def test_duckdb_sequence_auto_increment(tmp_path):
    """DuckDB auto increment via the dialect's sequence-backed fragment."""
    database = Database("duckdb", tmp_path / "auto.duckdb")
    try:
        dialect = database.dialect
        quote = dialect.quote_identifier
        sequence = dialect.sequence_name("notes", "id")
        database.execute(dialect.compile_fragment("create_sequence", table="notes", column="id"))
        database.execute(
            f"CREATE TABLE {quote('notes')} ("
            f"{quote('id')} "
            f"{dialect.compile_fragment('auto_increment', table='notes', column='id')}, "
            f"{quote('body')} {dialect.type_name(str)})"
        )
        first = Query("notes", database=database.manager).insert({"body": "first"})
        assert first["affected"] == 1
        Query("notes", database=database.manager).insert({"body": "second"})
        rows = Query("notes", database=database.manager).order_by("id").get()
        assert [row["id"] for row in rows] == [1, 2]
        assert [row["body"] for row in rows] == ["first", "second"]
        database.connection().commit()
        assert sequence == "notes_id_seq"
    finally:
        database.close()


# ---------------------------------------------------------------------------
# 9. SQLDialect surface (unit, both dialects)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dialect_cls", [SQLiteDialect, DuckDBDialect])
def test_dialect_surface(dialect_cls):
    dialect = dialect_cls()
    assert dialect.quote_identifier("users") == '"users"'
    assert dialect.quote_identifier('we"ird') == '"we""ird"'
    assert dialect.placeholder() == "?"
    assert dialect.type_name(int) == "INTEGER"
    assert dialect.type_name(str) in ("TEXT", "VARCHAR")
    assert dialect.auto_increment()
    features = dialect.features()
    assert features["supports_transactions"] is True
    assert features["supports_boolean"] is True


def test_dialect_boolean_difference():
    assert SQLiteDialect().boolean_value(True) == "1"
    assert SQLiteDialect().boolean_value(False) == "0"
    assert DuckDBDialect().boolean_value(True) == "TRUE"
    assert DuckDBDialect().boolean_value(False) == "FALSE"


def test_dialect_type_naming_difference():
    assert SQLiteDialect().type_name(str) == "TEXT"
    assert DuckDBDialect().type_name(str) == "VARCHAR"
    assert DuckDBDialect().type_name(bool) == "BOOLEAN"


def test_duckdb_auto_increment_is_sequence_backed():
    dialect = DuckDBDialect()
    fragment = dialect.compile_fragment("auto_increment", table="users", column="id")
    assert "nextval('users_id_seq')" in fragment
    assert dialect.sequence_name("users") == "users_id_seq"
    assert "CREATE SEQUENCE" in dialect.compile_fragment(
        "create_sequence", table="users", column="id"
    )
    assert dialect.features()["auto_increment"] == "sequence"


# ---------------------------------------------------------------------------
# 10. Environment report (never hide a limitation as a pass)
# ---------------------------------------------------------------------------


def test_engine_availability_report():
    assert "sqlite" in ENGINE_KINDS
    if duckdb_available():
        assert "duckdb" in ENGINE_KINDS
        assert isinstance(DuckDBEngine("default", {}), DuckDBEngine)
    else:  # pragma: no cover - depends on environment
        assert "duckdb" not in ENGINE_KINDS
        pytest.skip("optional duckdb driver not installed (SQLite still covered)")
