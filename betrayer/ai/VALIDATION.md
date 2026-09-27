# Betrayer Framework — Validation & Request Pipeline

One canonical way to parse + validate a request before the service runs.

## Pipeline (canonical order)

```
Request → Routing → Request Parsing → Validation → Resource → Service → Response/Error
```

* **Parsing happens once.** The JSON body is read through `Request.json`, which
  memoises the result on the request instance.
* **Validation happens before the service.** A resource validates the parsed
  body against its `schema`; only a valid body reaches the service.
* **Structured result.** The `ValidationResult` (cleaned `data` + field errors)
  is attached to `WebContext` (`context.validation` / `context.validated_data`)
  so both the Resource and the Service read the same structure.

There is exactly one validation API (`betrayer.web.validation`) and one error
contract (the existing web error envelope). Nothing else validates requests.

## Declare a schema

```python
from betrayer.web import CrudApiResource, Field, Schema

class ProductSchema(Schema):
    name  = Field(str, required=True)          # required
    price = Field(float, required=True, min=0) # type + value constraint
    stock = Field(int, default=0, min=0)       # optional + default

class ProductResource(CrudApiResource):
    name   = "products"
    prefix = "/api"
    schema = ProductSchema()                    # turns on the pipeline
```

`Field` supports: `type` (or a tuple of types), `required`, `default`,
`nullable`, `choices`, `min`/`max`, `min_length`/`max_length`, `pattern`.
`bool` is never accepted as a number; an `int` **is** accepted for a `float`
field (JSON has one number type).

Mapping style (equivalent): `Schema({"name": Field(str, required=True), "price": float})`.

## Validate directly (no HTTP)

```python
from betrayer.web import validate

result = ProductSchema().validate({"name": "Chair", "price": 10})
result.valid            # True
result.data             # {"name": "Chair", "price": 10, "stock": 0}
result.raise_if_invalid()   # -> data, or raises ValidationError (422)

bad = ProductSchema().validate({"price": "cheap"})
bad.valid               # False
bad.fields              # {"name": ["This field is required."],
                        #  "price": ["Must be a number."]}

# partial payload (update): only provided fields are checked, no defaults injected
ProductSchema().validate({"stock": 5}, partial=True).data   # {"stock": 5}

# one-shot helper accepts a Schema, a Schema subclass, a mapping or None
validate(ProductSchema, {"name": "x", "price": 1}).valid    # True
```

## Resource helpers (called by the CRUD handlers)

```python
result = self.validate_request(request, context)            # create (full body)
result = self.validate_request(request, context, partial=True)  # update (partial)
body   = self.validated_body(request, context)             # cleaned dict for the service
```

`CrudApiResource.create_handler` validates with `partial=False`,
`update_handler` with `partial=True` — but only when a `schema` is set. A
resource **without** a schema keeps the previous pass-through behaviour
(unchanged, backward compatible).

## Centralized error format

Validation failures reuse the one framework envelope
(`{"success", "data", "error"}`); the field errors ride under `error.details`:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Request validation failed.",
    "details": {
      "fields": {
        "name": ["This field is required."],
        "price": ["Must be a number."]
      },
      "errors": [
        {"field": "name", "code": "required", "message": "This field is required."},
        {"field": "price", "code": "type", "message": "Must be a number."}
      ]
    }
  }
}
```

| error code                | meaning                                   |
|---------------------------|-------------------------------------------|
| `required`                | field missing / `None` on a required field |
| `type`                    | wrong type                                |
| `choice` / `min` / `max`  | value constraint                          |
| `min_length` / `max_length` | string/list length constraint           |
| `pattern`                 | string pattern mismatch                   |

HTTP status is `422` (`ValidationError`, code `VALIDATION_FAILED`).

## Dependency injection (existing container)

No second container. A resource resolves its service from the Task 02 container
through `WebContext`:

```python
class ProductResource(CrudApiResource):
    name = "products"                # service key: "products_service"
    schema = ProductSchema()

# register once (module / composition root)
app.container.singleton("products_service",
                        lambda: ProductService(app.container.resolve("products_repository")))
```

An explicit `ProductResource(service=stub)` still bypasses the container for
unit tests.

## Golden Path example

`example/product_catalog/` uses the pipeline: `ProductSchema`
(`schemas.py`) + `ProductResource.schema`; the service (`service.py`) no longer
performs basic request validation.

```bash
POST /api/products  {"name": "Antique Chair", "price": 1500000, "stock": 2}  -> 201
POST /api/products  {"price": 1}                 -> 422 VALIDATION_FAILED (name required)
POST /api/products  {"name": "x", "price": "y"}  -> 422 VALIDATION_FAILED (price: number)
PUT  /api/products/1 {"stock": 5}                -> 200 (partial, validated)
```

## Limitations

* One body per request (JSON object); no query/header schemas.
* No coercion: a `"12"` string is **not** accepted for a numeric field (use an
  explicit converter if needed).
* Unknown fields are ignored (not persisted); only declared fields reach the
  service.
* No nested/array element schemas, no custom validator callables yet.
