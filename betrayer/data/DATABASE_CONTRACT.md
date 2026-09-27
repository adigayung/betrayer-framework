# Betrayer Database Contract (Stage 09.1)

Database abstraction for Betrayer. Betrayer **tidak memilih database** —
ia mendefinisikan *contract*. Engine/driver konkret (SQLite, PostgreSQL,
DuckDB, ...) didaftarkan lewat extension point dan diresolusi dari
konfigurasi yang ada (betrayer/core/config.py).

LLM tidak perlu membaca source implementation yang memakai contract ini.
Cukup baca dokumen ini + `betrayer/data/database.py` (contract) dan
`betrayer/data/registry.py` (registry).

## Capability surface

| Capability       | Path                                    | Purpose                                        |
|------------------|-----------------------------------------|------------------------------------------------|
| database         | `betrayer.data.DatabaseRegistry`        | Multi-connection engine registry + resolver    |
| database.engine  | `betrayer.data.DatabaseEngine`          | Kontrak engine: connect/transaction/dialect    |
| database.connection | `betrayer.data.Connection`           | Kontrak koneksi: execute/executemany/...       |
| database.transaction | `betrayer.data.Transaction`         | Transaction context manager                    |
| database.registry | `betrayer.data.registry`              | Registry implementations                       |
| database.configuration | `Config["database.<name>"]`       | Driver + options per connection                |
| database.dialect | `betrayer.data.SQLDialect`              | Perilaku SQL spesifik database (extension point)|
| database.errors  | `betrayer.data.exceptions`              | Error boundary (original cause dipertahankan)  |
| database.engines | `betrayer.data.engines`                 | Concrete adapters (sqlite, duckdb) + register  |

## Interaction

```text
Requirement
    ↓
Discover database capability (dokumen ini / introspection)
    ↓
Read contract
    ↓
Use canonical API
    ↓
Structured result/error
```

## Usage (canonical)

```python
from betrayer.data import DatabaseRegistry, DatabaseManager
from betrayer.core.config import Config

config = Config({
    "database.default.driver": "memory",          # driver = implementation id
    "database.default.database": "app.db",
    "database.analytics.driver": "memory",
})

registry = DatabaseRegistry(config)
registry.register_engine("memory", InMemoryEngine)   # concrete engine (test/fake di sini)

# Resolve engine per connection name
engine = registry.engine("default")                  # <InMemoryEngine>
with engine.connect() as conn:
    conn.execute("INSERT INTO t VALUES (?)", [1])
    conn.commit()

# Transaction (commit on success, rollback+re-raise on failure)
with engine.transaction():
    engine.connect().execute("INSERT INTO t VALUES (?)", [2])

# Manager (backward-compatible single-engine wrapper)
mgr = DatabaseManager(engine)
mgr.connect()
mgr.execute("SELECT ?", [1])
```

Tidak ada koneksi yang dipilih Betrayer secara default: aplikasi/LLM yang
memilih engine mana yang didaftarkan untuk driver id mana.

## Contract detail

### DatabaseEngine (betrayer.data.database.DatabaseEngine)

Tingkat *capability* database:

```python
class DatabaseEngine(ABC):
    def connect(self, name=None, **options) -> Connection: ...
    def transaction(self, connection=None, **options) -> Transaction: ...
    def dialect(self) -> SQLDialect: ...
    def close(self) -> None: ...
    def metadata(self) -> dict: ...
    def introspect(self) -> dict: ...
```

### Connection (betrayer.data.database.Connection)

Boundary antara Betrayer dan driver. Parameterized execution selalu
memisahkan SQL dan parameter:

```python
class Connection(ABC):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def execute(self, query, parameters=None) -> Any: ...
    def executemany(self, query, parameters: Iterable) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def cursor(self) -> Any: ...
```

### Transaction (betrayer.data.transaction.Transaction)

```text
enter -> BEGIN -> operations -> success -> COMMIT
                            \-> exception -> ROLLBACK -> re-raise original
```

Tidak pernah menelan exception. Lifecycle deterministik:
`CREATED → ACTIVE → COMMITTED | ROLLED_BACK | FAILED`.

```python
with db.transaction():
    ...
```

### SQLDialect (betrayer.data.database.SQLDialect)

Extension point untuk perilaku SQL spesifik database:

```python
quote_identifier(identifier) -> str
placeholder(position=None)   -> str
boolean_value(value)         -> str
auto_increment()             -> str
type_name(python_type)       -> str
features() -> dict
compile_fragment(feature, **kwargs) -> str
```

Digunakan oleh Query Builder pada Stage 09.2.

### DatabaseRegistry (betrayer.data.registry.DatabaseRegistry)

```python
registry = DatabaseRegistry(config)
registry.register_engine("custom", CustomEngine)   # extension point
engine = registry.engine("default")                # resolve by name
engine = registry.engine("analytics")
registry.names()           # connection names dari config
registry.introspect()      # LLM-readable, secrets tidak pernah bocor
```

Resolusi: `Configuration -> Registry -> Registered Implementation`.
Core framework tidak pernah hardcode `if driver == "sqlite"`.

### Configuration (existing `core/config.py`)

```python
DATABASE = {
    "default": {"driver": "...", "database": "...", ...},
    "analytics": {"driver": "...", "database": "...", ...},
}
```

`"driver"` adalah **implementation identifier** — bukan database yang
diwajibkan Betrayer. Kredensial di-mask oleh Config (`safe_data()`).

### Error contract (betrayer.data.exceptions)

```text
BetrayerError
  └─ DataError
       └─ DatabaseError
            ├─ ConnectionError
            ├─ TransactionError
            ├─ DatabaseConfigurationError
            └─ UnsupportedDatabaseError
```

Setiap error:
- mempertahankan original exception di `cause`
- boleh membawa `operation`/`driver`/`database` di `context`
- **tidak pernah** memuat password/API key/credential/secret

## Concrete adapters (Stage 09.4)

Engine konkret **tidak** ada di core (`betrayer.data.database` tetap abstrak).
Engine konkret berada di subpackage terisolasi `betrayer.data.engines` dan
didaftarkan lewat extension point yang sama dengan engine lain.

| Adapter          | Driver id  | Dependency                                  |
|------------------|------------|---------------------------------------------|
| `SQLiteEngine`   | `"sqlite"` | standard library `sqlite3` (selalu tersedia)|
| `DuckDBEngine`   | `"duckdb"` | optional `duckdb` (di-import lazily)        |

```python
from betrayer.core.config import Config
from betrayer.data import DatabaseRegistry, DatabaseManager
from betrayer.data.engines import register_builtin_engines

config = Config({
    "database.default.driver": "sqlite",            # implementation id
    "database.default.database": "app.db",
    "database.analytics.driver": "duckdb",          # multi-connection
    "database.analytics.database": ":memory:",
})
registry = DatabaseRegistry(config)
register_builtin_engines(registry)                  # extension point

engine  = registry.engine("default")                # SQLiteEngine
manager = DatabaseManager(engine)
manager.connect()

# E2E: schema -> ORM -> Repository -> Query -> database (tanpa SQL manual)
engine.connect().execute(
    'CREATE TABLE "users" ("id" INTEGER PRIMARY KEY, "name" TEXT, "active" INTEGER)'
)
from betrayer.data import ORMModel, ORMField

class User(ORMModel):
    __table__ = "users"
    __connection__ = manager
    id = ORMField(int, primary_key=True)
    name = ORMField(str, required=True)
    active = ORMField(bool, default=True)

user = User.repository().create(id=1, name="John")
assert User.repository().find(1).name == "John"
```

### Result shape (Connection contract)

Setiap adaptor mengembalikan mapping stabil yang dikonsumsi Query Builder:

* `SELECT`  -> `{"rows": [ {col: value, ...} ], "columns": [...]}`
* write    -> `{"affected": int, "lastrowid": int | None}`

### Perbedaan dialect yang ditangani

Perbedaan antar database **hanya** hidup di `SQLDialect` (bukan di ORM,
Repository, atau Query Builder):

| Fitur            | `SQLiteDialect`                     | `DuckDBDialect`                          |
|------------------|-------------------------------------|------------------------------------------|
| identifier       | `"col"`                             | `"col"`                                  |
| placeholder      | `?`                                 | `?`                                      |
| boolean          | `1` / `0`                           | `TRUE` / `FALSE`                         |
| auto increment   | `INTEGER PRIMARY KEY AUTOINCREMENT` | sequence-backed `DEFAULT nextval(...)`   |
| `str` / `float`  | `TEXT` / `REAL`                     | `VARCHAR` / `DOUBLE`                     |

DuckDB tidak punya kata kunci `AUTOINCREMENT` inline; auto increment
diungkapkan sebagai `DEFAULT` berbasis sequence lewat
`dialect.compile_fragment("auto_increment", table=..., column=...)`
(nama sequence: `dialect.sequence_name(table, column)`).

### Keamanan & error

* Semua value selalu di-bind parameter (`?`) — tidak pernah diinterpolasi.
  Nilai dengan quote/unicode/karakter SQL tidak mengubah struktur query.
* Error concrete database memakai hierarchy yang sama (`DatabaseError` dst.),
  terstruktur, deterministik, mempertahankan `cause` asli, dan tidak memuat
  password/token/secret.
* Dependency driver bersifat **optional** dan terisolasi di adapter: `duckdb`
  di-import lazily; jika tidak terpasang, connect melempar
  `UnsupportedDatabaseError` dan framework tetap import bersih.

## Next

- Stage 09.2 — Query Builder & ORM: **sudah tersedia**, lihat
  `betrayer/data/ORM_CONTRACT.md` (atau `betrayer.data.ORMModel` /
  `betrayer.data.Query` / `betrayer.data.QueryCompiler`).
- Stage 09.3 — Repository & Relationships: **sudah tersedia**, lihat
  `betrayer/data/REPOSITORY_CONTRACT.md` (atau `betrayer.data.BaseRepository`
  / relationship helpers `BelongsTo`, `HasOne`, `HasMany`, `ManyToMany`).
- Stage 09.4 — Concrete database integration + E2E: **sudah tersedia**, lihat
  `betrayer/data/engines/` dan `tests/test_database_e2e.py`.

## JANGAN

- Jangan menambahkan concrete database engine ke **core** (`betrayer.data`).
  Engine konkret hanya di `betrayer.data.engines` (terisolasi, optional deps).
- Jangan menambah protocol/network driver sendiri.
- Query Builder / ORM / Repository tidak boleh menambah pengetahuan database
  tertentu (tidak ada `if driver == "sqlite"` di luar `engines/`).