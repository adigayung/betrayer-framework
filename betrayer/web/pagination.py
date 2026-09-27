"""Canonical page-based pagination for Betrayer collection endpoints (Task 16.3).

This is the **one** pagination API in Betrayer.  It is a small, explicit,
LLM-friendly surface layered on the existing web abstractions
(:class:`~betrayer.web.request.Request`,
:class:`~betrayer.web.exceptions.ValidationError`); it does not create a
second pagination subsystem, a custom envelope, or a database-specific
abstraction.

Pipeline::

    request -> parse_pagination(request) -> PaginationParams
             -> paginate_query(query, params)        (data layer)
             -> paginate_sequence(items, params)     (in-memory fallback)
             -> PaginatedResult(items, PaginationMetadata)
             -> envelope  {success, data, meta, pagination}

Defaults / rules (canonical)
----------------------------
* ``page``     -- default ``1``; must parse as an integer >= 1.
* ``per_page`` -- default ``20``; must parse as an integer with
  ``1 <= per_page <= MAX_PER_PAGE`` (``100``).  A client can never request an
  unbounded page size.
* ``total_pages`` -- ``ceil(total / per_page)``; ``0`` when ``total == 0``.

Validation
----------
Invalid parameters (non-integer, ``page < 1``, ``per_page < 1``,
``per_page > MAX_PER_PAGE``) raise the framework
:class:`~betrayer.web.exceptions.ValidationError` (``422 VALIDATION_FAILED``)
with the same structured ``fields`` / ``errors`` view the body-validation
pipeline (``Schema``) uses -- there is no second error envelope.

Out-of-range pages
------------------
A ``page`` beyond the last page returns an **empty** ``items`` slice while the
metadata keeps the requested ``page`` and the true ``total_pages``, so the
client can see that the page is out of range.  This is the most explicit,
least magical behaviour (no silent clamping, no invented convention).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from betrayer.web.exceptions import ValidationError
from betrayer.web.request import Request

__all__ = [
    "DEFAULT_PAGE",
    "DEFAULT_PER_PAGE",
    "MAX_PER_PAGE",
    "PAGE_PARAM",
    "PER_PAGE_PARAM",
    "PaginationParams",
    "PaginationMetadata",
    "PaginatedResult",
    "parse_pagination",
    "paginate_sequence",
    "paginate_query",
]

#: Query-string key for the page number.
PAGE_PARAM = "page"

#: Query-string key for the page size.
PER_PAGE_PARAM = "per_page"

#: Default page number when ``page`` is absent.
DEFAULT_PAGE = 1

#: Default page size when ``per_page`` is absent.
DEFAULT_PER_PAGE = 20

#: Hard upper bound for ``per_page`` (clients can never request more).
MAX_PER_PAGE = 100


def _reject(field: str, code: str, message: str) -> None:
    """Raise the framework ValidationError with the standard field view."""
    raise ValidationError(
        message="Invalid pagination parameter.",
        code="VALIDATION_FAILED",
        stage="validation",
        fields={field: [message]},
        errors=[{"field": field, "code": code, "message": message}],
    )


def _parse_int(
    request: Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: Optional[int],
) -> int:
    """Read one query parameter, coerced to an int with bounds checks."""
    raw = request.get_query(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _reject(name, "type", f"{name} must be an integer, got {raw!r}.")
    if value < minimum:
        _reject(name, "min", f"{name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        _reject(name, "max", f"{name} must be at most {maximum}.")
    return value


@dataclass(frozen=True)
class PaginationParams:
    """Validated page-based pagination parameters.

    Construct directly (``PaginationParams(page=2, per_page=20)``) or parse
    from a request with :func:`parse_pagination`.  Instances are immutable;
    invalid values raise at construction time (programming error guard).

    Attributes
    ----------
    page:
        The 1-based page number (``>= 1``).
    per_page:
        The page size (``1 <= per_page <= MAX_PER_PAGE``).
    """

    page: int = DEFAULT_PAGE
    per_page: int = DEFAULT_PER_PAGE

    def __post_init__(self) -> None:
        if not isinstance(self.page, int) or isinstance(self.page, bool):
            raise TypeError("PaginationParams.page must be an integer")
        if not isinstance(self.per_page, int) or isinstance(self.per_page, bool):
            raise TypeError("PaginationParams.per_page must be an integer")
        if self.page < 1:
            raise ValueError("PaginationParams.page must be >= 1")
        if not 1 <= self.per_page <= MAX_PER_PAGE:
            raise ValueError(f"PaginationParams.per_page must be 1..{MAX_PER_PAGE}")

    @property
    def offset(self) -> int:
        """Number of rows to skip for this page (``(page - 1) * per_page``)."""
        return (self.page - 1) * self.per_page

    def to_dict(self) -> dict:
        """JSON friendly parameter snapshot."""
        return {"page": self.page, "per_page": self.per_page}

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PaginationParams page={self.page} per_page={self.per_page}>"


@dataclass(frozen=True)
class PaginationMetadata:
    """Stable pagination metadata attached to a paginated collection response.

    Attributes
    ----------
    page:
        The requested page number.
    per_page:
        The requested page size.
    total:
        Total number of matching items (independent of the page).
    total_pages:
        ``ceil(total / per_page)``; ``0`` when ``total == 0``.
    """

    page: int
    per_page: int
    total: int
    total_pages: int

    @classmethod
    def from_params(cls, params: PaginationParams, total: int) -> "PaginationMetadata":
        """Compute metadata for ``params`` given a ``total`` item count."""
        total = int(total)
        total_pages = (total + params.per_page - 1) // params.per_page if total else 0
        return cls(
            page=params.page,
            per_page=params.per_page,
            total=total,
            total_pages=total_pages,
        )

    def to_dict(self) -> dict:
        """JSON friendly metadata (the documented wire shape)."""
        return {
            "page": self.page,
            "per_page": self.per_page,
            "total": self.total,
            "total_pages": self.total_pages,
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<PaginationMetadata page={self.page} per_page={self.per_page} "
            f"total={self.total} total_pages={self.total_pages}>"
        )


@dataclass(frozen=True)
class PaginatedResult:
    """One paginated slice: ``items`` plus consistent ``metadata``.

    This is the canonical return value of the pagination helpers and the
    optional ``service.paginate(page=..., per_page=...)`` contract.
    """

    items: Sequence[Any]
    metadata: PaginationMetadata

    def to_dict(self) -> dict:
        """JSON friendly snapshot (``items`` + ``pagination`` metadata)."""
        return {
            "items": list(self.items),
            "pagination": self.metadata.to_dict(),
        }

    describe = to_dict

    def __len__(self) -> int:
        return len(self.items)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PaginatedResult items={len(self.items)} {self.metadata!r}>"


def parse_pagination(
    request: Request,
    *,
    page_key: str = PAGE_PARAM,
    per_page_key: str = PER_PAGE_PARAM,
) -> PaginationParams:
    """Parse and validate ``page`` / ``per_page`` from a request.

    Absent parameters fall back to the documented defaults.  Invalid values
    raise :class:`~betrayer.web.exceptions.ValidationError` (422
    ``VALIDATION_FAILED``) carrying the standard structured field view.

    ::

        params = parse_pagination(request)          # page & per_page defaults
        params = parse_pagination(request, page_key="p", per_page_key="size")
    """
    page = _parse_int(
        request,
        page_key,
        default=DEFAULT_PAGE,
        minimum=1,
        maximum=None,
    )
    per_page = _parse_int(
        request,
        per_page_key,
        default=DEFAULT_PER_PAGE,
        minimum=1,
        maximum=MAX_PER_PAGE,
    )
    return PaginationParams(page=page, per_page=per_page)


def paginate_sequence(
    items: Sequence[Any],
    params: PaginationParams,
) -> PaginatedResult:
    """Paginate an in-memory sequence (fallback, no data layer involved).

    Used when a service has no ``paginate`` implementation and returns the
    full collection from ``list()``; the page slice is cut in memory while the
    metadata always reports the true ``total``.
    """
    values = list(items)
    total = len(values)
    start = params.offset
    page_items = values[start : start + params.per_page]
    return PaginatedResult(
        items=page_items,
        metadata=PaginationMetadata.from_params(params, total),
    )


def paginate_query(query: Any, params: PaginationParams) -> PaginatedResult:
    """Paginate at the data layer through an existing query abstraction.

    ``query`` must expose the framework Query Builder surface used by
    ``betrayer.data.Query`` / ``BaseRepository.query()``:

    * ``count()``  -- total matching rows (limit/offset independent);
    * ``limit(n)`` / ``offset(n)`` -- immutable composable modifiers;
    * ``get()``    -- execute and return the matching rows.

    This keeps pagination at the correct layer (Query/Repository), never
    ``Resource -> SQL``.
    """
    total = int(query.count())
    page_items = list(query.limit(params.per_page).offset(params.offset).get())
    return PaginatedResult(
        items=page_items,
        metadata=PaginationMetadata.from_params(params, total),
    )