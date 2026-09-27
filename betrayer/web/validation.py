"""Canonical request validation + request pipeline (Task 11).

This is the **one** validation API in Betrayer.  It layers a small,
LLM-friendly declaration surface on top of the existing web abstractions
(``Request``, ``ApiResource``, ``WebContext``, ``ValidationError``) so a
resource declares what a request must look like and the framework parses,
validates and reports -- the resource never re-implements ad-hoc checks.

Pipeline (canonical order)::

    Request -> Routing -> Request Parsing -> Validation -> Resource -> Service -> Response/Error

* **Parsing happens once** -- :meth:`ApiResource.validate_request` reads the
  JSON body through ``Request.json`` (memoised on the request) exactly once.
* **Validation happens before the service** -- the resource validates the
  parsed body against its ``schema`` and only calls the service when the body
  is valid; an invalid body raises ``ValidationError`` (422) and the service is
  never reached.
* **Structured result** -- the :class:`ValidationResult` (cleaned ``data`` plus
  field errors) is attached to the ``WebContext`` so both the Resource and the
  Service can read the same, already-validated structure.

Declare a schema and attach it to a resource::

    from betrayer.web import CrudApiResource, Field, Schema

    class ProductSchema(Schema):
        name = Field(str, required=True, min_length=1)
        price = Field(float, required=True, min=0)
        stock = Field(int, default=0, min=0)

    class ProductResource(CrudApiResource):
        name = "products"
        prefix = "/api"
        schema = ProductSchema()

Validation failure uses the existing error contract -- a ``ValidationError``
(422 ``VALIDATION_FAILED``) whose structured field errors ride in the response
envelope under ``error.details``::

    {"success": false, "data": null,
     "error": {"code": "VALIDATION_FAILED",
               "message": "Request validation failed.",
               "details": {"fields": {"name": ["This field is required."],
                                      "price": ["Must be a number."]}}}}

No second error system, no second DI container: a resource still resolves its
service from the existing container through ``WebContext.resolve``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Type, Union

from betrayer.web.exceptions import ValidationError

__all__ = [
    "Field",
    "FieldError",
    "Schema",
    "ValidationResult",
    "validate",
]

_MISSING = object()

#: Type name used in ``"Must be a <name>."`` messages.
_TYPE_NAME: Dict[type, str] = {
    int: "number",
    float: "number",
    str: "string",
    bool: "boolean",
    list: "list",
    dict: "object",
}


def _type_label(expected: Any) -> str:
    """Human/LLM readable label for an expected type declaration."""
    if isinstance(expected, tuple):
        labels = [_type_label(item) for item in expected]
        # de-duplicate while keeping order (int|float -> "number")
        seen: List[str] = []
        for label in labels:
            if label not in seen:
                seen.append(label)
        if len(seen) == 1:
            return seen[0]
        return " or ".join(seen)
    if expected is Any or expected is None:
        return "value"
    if isinstance(expected, type):
        return _TYPE_NAME.get(expected, expected.__name__)
    return str(expected)


def _matches(value: Any, expected: Any) -> bool:
    """Return ``True`` when ``value`` satisfies the ``expected`` type.

    ``bool`` is never accepted as a ``number`` (Python's ``bool`` subclasses
    ``int``); ``int`` is accepted for a declared ``float`` because JSON has a
    single number type.
    """
    if expected is None or expected is Any:
        return True
    if isinstance(expected, tuple):
        return any(_matches(value, item) for item in expected)
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected)


class FieldError:
    """One rejected field: ``field`` + machine ``code`` + readable ``message``."""

    __slots__ = ("field", "code", "message")

    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        """JSON friendly shape (sorted, stable keys)."""
        return {"field": self.field, "code": self.code, "message": self.message}

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FieldError {self.field}:{self.code} {self.message!r}>"


class Field:
    """One declared request field: type, required/optional and value rules.

    Parameters
    ----------
    type:
        Expected Python type (or tuple of types).  ``None``/``Any`` skips the
        type check.  ``int`` is accepted for ``float``.
    required:
        When ``True`` the field must be present and not ``None``.
    default:
        Value injected for an absent field on a create (non ``partial``) call.
    nullable:
        When ``True`` an explicit ``None`` is accepted and passed through.
    choices:
        Allowed values (``in`` check).
    min / max:
        Inclusive numeric bounds (``min``/``max``).
    min_length / max_length:
        Inclusive length bounds for strings and lists.
    pattern:
        Regular expression a string value must fully/partially match.
    description:
        Free-form note surfaced by introspection.
    """

    __slots__ = (
        "type",
        "required",
        "default",
        "nullable",
        "choices",
        "min",
        "max",
        "min_length",
        "max_length",
        "pattern",
        "description",
        "name",
    )

    def __init__(
        self,
        type: Any = None,
        *,
        required: bool = False,
        default: Any = _MISSING,
        nullable: bool = False,
        choices: Optional[Sequence[Any]] = None,
        min: Optional[Union[int, float]] = None,
        max: Optional[Union[int, float]] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        description: str = "",
    ) -> None:
        self.type = type
        self.required = bool(required)
        self.default = default
        self.nullable = bool(nullable)
        self.choices = tuple(choices) if choices is not None else None
        self.min = min
        self.max = max
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.description = description
        self.name = ""

    # -- helpers -------------------------------------------------------
    @property
    def has_default(self) -> bool:
        """``True`` when a ``default`` was declared for absent values."""
        return self.default is not _MISSING

    def bind(self, name: str) -> "Field":
        """Attach ``name`` (returns ``self`` so declaration stays terse)."""
        self.name = name
        return self

    # -- validation ----------------------------------------------------
    def check(self, value: Any) -> List[Tuple[str, str]]:
        """Validate ``value``; return ``(code, message)`` pairs (empty = ok)."""
        errors: List[Tuple[str, str]] = []
        if not _matches(value, self.type):
            errors.append(("type", f"Must be a {_type_label(self.type)}."))
            # A wrong type makes the value-based rules meaningless.
            return errors
        if self.choices is not None and value not in self.choices:
            errors.append(
                ("choice", "Must be one of: " + ", ".join(str(c) for c in self.choices) + ".")
            )
        if self.min is not None or self.max is not None:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if self.min is not None and value < self.min:
                    errors.append(("min", f"Must be at least {self.min}."))
                if self.max is not None and value > self.max:
                    errors.append(("max", f"Must be at most {self.max}."))
        if self.min_length is not None or self.max_length is not None:
            if isinstance(value, (str, list, tuple)):
                size = len(value)
                if self.min_length is not None and size < self.min_length:
                    unit = "character" if isinstance(value, str) else "item"
                    errors.append(
                        ("min_length", f"Must be at least {self.min_length} {unit}(s).")
                    )
                if self.max_length is not None and size > self.max_length:
                    unit = "character" if isinstance(value, str) else "item"
                    errors.append(
                        ("max_length", f"Must be at most {self.max_length} {unit}(s).")
                    )
        if self.pattern is not None and isinstance(value, str):
            import re

            if re.search(self.pattern, value) is None:
                errors.append(("pattern", "Does not match the required pattern."))
        return errors

    # -- introspection -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """JSON friendly field description (LLM introspection)."""
        return {
            "name": self.name,
            "type": _type_label(self.type),
            "required": self.required,
            "nullable": self.nullable,
            "default": None if not self.has_default else self.default,
            "choices": list(self.choices) if self.choices is not None else None,
            "min": self.min,
            "max": self.max,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "pattern": self.pattern,
            "description": self.description,
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Field {self.name or '?'} type={_type_label(self.type)} required={self.required}>"


class ValidationResult:
    """Structured outcome of validating one request body.

    Attributes
    ----------
    data:
        The cleaned payload: only declared fields, coerced/validated, with
        defaults applied on a create call.  This is what the service receives.
    errors:
        The :class:`FieldError` list (empty when ``valid``).
    fields:
        ``{field: [message, ...]}`` -- the LLM/`422`-friendly field map.
    """

    __slots__ = ("data", "errors", "fields")

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        errors: Optional[Iterable[FieldError]] = None,
        fields: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self.data: Dict[str, Any] = dict(data or {})
        self.errors: List[FieldError] = list(errors or ())
        self.fields: Dict[str, List[str]] = dict(fields or {})

    @property
    def valid(self) -> bool:
        """``True`` when no field was rejected."""
        return not self.errors

    def raise_if_invalid(self, message: str = "Request validation failed.") -> Dict[str, Any]:
        """Raise the framework ``ValidationError`` (422) when invalid.

        Returns the cleaned ``data`` when the body is valid, so the caller can
        do ``data = result.raise_if_invalid()`` in one line.
        """
        if self.errors:
            raise ValidationError(
                message=message,
                code="VALIDATION_FAILED",
                stage="validation",
                fields=self.fields,
                errors=[error.to_dict() for error in self.errors],
            )
        return self.data

    def to_dict(self) -> Dict[str, Any]:
        """JSON friendly snapshot (deterministic keys)."""
        return {
            "valid": self.valid,
            "data": dict(self.data),
            "fields": {name: list(messages) for name, messages in self.fields.items()},
            "errors": [error.to_dict() for error in self.errors],
        }

    describe = to_dict

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.valid

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ValidationResult valid={self.valid} fields={sorted(self.fields)}>"


class Schema:
    """A declarative request schema: named :class:`Field` definitions.

    Two equivalent declaration styles::

        class ProductSchema(Schema):          # class style
            name = Field(str, required=True)

        schema = Schema({"name": Field(str, required=True)})   # mapping style

    A mapping value may also be a bare type (``{"name": str}``) or a plain
    default value, both of which are shorthand for an optional field.
    """

    def __init__(
        self,
        fields: Optional[Mapping[str, Any]] = None,
        *,
        name: Optional[str] = None,
    ) -> None:
        self.name = name or type(self).__name__
        collected: Dict[str, Field] = {}
        # Base classes first, so a subclass can override a declared field.
        for klass in reversed(type(self).__mro__):
            for key, value in vars(klass).items():
                if isinstance(value, Field):
                    collected[key] = value
        for key, value in (fields or {}).items():
            collected[str(key)] = self._coerce_field(value)
        self.fields: Dict[str, Field] = {
            key: field.bind(key) for key, field in collected.items()
        }

    @staticmethod
    def _coerce_field(spec: Any) -> Field:
        """Normalise a mapping value into a :class:`Field`."""
        if isinstance(spec, Field):
            return spec
        if isinstance(spec, type):
            return Field(spec)
        return Field(type(spec), default=spec)

    # -- validation ----------------------------------------------------
    def validate(self, data: Optional[Mapping[str, Any]], *, partial: bool = False) -> ValidationResult:
        """Validate ``data`` and return a :class:`ValidationResult`.

        ``partial=True`` validates an update payload: only the provided fields
        are checked and defaults are never injected.
        """
        if data is None:
            data = {}
        if not isinstance(data, Mapping):
            error = FieldError("_body", "type", "Request body must be a JSON object.")
            return ValidationResult(
                data={},
                errors=[error],
                fields={"_body": [error.message]},
            )

        cleaned: Dict[str, Any] = {}
        errors: List[FieldError] = []
        fields: Dict[str, List[str]] = {}

        def _reject(field_name: str, code: str, message: str) -> None:
            errors.append(FieldError(field_name, code, message))
            fields.setdefault(field_name, []).append(message)

        for field_name, field in self.fields.items():
            if field_name not in data:
                if partial:
                    continue
                if field.required:
                    _reject(field_name, "required", "This field is required.")
                    continue
                if field.has_default:
                    cleaned[field_name] = field.default
                continue

            value = data[field_name]
            if value is None:
                if field.required:
                    _reject(field_name, "required", "This field is required.")
                elif field.nullable:
                    cleaned[field_name] = None
                # Optional + None + not nullable -> treated as "not provided".
                continue

            field_errors = field.check(value)
            if field_errors:
                for code, message in field_errors:
                    _reject(field_name, code, message)
                continue
            cleaned[field_name] = value

        return ValidationResult(data=cleaned, errors=errors, fields=fields)

    def __call__(self, data: Optional[Mapping[str, Any]], *, partial: bool = False) -> ValidationResult:
        """Alias of :meth:`validate` (``schema(data)``)."""
        return self.validate(data, partial=partial)

    # -- introspection -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """JSON friendly schema description (declared fields + rules)."""
        return {
            "name": self.name,
            "fields": [field.to_dict() for field in self.fields.values()],
        }

    describe = to_dict

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Schema {self.name} fields={list(self.fields)}>"


def validate(
    schema: Union[Schema, Type[Schema], Mapping[str, Any], None],
    data: Optional[Mapping[str, Any]],
    *,
    partial: bool = False,
) -> ValidationResult:
    """Validate ``data`` against ``schema`` with one canonical entry point.

    ``schema`` may be a :class:`Schema` instance, a ``Schema`` subclass, or a
    raw field mapping (``{"name": Field(str, required=True)}``); ``None``
    returns a pass-through result wrapping ``data`` unchanged.
    """
    if schema is None:
        return ValidationResult(data=dict(data or {}))
    if isinstance(schema, Schema):
        resolved = schema
    elif isinstance(schema, type) and issubclass(schema, Schema):
        resolved = schema()
    elif isinstance(schema, Mapping):
        resolved = Schema(schema)
    else:
        raise TypeError(
            "validate() expects a Schema, a Schema subclass or a field mapping, "
            f"got {type(schema).__name__}"
        )
    return resolved.validate(data, partial=partial)
