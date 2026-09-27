# Cache Contract

## Purpose

The Cache subsystem provides a **canonical, backend-agnostic cache API** for the
Betrayer framework.  It is designed for LLM-friendly discovery and usage.

## Location

```
betrayer/
  data/
    cache.py          # CacheBackend, MemoryCacheBackend, CacheManager (core)
  cache/
    __init__.py       # Re-exports + WebCacheMiddleware, CachePolicy
    policy.py         # CachePolicy — declarative cache config for resources
    middleware.py     # WebCacheMiddleware — HTTP response caching middleware
```

## Canonical API

```python
from betrayer.data import CacheManager

cache = CacheManager()

cache.set("key", value, ttl=60)         # store with 60s TTL
cache.get("key")                        # retrieve (or MISSING sentinel)
cache.get("key", default=None)          # retrieve (None on miss)
cache.exists("key")                     # True if present and not expired
cache.delete("key")                     # remove key (no-op if missing)
cache.clear()                           # remove all entries
cache.get_or_set("key", factory, ttl=60) # get or compute+store
```

### get / set / delete / exists / clear

- `get(key, default=_MISSING)` — returns `default` (or the `MISSING` sentinel)
  when the key is missing or expired.  The sentinel distinguishes a cache miss
  from a cached `None`.
- `set(key, value, ttl=None)` — stores a value.  `ttl=None` means no
  expiration.  Negative TTL raises `ValueError`.  TTL=0 is a no-op.
- `delete(key)` — removes the key.  No-op when missing.
- `exists(key)` — returns `True` if the key exists and has not expired.
- `clear()` — removes all entries from the backend.

### get_or_set

```python
cache.get_or_set("user:1", fetch_user(1), ttl=300)
cache.get_or_set("config", {"theme": "dark"}, ttl=None)
```

When the key is missing or expired, `factory` is called (no arguments) and its
return value is stored before being returned.  If `factory` is not callable it
is used as the value directly.

### MISSING sentinel

```python
value = cache.get("key")
if value is cache.MISSING:
    # cache miss — value was NOT cached
    ...
```

## TTL

TTL is specified in seconds.

| TTL value | Behavior |
|-----------|----------|
| `None`    | No expiration (cached forever until deleted/cleared) |
| `0`       | Value expires immediately (no-op, nothing is stored) |
| `> 0`     | Value is available for that many seconds |
| `< 0`     | `ValueError` is raised |

Expired values are treated as cache misses.  Cleanup is lazy (on access).

## Cache Miss Behavior

A cache miss returns the `MISSING` sentinel (or the provided `default`):

```python
cache.get("missing")           # -> cache.MISSING (sentinel)
cache.get("missing", None)     # -> None
cache.get("missing", "fall")   # -> "fall"
```

## Cached `None`

Cached `None` is valid and is NOT treated as a cache miss:

```python
cache.set("config", None, ttl=60)
cache.get("config")            # -> None (not MISSING)
cache.get("config", "fall")    # -> None (default is ignored when cached)
```

## Storage

### Backend abstraction

```python
from betrayer.data import CacheBackend, MemoryCacheBackend
```

The abstract `CacheBackend` class defines the contract.  `MemoryCacheBackend`
is the default in-memory implementation.

### MemoryCacheBackend

- Thread-safe via `threading.Lock`
- Stores values + expiration timestamps
- Lazy expiration cleanup (on `get`/`has`/`exists`)
- Independent key storage
- No background workers or threads

## Concurrency

All `CacheManager` operations are thread-safe when backed by a thread-safe
backend (the default `MemoryCacheBackend` is thread-safe).

- Concurrent `get`/`set`/`delete`/`exists`/`clear` are safe.
- No distributed locking is implemented.
- No background cleanup threads.

## Application Usage

Cache can be used directly from any service or application layer:

```python
# In a service
class ProductService:
    def __init__(self, cache: CacheManager):
        self.cache = cache

    def get_product(self, id: int):
        key = f"product:{id}"
        cached = self.cache.get(key)
        if cached is not self.cache.MISSING:
            return cached
        product = self._fetch_from_db(id)
        self.cache.set(key, product, ttl=300)
        return product
```

For DI integration, register `CacheManager` in the Container:

```python
container.singleton("cache", CacheManager())
```

## HTTP / Resource Integration

### Opt-in per resource

```python
from betrayer.web import CrudApiResource
from betrayer.cache import CachePolicy

class ProductResource(CrudApiResource):
    name = "product"
    cache_ttl = 60   # cache GET/HEAD for 60 seconds
```

Or with an explicit `CachePolicy`:

```python
cache_ttl = CachePolicy(ttl=60, cache_error=False)
```

Resources **without** `cache_ttl` are never cached (no behavior change).

### WebCacheMiddleware

```python
from betrayer.cache import WebCacheMiddleware, CacheManager

registry.add(WebCacheMiddleware(cache=CacheManager()))
```

- Only `GET`/`HEAD` requests are candidates for caching.
- `POST`/`PUT`/`PATCH`/`DELETE` are never automatically cached.
- Error responses (status >= 400) are **not** cached by default
  (configurable via `CachePolicy(cache_error=True)`).
- User-specific data is not automatically detected — configure per-resource.
- Adds `X-Cache: HIT` / `X-Cache: MISS` headers to cached responses.

### Cache key rules

The HTTP cache key is deterministic:

```
{method}:{path}?{sorted_query_params}
```

- `GET /products?page=1&limit=20` and `GET /products?limit=20&page=1`
  produce the **same** key (query parameters are sorted).
- The `Authorization` header is **not** included in the cache key.

## Invalidation

```python
cache.delete("product:123")   # remove one cached value
cache.clear()                 # remove all cached values
```

No automatic dependency graph / cache invalidation system is implemented.

## Limitations

- No Redis, Memcached, or database-backed cache backends (backend abstraction
  exists and can be extended).
- No distributed or clustered cache.
- No cache tags / stampede protection / locking.
- No background cleanup workers (expiration is lazy).
- No cache warming / preloading.
- No full HTTP caching standard (e.g. `Cache-Control`, `ETag`).

## Non-goals (not implemented in this task)

- Redis / Memcached / database cache backends
- Distributed cache and invalidation
- Cache tags / advanced eviction
- Cache warming / preloading
- Full `Cache-Control` / `ETag` / `Vary` HTTP standard
- Cache dashboard / admin UI
- CDN / HTTP proxy / frontend cache integration