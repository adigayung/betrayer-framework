"""Type / value mapping between Python and database values.

Task 09.2.  The mapper is **database-agnostic**: it works purely on Python
values and their declared types, never on SQL or dialect behaviour.  Column
*type names* (``INTEGER``, ``TEXT``, ...) are delegated to the dialect via
``SQLDialect.type_name``; this module only decides how a Python value is
converted before binding and how a raw driver value is converted back when a
model is hydrated.

Supported types: ``str``, ``int``, ``float``, ``bool``, ``datetime``,
``date``, ``Decimal``, bytes, and ``None`` (nullable).  Unknown types are
passed through unchanged — Betrayer never assumes a concrete database driver
knows a specific pickle/json encoding.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any, Dict, Optional, Type

from betrayer.data.exceptions import ModelError

#: Canonical Python types understood by the value mapper.  Plain value data
#: types (no SQL involved), in declaration order used by ``type_name``.
VALUE_TYPES: tuple = (
    str,
    int,
    float,
    bool,
    datetime.datetime,
    datetime.date,
    decimal.Decimal,
    bytes,
)

__all__ = [
    "ValueMapper",
    "VALUE_TYPES",
    "canonical_type",
    "python_type_name",
]


def canonical_type(type_: Any) -> type:
    """Return the canonical base type for *type_*.

    ``bool`` keeps precedence over ``int`` (``bool`` is a subclass of
    ``int``), ``datetime`` over ``date``.  Unknown types are returned as-is.
    """
    if type_ is bool or type_ is int:
        return bool if type_ is bool else int
    if type_ is datetime.datetime:
        return datetime.datetime
    if type_ is datetime.date:
        return datetime.datetime if issubclass(type_, datetime.datetime) else datetime.date
    return type_


def python_type_name(type_: Any) -> str:
    """Stable, human readable name for *type_* (e.g. ``"datetime"``)."""
    if type_ is bool:
        return "bool"
    if type_ is int:
        return "int"
    if type_ is float:
        return "float"
    if type_ is str:
        return "str"
    if type_ is datetime.datetime:
        return "datetime"
    if type_ is datetime.date:
        return "date"
    if type_ is decimal.Decimal:
        return "decimal"
    if type_ is bytes:
        return "bytes"
    return getattr(type_, "__name__", str(type_))


class ValueMapper:
    """Maps Python values to and from database values.

    Both directions are database-agnostic:

    * ``to_database``  — prepare a Python value for a parameterized query.
      ``None`` stays ``None``, ``bool`` stays ``bool`` (the dialect decides
      the literal when needed), everything else is passed through unchanged.
    * ``from_database`` — convert a raw driver value back into the declared
      Python type during model hydration.  Conversion is lenient: a driver
      that already returns the right type is never touched; convertible
      values are coerced; invalid conversions raise ``ModelError``.
    """

    #: Type -> conversion callable for ``from_database``.
    _COERCERS: Dict[type, Any] = {
        str: str,
        int: int,
        float: float,
        bool: bool,
        bytes: bytes,
    }

    def __init__(self, type_: Any = None) -> None:
        self._type: Any = canonical_type(type_) if type_ is not None else None
        self._name: str = python_type_name(self._type) if self._type is not None else "any"

    @property
    def type(self) -> Any:
        """Canonical Python type this mapper converts to."""
        return self._type

    @property
    def type_name(self) -> str:
        """Stable name of the mapped Python type."""
        return self._name

    # ── to database ───────────────────────────────────────────────────

    def to_database(self, value: Any) -> Any:
        """Convert *value* to a bindable parameter (never SQL)."""
        if value is None:
            return None
        if isinstance(value, (bool, int, float, str, bytes)):
            return value
        if isinstance(value, (datetime.datetime, datetime.date, decimal.Decimal)):
            return value
        return value

    # ── from database ─────────────────────────────────────────────────

    def from_database(self, value: Any) -> Any:
        """Convert a raw driver value into the declared Python type."""
        if value is None or self._type is None:
            return value
        if isinstance(value, self._type):
            return value
        coercer = self._COERCERS.get(self._type)
        if coercer is None:
            # datetime/date/Decimal: leave driver value as-is; a driver that
            # already returned the right type was handled above.
            return value
        try:
            if coercer is bool:
                return bool(value)
            return coercer(value)
        except (TypeError, ValueError) as exc:
            raise ModelError(
                message=(
                    f"Cannot convert database value {value!r} to "
                    f"{self._name}"
                ),
                stage="hydrate",
                cause=exc,
                context={"type": self._name},
            ) from exc


def type_name(type_: Any) -> str:
    """Shortcut for :func:`python_type_name` (stable, no SQL)."""
    return python_type_name(type_)


def default_type_for(value: Any) -> Optional[type]:
    """Return a sensible Python type for a sample *value* (or ``None``)."""
    if value is None:
        return None
    return type(value)