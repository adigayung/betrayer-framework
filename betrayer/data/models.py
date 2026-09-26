"""Model abstraction: base Model with explicit field metadata.

A Model is a plain data container with declared fields.  It is **not** an
ORM entity: the mapping to database tables is handled by the Repository layer.

Design rules:
- Model has no dependency on Flask, web, or HTTP.
- Fields are explicit attributes with metadata (name, type, required, default).
- Serialization is to dict (``to_dict`` / ``from_dict``) for predictable
  conversion to JSON or other formats.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union

from betrayer.data.exceptions import ModelError


class Field:
    """Declarative field descriptor for a Model.

    ``name`` is set automatically when the owning Model class is created
    (via ``__init_subclass__``).  Application code usually passes only
    ``type_``, ``required``, ``default``, and ``description``.

    Examples::

        name = Field(str, required=True, description="User display name")
        age = Field(int, default=0)
    """

    def __init__(
        self,
        type_: type = str,
        *,
        required: bool = False,
        default: Any = None,
        description: str = "",
    ) -> None:
        self.type_ = type_
        self.required = required
        self.default = default
        self.description = description
        self.name: str = ""

    def validate(self, value: Any) -> Any:
        """Validate and coerce *value* according to field rules."""
        if value is None:
            if self.required:
                raise ModelError(
                    f"Field {self.name!r} is required",
                    stage="validate",
                )
            return self.default
        if not isinstance(value, self.type_):
            try:
                return self.type_(value)
            except (TypeError, ValueError) as exc:
                raise ModelError(
                    f"Field {self.name!r} expected {self.type_.__name__}, "
                    f"got {type(value).__name__}: {value!r}",
                    stage="validate",
                    cause=exc,
                ) from exc
        return value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_.__name__,
            "required": self.required,
            "default": self.default,
            "description": self.description,
        }


class ModelMeta(type):
    """Metaclass that collects ``Field`` instances into ``_fields``."""

    def __new__(
        mcs, name: str, bases: tuple, namespace: dict
    ) -> "ModelMeta":
        cls = super().__new__(mcs, name, bases, namespace)
        fields: Dict[str, Field] = {}
        for base in reversed(bases):
            if hasattr(base, "_fields"):
                fields.update(base._fields)
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, Field):
                attr_value.name = attr_name
                fields[attr_name] = attr_value
        cls._fields = fields  # type: ignore[attr-defined]
        return cls


class Model(metaclass=ModelMeta):
    """Base class for all Data Layer models.

    Subclasses declare fields as class-level ``Field`` instances::

        class User(Model):
            name = Field(str, required=True)
            age = Field(int, default=0)
    """

    _fields: Dict[str, Field]

    def __init__(self, **kwargs: Any) -> None:
        for field_name, field in self._fields.items():
            if field_name in kwargs:
                value = field.validate(kwargs[field_name])
            else:
                value = field.validate(None)
            setattr(self, field_name, value)
        # store any extra attributes silently (e.g. computed fields)
        for key, value in kwargs.items():
            if key not in self._fields:
                setattr(self, key, value)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Model":
        """Create an instance from a dictionary (keys = field names)."""
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (values only, no field metadata)."""
        return {name: getattr(self, name) for name in self._fields}

    @classmethod
    def introspect(cls) -> Dict[str, Any]:
        """Return deterministic metadata about the model class."""
        return {
            "name": cls.__name__,
            "module": cls.__module__,
            "fields": [f.to_dict() for f in cls._fields.values()],
        }

    def __repr__(self) -> str:  # pragma: no cover
        values = ", ".join(
            f"{k}={getattr(self, k)!r}" for k in self._fields
        )
        return f"{type(self).__name__}({values})"


__all__ = [
    "Field",
    "Model",
    "ModelMeta",
]