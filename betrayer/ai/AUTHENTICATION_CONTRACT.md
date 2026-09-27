# Authentication Contract for LLM Agents

Authentication determines **who** the request is (identity), not **what** the
user is allowed to do (authorization, a separate capability).  This contract
describes the canonical authentication API — read this to use authentication
in any Betrayer application.

---

## 1. Core Concepts

| Term             | Meaning                                                |
|------------------|--------------------------------------------------------|
| **Identity**     | Who the request is — an `Identity` object with `id`, optional `name`, `email`, and `attributes`. |
| **AnonymousIdentity** | The identity of an unauthenticated request. `is_anonymous == True`. |
| **Authenticator** | Resolves `request -> Identity | None`. The framework does not dictate *how*. |
| **request.user** | The canonical accessor for the current identity. Always safe to access — never raises. |

Every request gets either an `Identity` (authenticated) or an
`AnonymousIdentity` (anonymous).  Check with:

```python
if request.user.is_authenticated:
    # authenticated
else:
    # anonymous
```

---

## 2. Identity

```python
from betrayer.auth import Identity, AnonymousIdentity

# Authenticated user
identity = Identity(id=42, name="Ada", email="ada@example.com")
identity.is_authenticated  # True
identity.is_anonymous     # False

# Anonymous request
anon = AnonymousIdentity()
anon.is_authenticated  # False
anon.is_anonymous      # True

# Attributes
identity = Identity(id="svc-1", attributes={"scopes": ["read", "write"]})
identity.get("scopes")  # ["read", "write"]
```

**No User model is required.**  Any object, dict, or application model can
back an `Identity`.

---

## 3. Authenticator

An `Authenticator` resolves a request to an identity:

```python
from betrayer.auth import Authenticator

# Subclass:
class MyAuthenticator(Authenticator):
    def authenticate(self, request) -> Identity | None:
        token = request.header("Authorization", "").removeprefix("Bearer ")
        if token == "my-secret":
            return Identity(id=1, name="My User")
        return None
```

### Built-in: `HeaderTokenAuthenticator`

```python
from betrayer.auth import HeaderTokenAuthenticator, Identity

def resolve_token(token: str) -> Identity | None:
    if token == "valid-token":
        return Identity(id=42, name="Dev User")
    return None

authenticator = HeaderTokenAuthenticator(resolver=resolve_token)
```

Extracts `Authorization: Bearer <token>` by default.  Customise with
`header=` and `scheme=` constructor arguments.

### Built-in: `CallbackAuthenticator`

```python
from betrayer.auth import CallbackAuthenticator, Identity

def my_auth(request) -> Identity | None:
    api_key = request.header("X-Api-Key")
    if api_key == "abc":
        return Identity(id=1, name="Service")
    return None

authenticator = CallbackAuthenticator(callback=my_auth)
```

---

## 4. Registering an Authenticator

Register through the **Container/DI**:

```python
# Register as a service
app.container.singleton("authenticator", authenticator)
```

Or create and register the authentication middleware directly:

```python
from betrayer.auth import AuthenticationMiddleware, HeaderTokenAuthenticator

authenticator = HeaderTokenAuthenticator(resolver=resolve_token)
auth_mw = AuthenticationMiddleware(authenticator=authenticator)

# Register on the web middleware registry:
app.registry.get("web.middleware").add(auth_mw)
```

The middleware runs `before_request` on every HTTP request and sets
`request.user`.

---

## 5. Getting the Current Identity

### In a resource/service handler:

```python
request.user              # Identity or AnonymousIdentity
request.user.id           # any JSON-serialisable value (or None)
request.user.name         # optional display name
request.user.email        # optional email
request.user.is_authenticated   # True / False
request.user.is_anonymous       # True / False
request.user.attributes        # dict of application-defined data
request.user.to_dict()         # JSON-safe snapshot
```

### In WebContext:

Not needed — `request.user` is the single canonical API.

---

## 6. Protected Endpoints

Two ways to require authentication:

### Option A: `authentication_required = True` on a Resource

```python
class ProductResource(CrudApiResource):
    name = "product"
    authentication_required = True     # every endpoint checks auth
```

Anonymous requests receive `401 UNAUTHENTICATED` immediately.

### Option B: Check in individual handlers

```python
class ProductResource(ApiResource):
    def endpoints(self):
        return [("GET", "/public", self.public), ("GET", "/secret", self.secret)]

    async def public(self, request, context):
        return ApiResponse.success({"message": "public"})

    async def secret(self, request, context):
        self.require_authentication(request)  # raises 401 if anonymous
        # ... authenticated-only logic ...
```

---

## 7. Error Handling

| Error                  | Code              | HTTP Status |
|------------------------|-------------------|-------------|
| `UnauthenticatedError` | `UNAUTHENTICATED` | 401         |
| `AuthenticationError`  | `AUTHENTICATION_ERROR` | (depends on context) |

Both inherit from the existing error hierarchy (`BetrayerError` →
`AuthenticationError` / `WebError` → `UnauthenticatedError`), so the standard
error envelope and error handler work without configuration:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "UNAUTHENTICATED",
    "message": "Authentication is required to access this resource"
  }
}
```

---

## 8. Container / DI Integration

```python
# Register
app.container.singleton("authenticator", my_authenticator)

# Resolve
authenticator = app.container.resolve("authenticator")
```

The middleware resolves by reference when constructed, or you can wire it
lazily via the container.

---

## 9. Flow Diagram

```
Incoming Request
    │
    ▼
FlaskAdapter starts the view
    │
    ▼
AuthenticationMiddleware.before_request(request, context)
    │  ├─ has authenticator → authenticate(request)
    │  │    ├─ returns Identity  → request.user = Identity
    │  │    └─ returns None      → request.user = AnonymousIdentity
    │  └─ no authenticator → request.user = AnonymousIdentity
    │
    ▼
Resource handler (e.g. ProductResource.list_handler)
    │  ├─ authentication_required=True & anonymous → 401 UNAUTHENTICATED
    │  └─ authenticated or not required → continues to Service
    │
    ▼
Service → Response
```

---

## 10. What This Is NOT

- **Not authorization.**  No roles, permissions, RBAC, ACL.
- **Not JWT.**  No JWT encode/decode/verify built in.
- **Not OAuth/OIDC.**  No identity provider integration.
- **Not sessions.**  No session database or cookies.
- **Not user management.**  No User model, registration, password hashing,
  password reset.
- **Not a second authentication subsystem.**  Reuses the existing
  Container/DI, Middleware, WebPipeline, Resource, Error contract, and
  Diagnostics.

Authorization is a separate capability (Betrayer Task 16.2).

---

## 11. Testing

```python
from betrayer.auth import Identity, AnonymousIdentity

# Identity tests
identity = Identity(id=1, name="Test")
assert identity.is_authenticated
assert not identity.is_anonymous

anon = AnonymousIdentity()
assert not anon.is_authenticated
assert anon.is_anonymous

# Authenticator tests
from betrayer.auth import HeaderTokenAuthenticator

def resolve(token):
    return Identity(id=42) if token == "valid" else None

auth = HeaderTokenAuthenticator(resolver=resolve)

# With Betrayer Request
from betrayer.web import Request
request = Request()
# ... mock header and test ...

# Container integration
app.container.singleton("authenticator", auth)
assert app.container.has("authenticator")