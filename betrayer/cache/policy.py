"""CachePolicy — declarative cache configuration for resources.

``CachePolicy`` is a simple value object that tells the middleware which
endpoints to cache and for how long.  Resources without a policy are never
cached.

Example::

    from betrayer.cache import CachePolicy

    class ProductResource(CrudApiResource):
        name = "product"
        cache_policy = CachePolicy(ttl=60)   # cache GET responses for 60s
"""

from __future__ import annotations

from typing import Optional


class CachePolicy:
    """Declarative cache configuration for a resource or route.

    Attributes
    ----------
    ttl:
        Time-to-live in seconds.  ``None`` means no expiration (cache
        forever until invalidated).
    cache_error:
        When ``True``, error responses (status >= 400) are also cached.
        Default is ``False`` — only successful responses (2xx/3xx) are cached.
    key_prefix:
        Optional prefix to avoid key collisions across resources.
    """

    def __init__(
        self,
        ttl: Optional[int] = None,
        *,
        cache_error: bool = False,
        key_prefix: Optional[str] = None,
    ) -> None:
        if ttl is not None:
            if not isinstance(ttl, (int, float)) or ttl < 0:
                raise ValueError(
                    f"CachePolicy ttl must be None or a non-negative number, got {ttl}"
                )
            self._ttl: Optional[int] = int(ttl) if ttl > 0 else 0
        else:
            self._ttl = None
        self._cache_error = bool(cache_error)
        self._key_prefix = str(key_prefix) if key_prefix is not None else None

    @property
    def ttl(self) -> Optional[int]:
        """Seconds to cache, or ``None`` for no expiration."""
        return self._ttl

    @property
    def cache_error(self) -> bool:
        """Whether error responses should be cached."""
        return self._cache_error

    @property
    def key_prefix(self) -> Optional[str]:
        """Optional key prefix."""
        return self._key_prefix

    def to_dict(self) -> dict:
        return {
            "ttl": self._ttl,
            "cache_error": self._cache_error,
            "key_prefix": self._key_prefix,
        }

    def describe(self) -> dict:
        return self.to_dict()

    def __repr__(self) -> str:
        return (
            f"<CachePolicy ttl={self._ttl} "
            f"cache_error={self._cache_error} "
            f"key_prefix={self._key_prefix!r}>"
        )