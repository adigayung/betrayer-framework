# Pagination Contract for LLM Agents

Pagination is the canonical page-based API for collection endpoints in
Betrayer.  Read this to add pagination to any collection `Resource`/`API`
without inventing a second subsystem or a custom envelope.

**Flow (deterministic):**

```text
request (?page=2&per_page=20)
→ parse_pagination(request) → PaginationParams (validated)
→ service pagination (paginate() / list() fallback) or query pagination
→ PaginatedResult(items, PaginationMetadata)
→ collection envelope  {success, data, meta.pagination}
```

---

## 1. Canonical API

Everything imports from one place:

```python
from betrayer.web import (
    PaginationParams,          # immutable, validated
    PaginationMetadata,        # page, per_page, total, total_pages
    PaginatedResult,           # items + metadata
    parse_pagination,          # Request -> PaginationParams (raises 422)
    paginate_sequence,         # in-memory pagination (fallback)
    paginate_query,            # data-layer pagination (Query/Repository)
)
# also re-exported at the top level: from betrayer import PaginationParams, ...
```

### `PaginationParams`

```python
params = PaginationParams(page=2, per_page=20)
params.page       # 2
params.per_page   # 20
params.offset     # (page - 1) * per_page -> 20
params.to_dict()  # {"page": 2, "per_page": 20}
```

* Immutable frozen dataclass.
* Invalid values raise at construction time: `page < 1`,
  `per_page < 1`, `per_page > MAX_PER_PAGE` are programming errors and raise
  `ValueError` / `TypeError`.
* Parse from a request with `parse_pagination(request)`; invalid query
  parameters raise the framework `ValidationError` (422).

### `PaginationMetadata`

```python
meta = PaginationMetadata.from_params(params, total=135)
meta.to_dict()
# {"page": 2, "per_page": 20, "total": 135, "total_pages": 7}
```

* `total_pages` = `ceil(total / per_page)`; **0 when `total == 0`**.

### `PaginatedResult`

```python
result = PaginatedResult(items=[...], metadata=meta)
result.items      # -> the page slice
result.metadata   # -> PaginationMetadata
```

---

## 2. Input & Defaults

| Parameter   | Query key   | Default | Rules                          |
|-------------|-------------|---------|--------------------------------|
| `page`      | `page`      | `1`     | integer, `>= 1`                |
| `per_page`  | `per_page`  | `20`    | integer, `1 <= per_page <= MAX_PER_PAGE` |

`MAX_PER_PAGE = 100` — a client can never request an unbounded page size.
The keys can be renamed at the call site
(`parse_pagination(request, page_key="p", per_page_key="size")`).

---

## 3. Validation / Error Behavior

Invalid parameters produce the **existing** validation error contract:

```python
# page=0, page=-3, per_page=0, per_page=101, page=abc
ValidationError  (422 VALIDATION_FAILED)
  error.details.fields = {"page": ["page must be at least 1."], ...}
```

No new error envelope, no new exception hierarchy.

---

## 4. Output / Response Contract

Pagination rides inside the **existing** Betrayer collection envelope —
`meta.pagination` is the only addition:

```json
{
  "success": true,
  "data": [{}, {}],
  "meta": {
    "resource": "products",
    "count": 2,
    "pagination": {
      "page": 1,
      "per_page": 2,
      "total": 5,
      "total_pages": 3
    }
  }
}
```

---

## 5. Resource Integration

Opt in per resource — unpaginated resources keep their exact previous
behavior:

```python
from betrayer.web import CrudApiResource

class ProductResource(CrudApiResource):
    name = "products"
    prefix = "/api"
    pagination = True          # GET /api/products?page=2&per_page=20
```

The collection handler (`GET {base}`):

1. parses + validates `page` / `per_page` (422 on invalid values);
2. asks the service for one page (see below);
3. returns `data` + `meta.pagination`.

Custom collection endpoints can use the helper directly:

```python
class ReportsResource(ApiResource):
    def endpoints(self):
        return [("GET", "", self.list_reports)]

    def list_reports(self, request, context):
        return self.paginated_collection(request, context)
```

### Service contract

The handler prefers the canonical service method `paginate()`:

```python
class ProductService:
    def paginate(self, page=1, per_page=20):
        result = self._repository.query().paginate(page=page, per_page=per_page)
        # result == {"items": [...], "total": 135}
        return result["items"], result["total"]      # (items, total) pair
        # OR return PaginatedResult(items=..., metadata=...)
        # OR return {"items": [...], "total": 135}
```

Fallbacks, in order:

1. `service.paginate(page=..., per_page=...)` → `PaginatedResult`,
   `(items, total)` pair, or `{"items": ..., "total": ...}`;
2. `service.list(page=..., per_page=...)` accepting pagination keywords;
3. `service.list()` sliced in memory (`paginate_sequence`); `total` is then
   the whole collection length.

---

## 6. Query / Repository Integration

Pagination on a real database stays at the **data layer** — never
`Resource → SQL`:

```python
from betrayer.data import BaseRepository, Query

class ProductRepository(BaseRepository[Product]):
    def paginate(self, page=1, per_page=20):
        return self.query().paginate(page=page, per_page=per_page)
        # -> {"items": [...], "total": int}
```

`Query.paginate(page, per_page)` is a **minimal extension** of the existing
Query Builder (`limit` / `offset` / `count`); it returns
`{"items": [...], "total": int}` for the caller to build metadata from.  The
generic helper `paginate_query(query, params)` wraps it into a
`PaginatedResult` with full metadata.

`BaseRepository` already exposes `query()`, `count()` and `where(...)`, so a
repository-level `paginate` is a few lines with no new abstraction.

---

## 7. Edge Cases

| Case                          | Behavior                                                                 |
|-------------------------------|--------------------------------------------------------------------------|
| empty collection              | `data: []`, `total: 0`, `total_pages: 0`                                 |
| first page                    | `page: 1`, normal slice                                                   |
| last page                     | returns the remaining items (may be < `per_page`)                        |
| page beyond last page         | `data: []`, metadata keeps the requested `page` and the true `total_pages` |
| `per_page = 1`                | one item per page                                                         |
| `per_page = MAX_PER_PAGE`     | allowed (exact cap)                                                       |
| `per_page > MAX_PER_PAGE`     | `422 VALIDATION_FAILED` (bounded)                                         |
| non-integer `page`/`per_page` | `422 VALIDATION_FAILED` (type error)                                      |
| `page = 0` / negative         | `422 VALIDATION_FAILED` (`>= 1`)                                          |
| `per_page = 0` / negative     | `422 VALIDATION_FAILED` (`>= 1`)                                          |
| `total = 0`                   | `total_pages: 0`, `data: []`                                              |

Out-of-range pages are **not** clamped: the response is an empty `items`
slice plus truthful metadata, so the client can detect the out-of-range page
explicitly.

---

## 8. What is NOT included

* cursor / keyset pagination (page-based is the canonical API today);
* filtering, sorting, search, caching, rate limiting (separate concerns);
* database-specific pagination abstractions;
* admin UI / frontend pagination;
* any change to unpaginated endpoints.