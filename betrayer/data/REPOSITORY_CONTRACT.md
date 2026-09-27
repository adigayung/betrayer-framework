# Betrayer Repository & Relationships Contract (Stage 09.3)

Canonical Repository layer + relationship contract for Betrayer, built on
Stage 09.2 (`Query` / `ORMModel`) and Stage 09.1 (`DatabaseEngine` /
`Connection` / `SQLDialect`). Betrayer tetap **database-agnostic**: tidak ada
branch `if database == "sqlite"/"postgres"/...` di Repository maupun
relationship.

LLM TIDAK PERLU membaca `base_repository.py`, `relationships.py`, `query.py`,
`orm.py`, atau `compiler.py` untuk memakai Repository & relationships. Cukup
dokumen ini.

## Pipeline

```text
Service
    ↓
Repository            (betrayer.data.BaseRepository)
    ↓
ORM Model / Query      (betrayer.data.ORMModel / Query)
    ↓
Query Builder          (betrayer.data.Query)
    ↓
SQL Compiler           (QueryCompiler -> CompiledQuery)
    ↓
SQLDialect             (quoting / placeholder)
    ↓
DatabaseEngine / Connection   (execute(sql, parameters))
```

Repository **tidak** menulis SQL dan **tidak** menyentuh dialect; ia hanya
memakai `Query`/`ORMModel` yang sudah ada (tidak menduplikasi query builder).

## Capability surface

| Capability            | Path                                        | Purpose                                   |
|-----------------------|---------------------------------------------|-------------------------------------------|
| repository            | `betrayer.data.BaseRepository`              | Repository CRUD canonical atas ORM model  |
| repository.metadata   | `BaseRepository.introspect()`               | Metadata repository (model, pk, relasi)   |
| model.repository      | `ORMModel.repository()`                     | Repository default/canonical per model    |
| relationship          | `betrayer.data.Relationship` (+ helpers)    | Deklarasi relasi antar model              |
| relationship.belongs_to | `betrayer.data.BelongsTo`                 | FK di owner → target                      |
| relationship.has_one  | `betrayer.data.HasOne`                      | target FK → owner (satu baris)            |
| relationship.has_many | `betrayer.data.HasMany`                     | target FK → owner (banyak baris)          |
| relationship.many_to_many | `betrayer.data.ManyToMany`              | via pivot table                           |
| relationship.metadata | `ORMModel.meta()["relationships"]`          | Metadata relasi tanpa baca source         |
| errors                | `betrayer.data.exceptions`                  | `RepositoryError`, `ModelError`           |

Semua simbol di atas importable langsung dari `betrayer.data`.

## 1. Kapan menggunakan Repository

- Gunakan **Repository** sebagai satu-satunya pintu akses data dari Service;
  handler/service **jangan** menulis SQL atau memakai `Query` mentah kecuali
  butuh komposisi lanjutan.
- Gunakan **Repository** untuk CRUD + query sederhana (find/all/where/count/
  exists). Untuk komposisi kompleks (multi-where/order/limit), `where(...)`
  mengembalikan `Query` yang bisa dirantai.
- Selalu instantiate dengan **model ORM eksplisit**: `BaseRepository(User)`.

## 2. API Repository (canonical)

```python
from betrayer.data import BaseRepository

class UserRepository(BaseRepository[User]):
    def active(self):                     # method tambahan (opsional)
        return self.where("active", True).get()

repo = UserRepository(User)               # model diberikan eksplisit

# READ
user  = repo.find(1)                      # User | None (primary key)
user  = repo.find_or_fail(1)              # User atau RepositoryError
users = repo.all()                        # list[User]
q     = repo.where("active", True)        # Query (bisa dirantai)
users = repo.where("active", True).order_by("id", "desc").get()
n     = repo.count()                      # int
ok    = repo.exists(email="a@b.c")        # bool (tanpa filter = ada baris?)

# WRITE
user = repo.create(name="John", email="john@example.com")   # -> instance (pk terisi)
rows = repo.update(1, {"name": "Jane"})   # -> int (jumlah baris berubah)
rows = repo.delete(1)                     # -> int (jumlah baris terhapus)

# METADATA
repo.introspect()
# {"type": "repository", "name": "UserRepository", "model": "User",
#  "table": "users", "primary_key": "id", "relationships": [ ... ]}
```

Aturan:

- `find(id)` / `find_or_fail(id)` / `update(id, ...)` / `delete(id)` memakai
  **primary key** model.
- `update`/`delete` **selalu** menyertakan `where` primary key — kontrak
  keamanan 09.2 (tidak ada full-table update/delete). Identifier `None` →
  `RepositoryError`.
- `create` memvalidasi field `required` (melanggar → `ModelError`).
- Repository **tidak** mengandung branching database-specific.

## 3. Model ↔ Repository

Setiap `ORMModel` punya repository default tanpa wiring tambahan:

```python
repo = User.repository()                  # BaseRepository(User)
```

Atau pasang repository khusus:

```python
class UserRepository(BaseRepository[User]):
    pass

class User(ORMModel):
    __table__ = "users"
    __repository__ = UserRepository       # class (atau instance)

User.repository()                         # -> UserRepository(User)
```

Service memakai repository tanpa tahu detail SQL:

```python
class UserService:
    def __init__(self, repository: UserRepository):
        self.repo = repository

    def active_users(self):
        return self.repo.where("active", True).get()
```

> **Backward compatibility**: `betrayer.data.repository.Repository` (repository
> lama bertipe `Model`/`Field` DTO, dipakai `bet bet make crud/resource`) tetap
> dipertahankan apa adanya. `BaseRepository` adalah cara canonical baru untuk
> akses ORM. `betrayer.data.models.Model`/`Field` dan generator Resource/API
> tidak berubah.

## 4. Relationships

Deklarasikan relasi sebagai atribut class, seperti `ORMField`:

```python
from betrayer.data import ORMModel, ORMField, BelongsTo, HasOne, HasMany, ManyToMany

class User(ORMModel):
    __table__ = "users"
    __connection__ = manager
    id = ORMField(int, primary_key=True)
    posts = HasMany("Post")               # pakai nama model (forward ref aman)
    profile = HasOne("Profile")

class Post(ORMModel):
    __table__ = "posts"
    __connection__ = manager
    id = ORMField(int, primary_key=True)
    author_id = ORMField(int)
    author = BelongsTo(User)              # FK default: author_id

class Product(ORMModel):
    __table__ = "products"
    __connection__ = manager
    id = ORMField(int, primary_key=True)
    categories = ManyToMany("Category")   # pivot default: products_categories
```

`target` boleh berupa: **class** model, **string** nama model (di-resolve di
module pemilik, berguna untuk relasi siklik `User.posts` ↔ `Post.author`),
atau **callable** tanpa argumen yang mengembalikan class.

### Tipe relationship

| Tipe          | Cardinality | Default `foreign_key`         | Dipakai untuk                     |
|---------------|-------------|-------------------------------|-----------------------------------|
| `belongs_to`  | one         | `<nama_relasi>_id` (di owner) | Post.author_id → User.id          |
| `has_one`     | one         | `<owner_snake>_id` (di target)| User → Profile.user_id            |
| `has_many`    | many        | `<owner_snake>_id` (di target)| User → Post.user_id              |
| `many_to_many`| many        | via pivot                     | Product ↔ Category (products_categories) |

Override key via parameter: `foreign_key`, `local_key`, `target_key`,
`pivot`, `pivot_local_key`, `pivot_foreign_key`.

### Mengakses relationship (predictable, tanpa lazy-loading)

Akses lewat **instance** mengembalikan accessor kecil; memanggilnya
mengembalikan `Query` yang sudah tersaring ke target:

```python
user.posts().get()                                   # list[Post]
user.posts().where("published", True).get()          # komposisi Query
post.author().first()                                # User | None
user.profile().first()                               # Profile | None
product.categories().get()                           # list[Category]
```

- Akses **class** mengembalikan objek `Relationship` itu sendiri
  (`User.posts`).
- Konsisten: **semua** tipe mengembalikan `Query`; pakai `.first()` untuk
  relasi to-one dan `.get()` untuk to-many.
- Tidak ada eksekusi implisit selain `many_to_many` yang membaca pivot lebih
  dulu lalu mengembalikan `Query` tersaring `where_in`. Relasi kosong
  mengembalikan `Query` kosong yang deterministik (bukan error).
- Tanpa join/raw SQL: `many_to_many` melakukan dua langkah (pivot → `where_in`)
  memakai `Query` yang ada.

## 5. Metadata / introspection

```python
User.meta()
# {
#   "type": "orm_model", "name": "User", "table": "users", "primary_key": "id",
#   "fields": [ ... ],
#   "relationships": [
#     {"name": "posts", "type": "has_many", "target": "Post",
#      "cardinality": "many",
#      "keys": {"foreign_key": "user_id", "local_key": "id"}, "description": ""},
#     {"name": "profile", "type": "has_one", "target": "Profile", ...},
#   ],
#   "connection": { ... },
# }

User.orm_relationships()          # {"posts": Relationship, "profile": ...}
User.relationship("posts")        # Relationship (ModelError bila tidak ada)
User.relationship("posts").to_dict()
```

Repository juga mengekspose relasi model pada `introspect()["relationships"]`.

## 6. Error contract

Kelanjutan hierarchy Task 09.1/09.2:

```text
BetrayerError -> DataError
                 ├─ RepositoryError    # repository: model invalid, not found,
                 │                     # identifier hilang, missing pk
                 ├─ ModelError         # definisi model/relasi, validasi, hydration
                 ├─ QueryError         # konstruksi/kompilasi query invalid
                 ├─ DatabaseError      # eksekusi driver gagal
                 └─ ...
```

- `BaseRepository(<bukan ORM model>)` → `RepositoryError` (stage `init`).
- `find_or_fail` gagal → `RepositoryError` dengan context `model`,
  `primary_key`, `identifier`.
- `update`/`delete` tanpa identifier → `RepositoryError` (safety).
- Tipe relationship tidak dikenal / target bukan model / nama bentrok dengan
  `ORMField` / target string tak ter-resolve → `ModelError`.
- **Tidak pernah** membocorkan password / connection string / secret.
  Nilai user selalu menjadi bind parameter (tidak di-interpolasi ke SQL).

## 7. Didukung / Tidak didukung

Didukung (task ini):

- `BaseRepository`: `find`, `find_or_fail`, `all`, `where`, `create`,
  `update`, `delete`, `count`, `exists`, `query`, `introspect`
- `Model.repository()` (+ `__repository__`), metadata repository
- 4 relationship: `belongs_to`, `has_one`, `has_many`, `many_to_many`
  dengan metadata + akses `Query` yang predictable
- backward compatibility Task 09.1/09.2 + generator Resource/API

TIDAK didukung (di luar scope, jangan diekspektasikan):

- concrete database driver / integrasi SQLite/PostgreSQL/MySQL
- joins, group by, having, raw SQL, eager/lazy loading, caching query
- relationship parity SQLAlchemy/Django/Eloquent (auto migrations, cascade,
  polymorphic, through-models)
- DDL / schema (pakai migration system)

## Next

- Stage 09.4 — Database Integration / E2E dengan concrete engine.
