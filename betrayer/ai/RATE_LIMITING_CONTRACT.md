# Betrayer Rate Limiting Contract

## Tujuan

Rate Limiting menyediakan canonical API untuk membatasi jumlah request berdasarkan **identity atau request key** dalam periode waktu tertentu. Implementasi adalah **fixed-window** yang sederhana, eksplisit, provider-agnostic, dan terintegrasi dengan existing web middleware pipeline.

## Canonical API

Rate limiter diakses melalui `betrayer.ratelimit` package:

```python
from betrayer.ratelimit import (
    RateLimit,              # Konfigurasi limit/window
    RateLimitResult,        # Hasil check (allowed, remaining, reset_at)
    RateLimitMiddleware,    # Middleware untuk web pipeline
    MemoryRateLimitStore,   # In-memory store default
    FixedWindowRateLimiter, # Core limiter (storage agnostic)
)
```

### RateLimit (konfigurasi)

```python
# 100 requests / 60 seconds
rl = RateLimit(limit=100, window=60)

# Validasi otomatis: limit >= 1, window >= 1
RateLimit(limit=0, window=60)   # ValueError
RateLimit(limit=10, window=0)   # ValueError
```

### FixedWindowRateLimiter (core check)

```python
from betrayer.ratelimit import FixedWindowRateLimiter, MemoryRateLimitStore

store = MemoryRateLimitStore()
limiter = FixedWindowRateLimiter(store=store)

result = limiter.check(key="user:42", limit=RateLimit(100, 60))
# result.allowed    -> True/False
# result.limit      -> 100
# result.remaining  -> 99
# result.reset_at   -> unix timestamp

# Peek tanpa increment:
result = limiter.peek(key="user:42", limit=RateLimit(100, 60))
```

## Fixed-Window Behavior

* Counter di-reset pada setiap awal window baru.
* Window alignment: `int(time.time() / window) * window`.
* Contoh: window=60 → window_start = 1234560, reset pada 1234620.
* Ketika window baru dimulai, counter kembali ke 0.

## Key Resolution

Middleware menentukan key request dengan prioritas:

1. **Authenticated user**: `request.user.id` → key `"user:<id>"`
2. **Client IP**: `request.remote_addr` → key `"ip:<addr>"`
3. **Fallback**: `"anonymous"`

Menggunakan `Request.user` dari Authentication (Task 16.1). Anonymous request tetap di-rate-limit menggunakan IP address.

## Storage

### RateLimitStore (abstract)

```python
class RateLimitStore(ABC):
    def increment(self, key: str, window: int, *, amount: int = 1) -> Tuple[int, float]:
        ...
    def get(self, key: str, window: int) -> Tuple[int, float]:
        ...
    def reset(self, key: str) -> None:
        ...
    def clear_expired(self) -> int:
        ...
    def inspect(self) -> dict:
        ...
```

### MemoryRateLimitStore

Default in-memory implementation. Thread-safe (`threading.Lock`). Expired windows dibersihkan lazy (pada akses). Tidak ada background cleanup worker.

Backend lain (Redis, dll.) dapat ditambahkan tanpa mengubah middleware/resource API.

## Middleware Integration

### RateLimitMiddleware

Berintegrasi melalui existing middleware system (`betrayer.web.middleware.Middleware`).

```python
from betrayer.ratelimit import RateLimitMiddleware

registry = app.registry.get("web.middleware")
registry.add(RateLimitMiddleware(default=RateLimit(100, 60)))
```

Pipeline position (priority=5):

```
Request
→ Authentication (priority=0)
→ Rate Limiting   (priority=5)
→ Authorization   (priority=10)
→ Validation
→ Resource
→ Service
→ Response
```

### Behavior

* `before_request`: mengecek limit; jika exceeded → return 429 response (short-circuit, resource tidak dieksekusi).
* `after_request`: menambahkan header `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
* Route tanpa `rate_limit` metadata → tidak di-rate-limit.
* Default limit bisa di-set via `RateLimitMiddleware(default=RateLimit(...))`.

## Resource Integration

Rate limiting adalah **opt-in**. Resource mendeklarasikan `rate_limit` class attribute:

```python
from betrayer.ratelimit import RateLimit

class ProductResource(CrudApiResource):
    name = "product"
    rate_limit = RateLimit(limit=100, window=60)
```

Resource tanpa `rate_limit` tetap memiliki behavior lama (tidak di-rate-limit).

Rate limit configuration juga bisa di-set per-route melalui metadata:

```python
router.get("/api/products", handler, metadata={
    "rate_limit": RateLimit(limit=50, window=60)
})
```

## Response 429

Ketika rate limit terlampaui, middleware mengembalikan:

```
HTTP 429 Too Many Requests
```

dengan body:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded. 100 requests per 60s. Retry after 30s."
  }
}
```

Menggunakan existing error infrastructure (`betrayer.web.errors`, `ApiResponse.error`).

## Headers

Response yang di-rate-limit mendapat header:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1700000000
Retry-After: 30
```

* `X-RateLimit-Limit` — configured limit
* `X-RateLimit-Remaining` — remaining requests in current window
* `X-RateLimit-Reset` — Unix timestamp when window resets
* `Retry-After` — seconds to wait (hanya ketika limit exceeded)

## Explicit API

Rate limit check dapat dilakukan secara eksplisit di mana saja:

```python
from betrayer.ratelimit import FixedWindowRateLimiter, MemoryRateLimitStore, RateLimit

limiter = FixedWindowRateLimiter(store=MemoryRateLimitStore())
result = limiter.check(key="custom:key", limit=RateLimit(10, 60))
if not result.allowed:
    # handle rate limited
    pass
```

## Concurrency Behavior

* `MemoryRateLimitStore` menggunakan `threading.Lock` untuk keamanan concurrent.
* Cocok untuk single-process deployment.
* Tidak ada distributed locking.

## Limitations (sengaja belum dibuat)

* Distributed Redis rate limiting
* Token bucket, leaky bucket, sliding window
* API key management
* Quota/billing system
* Admin dashboard/UI
* Background cleanup worker
* Persistent database storage

## Package Structure

```
betrayer/ratelimit/
  __init__.py              # Public API exports
  limit.py                 # RateLimit, RateLimitResult, TooManyRequestsError
  limiter.py               # FixedWindowRateLimiter
  store.py                 # RateLimitStore, MemoryRateLimitStore
  middleware.py            # RateLimitMiddleware
```