# Authorization Contract for LLM Agents

Authorization answers **"is this identity allowed to perform this action?"** —
never *"who is this request?"* (that is Authentication, Task 16.1).  Read this
to protect endpoints in any Betrayer application.

**Flow (deterministic):**

```text
Request → Authentication (401 on anonymous+required)
        → Authorization  (403 on denied)
        → Validation → Resource → Service → Response
```

* Allowed  → request continues.
* Denied   → `403 FORBIDDEN` (existing structured error envelope).
* Anonymous on an endpoint that only requires identity → still `401`
  from the **authentication** layer, never from authorization.

---

## 1. Core Concepts

| Term                 | Meaning                                                              |
|----------------------|----------------------------------------------------------------------|
| **Authorizer**       | A policy object: `authorize(identity, action, resource, context) -> bool`. |
| **authorize()**      | The explicit check function: allow → continue, deny → `403 FORBIDDEN`. |
| **AuthorizationMiddleware** | Runs the check in the pipeline after Authentication (priority 10 > 0). |
| **"authorizer" key** | Canonical container key: `app.container.instance("authorizer", ...)`. |
| **ForbiddenError**   | 403 `FORBIDDEN` — reused from the existing web error hierarchy.      |

Authorization **never** re-resolves identity: it only reads `request.user`
(an `Identity` or `AnonymousIdentity` from Task 16.1).

---

## 2. Canonical API

```python
from betrayer.auth import Authorizer, authorize, CallbackAuthorizer, AllowAllAuthorizer

# The contract — implement exactly one method:
class MyAuthorizer(Authorizer):
    def authorize(self, identity, action, resource=None, context=None) -> bool:
        return action == "view" or identity.get("role") == "admin"
```

Inputs:

* `identity` — `request.user` (`Identity` / `AnonymousIdentity`)
* `action`   — short verb string, e.g. `"view"`, `"create"`, `"update"`, `"delete"`
* `resource` — optional object the action applies to (id, model, resource name)
* `context`  — optional request `WebContext` (used to resolve the container authorizer)

Result (deterministic):

```text
True  → authorize() returns None, request continues
False → authorize() raises ForbiddenError (403, code FORBIDDEN)
```

Explicit check from code:

```python
authorize(identity, action="update", resource=product, context=context)
# or with an inline policy:
authorize(request.user, action="view", authorizer=MyAuthorizer())
```

Built-in policies:

```python
CallbackAuthorizer(my_policy_callable)   # wrap any (identity, action, resource, context) -> bool
AllowAllAuthorizer()                     # allow every AUTHENTICATED identity, deny anonymous
```

---

## 3. Registering the Authorizer (Container/DI)

```python
app.container.instance("authorizer", MyAuthorizer())
# or: app.container.singleton("authorizer", MyAuthorizer)

resolved = app.container.resolve("authorizer")
```

Resolution order inside `authorize()`:

1. explicit `authorizer=` argument,
2. `context.container.resolve("authorizer")` (canonical key `"authorizer"`).

With **no** authorizer available the check raises `RuntimeError` — a missing
DI wiring problem, never a silent allow.

---

## 4. Protecting a Resource

### Option A: declarative flags on the Resource (default CRUD handlers)

```python
from betrayer.web import CrudApiResource

class ProductResource(CrudApiResource):
    name = "product"
    authorization_required = True
    authorization_action = "view"                                   # default action
    authorization_actions = {"POST": "create", "PUT": "update",     # per HTTP method
                             "DELETE": "delete"}
    authorization_resource_key = None        # or "id" to pass the path param as resource
```

* Deny → `403 FORBIDDEN`; allow → handler continues to the service.
* Resources without the flags behave exactly as before (no check runs).
* Authentication still layers first: add `authentication_required = True` when
  anonymous requests must get `401` instead of reaching the authorizer.

### Option B: explicit check in a custom handler

```python
async def secret(self, request, context):
    self.require_authorization(request, context, action="view")
    return ApiResponse.success({"secret": True})
```

### Option C: pipeline middleware (route flags)

```python
from betrayer.auth import AuthorizationMiddleware

app.registry.get("web.middleware").add(AuthorizationMiddleware())
# register AFTER AuthenticationMiddleware (its priority 10 > 0 guarantees order)

router.get("/orders", handler, metadata={"authorization_required": True,
                                         "authorization_action": "view"})
# or as attributes on a Route object:
route.authorization_required = True
route.authorization_action = "view"
route.authorization_resource_key = "id"   # passes request.param("id") as resource
```

The middleware reads `request.user`, resolves the authorizer through the
container, and raises 403 on denial. Routes without the flags are untouched.

---

## 5. Errors

| Error              | Code              | HTTP | Raised when                                    |
|--------------------|-------------------|------|------------------------------------------------|
| `ForbiddenError`   | `FORBIDDEN`       | 403  | Authenticated (or anonymous) but **not allowed** |
| `UnauthenticatedError` | `UNAUTHENTICATED` | 401 | No valid identity and authentication required |

Both use the **existing** error hierarchy and envelope — no new error format:

```json
{
  "success": false,
  "data": null,
  "error": {"code": "FORBIDDEN", "message": "Not allowed to perform 'update'"}
}
```

Denial details are deliberately minimal: `error.context` carries only
`action` and the resource **type** name — never resource values.

---

## 6. Full Example

```python
from betrayer.auth import Authorizer
from betrayer.web import CrudApiResource

class RoleAuthorizer(Authorizer):
    def authorize(self, identity, action, resource=None, context=None) -> bool:
        if identity.is_anonymous:
            return False
        return action in identity.get("permissions", [])

app.container.instance("authorizer", RoleAuthorizer())

class InvoiceResource(CrudApiResource):
    name = "invoice"
    authentication_required = True      # 401 for anonymous (Authentication, 16.1)
    authorization_required = True       # 403 for not allowed (Authorization, 16.2)
    authorization_actions = {"DELETE": "delete"}
```

```text
anonymous  + authentication_required → 401 UNAUTHENTICATED
authenticated, denied                → 403 FORBIDDEN
authenticated, allowed               → 200/201/204 normal response
```

---

## 7. Testing

```python
from betrayer.auth import Identity, authorize
from betrayer.web.exceptions import ForbiddenError

authorize(Identity(id=1), "view", authorizer=MyAuthorizer())   # allowed → None

with pytest.raises(ForbiddenError) as e:                       # denied → 403
    authorize(Identity(id=1), "update", authorizer=MyAuthorizer())
assert e.value.http_status == 403
```

Focused tests: `tests/test_authorization.py`.

---

## 8. What This Is NOT

- No RBAC/role hierarchy, no ACL engine, no permission database.
- No policy DSL, no admin UI, no distributed/Redis authorization.
- No JWT/OAuth/session/password logic (see Authentication contract).
- Not a second authentication system and not a new error/pipeline subsystem —
  it reuses Identity, `request.user`, Container/DI, WebPipeline, ApiResource
  and the existing error envelope.
