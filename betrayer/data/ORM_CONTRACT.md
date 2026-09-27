# Betrayer ORM Contract (Stage 09.2)

Query Builder & ORM abstraction for Betrayer, built on the Stage 09.1
database contract (``DatabaseEngine`` / ``Connection`` / ``SQLDialect``).
Betrayer tetap **database-agnostic**: semua perilaku SQL spesifik database
(quoting identifier, placeholder, tipe kolom) didelegasikan ke
`SQLDialect`, dan **tidak ada** branch `if database == "sqlite"/"postgres"/...`
di Query Builder / ORM / compiler.

LLM TIDAK PERLU membaca `query_builder.py`, `compiler.py`, `orm.py`,
`database.py`, atau `dialect.py` untuk memakai ORM ini. Cukup dokumen ini.

## Pipeline

```text
LLM / Application
    ↓
ORM Model API        (betrayer.data.ORMModel / ORMField)
    ↓
Query Builder        (betrayer.data.Query)
    ↓
SQL Compiler         (betrayer.data.QueryCompiler -> CompiledQuery)
    ↓
SQLDialect           (quoting / placeholder / type mapping)
    ↓
DatabaseEngine / Connection   (execute(sql, parameters))
    ↓
Concrete adapter     (disediakan di luar core / extension point)
```

## Capability surface

| Capability      | Path                                   | Purpose                            |
|-----------------|----------------------------------------|------------------------------------|
| orm.model       | `betrayer.data.ORMModel`               | Model ORM declarative              |
| orm.field       | `betrayer.data.ORMField`               | Definisi kolom                     |
| query           | `betrayer.data.Query`                  | Query builder immutable            |
| query.compiler  | `betrayer.data.QueryCompiler`          | Compile Query -> (sql, parameters) |
| query.compiled  | `betrayer.data.CompiledQuery`          | Kontrak hasil kompilasi            |
| value.mapper    | `betrayer.data.ValueMapper`            | Mapping Python ↔ database value    |
| orm.metadata    | `Model.meta()` / `Model.introspect()`  | Metadata model tanpa baca source   |
| errors          | `betrayer.data.exceptions`             | `QueryError`, `ModelError`, `DatabaseError` |

Semua simbol di atas importable langsung dari `betrayer.data`.

## 1. Mendefinisikan Model

```python
from betrayer.data import ORMModel, ORMField
from datetime import datetime

class User(ORMModel):
    __table__ = "users"              # opsional; default: snake_case plural
    __connection__ = manager         # DatabaseManager | DatabaseEngine | callable -> Connection

    id = ORMField(int, primary_key=True, nullable=False)
    name = ORMField(str, required=True, nullable=False)
    email = ORMField(str, nullable=False)
    active = ORMField(bool, default=True)
    age = ORMField(int, nullable=True)
    created_at = ORMField(datetime, nullable=True)
```

Aturan singkat:

- `__table__` default: `UserProfile` -> `user_profiles`.
- `__primary_key__` default: field `primary_key=True`, fallback `"id"`.
- `ORMField(type_, *, primary_key, required, default, nullable, unique,
  indexed, description)`.
- Wajib pasang `__connection__` sebelum query; tanpa itu `Model.query()`
  melempar `QueryError` (stage `init`).

## 2. Query (canonical API)

```python
user = User.query().where("email", email).first()
users = User.query().where("active", True).get()
users = User.query().order_by("created_at", "desc").limit(10).get()
exists = User.query().where("email", email).exists()
count = User.query().where("active", True).count()
first = User.query().order_by("id", "asc").first()   # None bila kosong
```

Modifier (semua **immutable** — mengembalikan Query baru):

| Method                | Efek                                   |
|-----------------------|----------------------------------------|
| `select(*cols)`       | Pilih kolom tertentu                   |
| `where(col, val)`     | `col = val` (AND); `val=None` -> `IS NULL` |
| `where(col, val, op)` | op: `= != > >= < <= like`             |
| `where_in(col, vals)` | `col IN (?, ?, ...)` — wajib non-kosong |
| `where_null(col)`     | `col IS NULL`                          |
| `where_not_null(col)` | `col IS NOT NULL`                      |
| `order_by(col, dir)`  | `dir` = `asc` / `desc` (append)        |
| `limit(n)` / `offset(n)` | pagination                          |

Terminal (SELECT): `get()/all()`, `first()`, `count()`, `exists()`.
Terminal (WRITE): `insert(dict)`, `update(dict)`, `delete()`.

### Standalone Query (tanpa Model, hasil = row dict)

```python
from betrayer.data import Query

rows = Query("users", database=manager).where("active", True).get()
Query("users", database=manager).insert({"name": "John"})
Query("users", database=manager).where("id", 1).update({"name": "Jane"})
Query("users", database=manager).where("id", 1).delete()
```

`get()` mengembalikan list of dict (bila driver mengembalikan rows) atau
list of mappings bila dikompilasi dengan kolom eksplisit.

## 3. Create / Update / Delete (Model CRUD)

```python
user = User.create(name="John", email="john@example.com")   # insert + hydrate + pk
user.name = "Jane"
user.save()            # pk set -> update; pk None -> insert
user.delete()          # hapus berdasar pk
user.refresh()         # reload dari database (ModelError bila row hilang)
```

Catatan:

- `create` memvalidasi field `required`; melanggar -> `ModelError`.
- `update`/`delete` **menolak** berjalan tanpa `where` (safety contract,
  `QueryError`) — tidak ada full-table update/delete yang tidak disengaja.
- `save()` pada instance tanpa pk berperilaku seperti `create`.

## 4. Serialization

```python
user.to_dict()          # {"name": ..., "email": ...} — field dict biasa
user.to_jsonable()      # datetime/Decimal -> isoformat/str, siap JSON
User.from_dict({...})   # build instance dari dict
```

## 5. Metadata (tanpa baca source)

```python
meta = User.meta()
# {
#   "type": "orm_model",
#   "name": "User",
#   "module": "...",
#   "table": "users",
#   "primary_key": "id",
#   "fields": [{"name", "type", "primary_key", "required", "nullable",
#               "default", "unique", "indexed", "description"}, ...],
#   "connection": {...introspect aman...},
# }
User.table_name()        # -> "users"
User.primary_key_name()  # -> "id"
User.orm_fields()        # -> {"id": ORMField, ...}
```

## 6. Type / Value mapping

```python
from betrayer.data import ValueMapper

mapper = ValueMapper(int)
mapper.to_database(5)        # 5           (bind value, bukan SQL)
mapper.from_database("42")   # 42          (coerce saat hydration)
mapper.type_name             # "int"
```

Didukung: `str int float bool datetime date Decimal bytes` + `None`.
Konversi gagal -> `ModelError` (stage `hydrate`/`validate`).
Tipe kolom SQL (`INTEGER`, `TEXT`, ...) tetap datang dari `SQLDialect.type_name`
— core tidak menetapkan type mapping untuk database tertentu.

## 7. Transaction

Pakai `Transaction` Task 09.1 apa adanya:

```python
with manager.transaction():
    User.create(name="A", email="a@x.com")
    User.create(name="B", email="b@x.com")
    # commit otomatis; exception -> rollback + re-raise
```

`User.query()`, `User.create()`, dll. memakai connection manager yang sama,
jadi berada dalam scope transaction tersebut (commit/rollback terpusat).

## 8. Error contract

Hierarki (kelanjutan Task 09.1):

```text
BetrayerError -> DataError
                 ├─ DatabaseError      # eksekusi driver gagal (stage=execute)
                 ├─ ConnectionError    # koneksi bermasalah
                 ├─ TransactionError   # commit/rollback
                 ├─ QueryError         # konstruksi/kompilasi query invalid
                 ├─ ModelError         # definisi/validasi/hydration model
                 └─ ...
```

- `QueryError` untuk: operator tidak dikenal, where column kosong,
  `where_in` kosong, arah order invalid, update/delete tanpa where,
  insert/update tanpa nilai, model tanpa `__connection__`.
- `DatabaseError` untuk error eksekusi; membawa `operation`, `table`,
  `driver` di context.
- **Tidak pernah** membocorkan password / connection string / secret.
  Traceback tidak disajikan sebagai response API (tetap `BetrayerError`).

## 9. Didukung / Tidak didukung

Didukung (task ini):

- select / where / where_in / where_null / where_not_null / order_by /
  limit / offset / first / get / all / count / exists
- insert / update / delete (parameterized, dengan safety where)
- ORM define table/pk/fields, query, hydration, serialization,
  create/update/delete, refresh
- metadata model, value mapping, error contract
- execution lewat DatabaseManager, DatabaseEngine, atau callable
  (provider Connection) — semuanya memakai `Connection.execute(query, parameters)`

TIDAK didukung (di luar scope, jangan diekspektasikan):

- SQLAlchemy / Django / Eloquent feature parity
- Joins / group by / having / raw SQL (relationship metadata & akses dasar
  tersedia sejak Stage 09.3 — lihat `REPOSITORY_CONTRACT.md`)
- ORM-level `or_where`
- Aggregates selain `count`/`exists`
- Query caching, eager loading, lazy loading
- DDL / schema ops (pakai migration system)
- Query Builder tidak berjalan tanpa koneksi/engine/dialect valid

## 10. JANGAN pada task ini

- Tidak ada concrete database dependency di core ORM.
- Tidak ada branch SQLite/PostgreSQL/MySQL di Query Builder / ORM /
  compiler.
- Tidak membuat driver database baru.
- Tidak mengubah kontrak Task 09.1 (`DatabaseEngine`, `Connection`,
  `Transaction`, `SQLDialect`, `DatabaseRegistry`, `DatabaseManager`,
  migration system tetap utuh).
- Nilai user tidak pernah di-interpolasi ke SQL (selalu parameter).

## Next

- Stage 09.3 — Repository & Relationships (`BaseRepository`, `BelongsTo`,
  `HasOne`, `HasMany`, `ManyToMany`) — lihat `REPOSITORY_CONTRACT.md`.
- Stage 09.4 — Database Integration / E2E dengan concrete engine.