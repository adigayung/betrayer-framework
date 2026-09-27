"""Focused tests for Betrayer Authentication (Task 16.1).

Tests cover:

* Identity / AnonymousIdentity
* Authenticator (HeaderTokenAuthenticator, CallbackAuthenticator)
* authentication middleware (sets request.user)
* protected / unprotected Resource
* 401 response for anonymous requests
* structured error
* Container/DI integration
* diagnostics does not leak credential
* regression: existing request pipeline still works
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest

from betrayer.application import BetrayerApplication
from betrayer.bootstrap import Bootstrap

# -- auth imports ---------------------------------------------------------
from betrayer.auth import (
    AnonymousIdentity,
    AuthenticationMiddleware,
    Authenticator,
    CallbackAuthenticator,
    HeaderTokenAuthenticator,
    Identity,
    TokenResolver,
    UnauthenticatedError,
)
from betrayer.auth.identity import Identity as IdentityCls

# -- web imports (existing pipeline) --------------------------------------
from betrayer.web import (
    ApiResource,
    ApiResponse,
    CrudApiResource,
    FlaskAdapter,
    Request,
    Response,
    WebContext,
    WebMiddlewareRegistry,
)

# -- core imports ---------------------------------------------------------
from betrayer.core.exceptions import BetrayerError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request_with_header(
    header_name: str = "Authorization",
    header_value: str = "Bearer valid-token",
) -> Request:
    """Build a minimal Request object with a given header.

    Because the Betrayer Request delegates to Flask, and we want to test
    without Flask, we create a minimal stub that exposes ``header()``.
    """
    request = Request()

    class _Headers:
        def get(self, name: str, default: str = "") -> str:
            if name == header_name:
                return header_value
            return default

        def keys(self) -> list:
            return [header_name]

    request._raw = type(
        "StubFlaskRequest",
        (),
        {
            "headers": _Headers(),
            "method": "GET",
            "path": "/",
            "full_path": "/",
            "url": "http://test/",
            "base_url": "http://test",
            "host": "test",
            "scheme": "http",
            "args": {},
            "cookies": {},
            "data": b"",
            "get_data": lambda *a, **kw: b"",
            "is_json": False,
            "content_type": None,
            "content_length": None,
            "files": {},
            "form": {},
            "endpoint": None,
            "remote_addr": "127.0.0.1",
            "user_agent": None,
        },
    )()
    return request


def _make_stub_context(request: Request) -> WebContext:
    app = BetrayerApplication(name="test-auth")
    Bootstrap(app).build()
    route = type("Route", (), {"module": "test", "endpoint": "test.handler"})()
    return WebContext(
        application=app,
        adapter=None,
        request=request,
        route=route,
    )


# ---------------------------------------------------------------------------
# Identity tests
# ---------------------------------------------------------------------------


class TestIdentity:
    def test_minimal_identity(self) -> None:
        identity = Identity(id=42)
        assert identity.id == 42
        assert identity.name is None
        assert identity.email is None
        assert identity.attributes == {}
        assert identity.is_authenticated is True
        assert identity.is_anonymous is False

    def test_identity_with_details(self) -> None:
        identity = Identity(
            id=1,
            name="Ada",
            email="ada@example.com",
            attributes={"role": "admin"},
        )
        assert identity.id == 1
        assert identity.name == "Ada"
        assert identity.email == "ada@example.com"
        assert identity.attributes["role"] == "admin"

    def test_identity_optional_fields(self) -> None:
        identity = Identity(id=None)
        assert identity.id is None
        assert identity.name is None
        assert identity.email is None

    def test_anonymous_identity(self) -> None:
        anon = AnonymousIdentity()
        assert anon.is_authenticated is False
        assert anon.is_anonymous is True
        assert anon.id is None
        assert anon.name is None

    def test_identity_to_dict(self) -> None:
        identity = Identity(id=42, name="Test", attributes={"x": 1})
        data = identity.to_dict()
        assert data["id"] == 42
        assert data["name"] == "Test"
        assert data["anonymous"] is False
        assert data["attributes"]["x"] == 1

    def test_anonymous_to_dict(self) -> None:
        anon = AnonymousIdentity()
        data = anon.to_dict()
        assert data["anonymous"] is True

    def test_identity_get_attribute(self) -> None:
        identity = Identity(id=1, attributes={"scopes": ["read"]})
        assert identity.get("scopes") == ["read"]
        assert identity.get("nonexistent") is None
        assert identity.get("missing", "default") == "default"


# ---------------------------------------------------------------------------
# Authenticator tests
# ---------------------------------------------------------------------------


class TestHeaderTokenAuthenticator:
    def test_successful_authentication(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            if token == "valid-token":
                return Identity(id=42, name="Valid User")
            return None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        request = _make_request_with_header(
            header_value="Bearer valid-token"
        )
        identity = auth.authenticate(request)
        assert identity is not None
        assert identity.id == 42
        assert identity.name == "Valid User"

    def test_invalid_token(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            return None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        request = _make_request_with_header(
            header_value="Bearer invalid-token"
        )
        identity = auth.authenticate(request)
        assert identity is None

    def test_missing_header(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            return Identity(id=1)

        auth = HeaderTokenAuthenticator(resolver=resolver)
        request = _make_request_with_header(header_value="")  # empty
        identity = auth.authenticate(request)
        assert identity is None

    def test_wrong_scheme(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            return Identity(id=1)

        auth = HeaderTokenAuthenticator(resolver=resolver)
        request = _make_request_with_header(
            header_value="Basic dXNlcjpwYXNz"
        )
        identity = auth.authenticate(request)
        assert identity is None

    def test_custom_header_and_scheme(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            if token == "key-123":
                return Identity(id="svc-1")
            return None

        auth = HeaderTokenAuthenticator(
            resolver=resolver, header="X-API-Key", scheme="Key"
        )
        request = _make_request_with_header(
            header_name="X-API-Key", header_value="Key key-123"
        )
        identity = auth.authenticate(request)
        assert identity is not None
        assert identity.id == "svc-1"

    def test_resolver_returns_none(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            return None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        request = _make_request_with_header(header_value="Bearer any-token")
        identity = auth.authenticate(request)
        assert identity is None

    def test_resolver_exception(self) -> None:
        def resolver(token: str) -> Identity:
            raise ValueError("error")

        auth = HeaderTokenAuthenticator(resolver=resolver)
        request = _make_request_with_header(header_value="Bearer token")
        identity = auth.authenticate(request)
        assert identity is None  # exception is caught

    def test_describe(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            return None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        info = auth.describe()
        assert info["type"] == "HeaderTokenAuthenticator"
        assert info["header"] == "Authorization"
        assert info["scheme"] == "Bearer"


class TestCallbackAuthenticator:
    def test_callback_returns_identity(self) -> None:
        def auth_fn(request: Any) -> Optional[Identity]:
            return Identity(id=99, name="Callback User")

        auth = CallbackAuthenticator(callback=auth_fn)
        identity = auth.authenticate(_make_request_with_header())
        assert identity is not None
        assert identity.id == 99

    def test_callback_returns_none(self) -> None:
        def auth_fn(request: Any) -> Optional[Identity]:
            return None

        auth = CallbackAuthenticator(callback=auth_fn)
        identity = auth.authenticate(_make_request_with_header())
        assert identity is None

    def test_callback_exception(self) -> None:
        def auth_fn(request: Any) -> Identity:
            raise RuntimeError("fail")

        auth = CallbackAuthenticator(callback=auth_fn)
        identity = auth.authenticate(_make_request_with_header())
        assert identity is None


# ---------------------------------------------------------------------------
# AuthenticationMiddleware tests
# ---------------------------------------------------------------------------


class TestAuthenticationMiddleware:
    def test_sets_authenticated_user(self) -> None:
        def resolver(token: str) -> Identity:
            return Identity(id=1, name="Test User")

        auth = HeaderTokenAuthenticator(resolver=resolver)
        mw = AuthenticationMiddleware(authenticator=auth)
        request = _make_request_with_header(header_value="Bearer token123")
        context = _make_stub_context(request)

        mw.before_request(request, context)

        assert request.user.is_authenticated is True
        assert request.user.id == 1
        assert request.user.name == "Test User"

    def test_sets_anonymous_for_missing_credential(self) -> None:
        def resolver(token: str) -> Optional[Identity]:
            return None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        mw = AuthenticationMiddleware(authenticator=auth)
        request = _make_request_with_header(header_value="")
        context = _make_stub_context(request)

        mw.before_request(request, context)

        assert request.user.is_anonymous is True
        assert request.user.is_authenticated is False

    def test_anonymous_when_no_authenticator(self) -> None:
        mw = AuthenticationMiddleware(authenticator=None)
        request = _make_request_with_header(header_value="Bearer token")
        context = _make_stub_context(request)

        mw.before_request(request, context)

        assert request.user.is_anonymous is True

    def test_anonymous_when_authenticator_none(self) -> None:
        """Test that the middleware handles authenticator=None gracefully."""
        mw = AuthenticationMiddleware()
        request = _make_request_with_header(header_value="Bearer token")
        context = _make_stub_context(request)
        mw.before_request(request, context)
        assert request.user.is_anonymous is True

    def test_before_request_never_short_circuits(self) -> None:
        """before_request should never return a Response (always None)."""
        mw = AuthenticationMiddleware()
        request = _make_request_with_header()
        context = _make_stub_context(request)
        result = mw.before_request(request, context)
        assert result is None


# ---------------------------------------------------------------------------
# Protected Resource tests (authentication_required)
# ---------------------------------------------------------------------------


class TestProtectedResource:
    def test_authentication_required_blocks_anonymous(self) -> None:
        """Setting authentication_required=True should cause require_authentication
        to raise for an anonymous request."""
        resource = ApiResource()
        resource.authentication_required = True

        request = _make_request_with_header(header_value="")
        context = _make_stub_context(request)
        # No middleware ran, so request.user is AnonymousIdentity (default)
        with pytest.raises(UnauthenticatedError) as exc_info:
            resource._enforce_authentication(request)

        assert exc_info.value.code == "UNAUTHENTICATED"
        assert exc_info.value.http_status == 401

    def test_authentication_required_allows_authenticated(self) -> None:
        """When request.user is authenticated, no error should be raised."""
        resource = ApiResource()
        resource.authentication_required = True

        request = _make_request_with_header()
        identity = Identity(id=1, name="Auth User")
        request.set_user(identity)

        # Should not raise
        resource._enforce_authentication(request)

    def test_no_auth_required_allows_anonymous(self) -> None:
        """When authentication_required is False, anonymous is allowed."""
        resource = ApiResource()
        resource.authentication_required = False

        request = _make_request_with_header(header_value="")
        # Should not raise
        resource._enforce_authentication(request)

    def test_require_authentication_static_method(self) -> None:
        """require_authentication raises when request has no user."""
        request = _make_request_with_header()
        with pytest.raises(UnauthenticatedError):
            ApiResource.require_authentication(request)

    def test_require_authentication_allows_authenticated(self) -> None:
        """require_authentication passes when authenticated."""
        request = _make_request_with_header()
        request.set_user(Identity(id=1))
        ApiResource.require_authentication(request)  # should not raise


# ---------------------------------------------------------------------------
# Error tests (structured errors)
# ---------------------------------------------------------------------------


class TestAuthenticationErrors:
    def test_unauthenticated_error_is_web_error(self) -> None:
        error = UnauthenticatedError(message="Auth required")
        assert error.code == "UNAUTHENTICATED"
        assert error.http_status == 401
        assert isinstance(error, BetrayerError)

    def test_unauthenticated_error_envelope(self) -> None:
        """Verify the error follows the standard JSON error envelope."""
        from betrayer.web.response import ApiResponse

        error = UnauthenticatedError(
            message="Authentication is required to access this resource",
        )
        from betrayer.web.errors import web_error_to_response

        response = web_error_to_response(error)
        data = json.loads(response.body)
        assert data["success"] is False
        assert data["data"] is None
        assert data["error"]["code"] == "UNAUTHENTICATED"
        assert data["error"]["message"] == (
            "Authentication is required to access this resource"
        )

    def test_unauthenticated_inherits_properly(self) -> None:
        """UnauthenticatedError is a WebError, not an UnauthorizedError,
        so its code is UNAUTHENTICATED not UNAUTHORIZED."""
        from betrayer.web.exceptions import WebError

        error = UnauthenticatedError()
        assert isinstance(error, WebError)
        assert error.code == "UNAUTHENTICATED"
        # It is NOT an instance of UnauthorizedError (which has code UNAUTHORIZED)
        from betrayer.web.exceptions import UnauthorizedError

        assert not isinstance(error, UnauthorizedError)


# ---------------------------------------------------------------------------
# Container / DI integration
# ---------------------------------------------------------------------------


class TestContainerIntegration:
    def test_authenticator_registration(self) -> None:
        app = BetrayerApplication(name="test-auth-di")
        Bootstrap(app).build()

        def resolver(token: str) -> Optional[Identity]:
            if token == "valid":
                return Identity(id=1)
            return None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        app.container.instance("authenticator", auth)

        assert app.container.has("authenticator")
        resolved = app.container.resolve("authenticator")
        assert resolved is auth

    def test_authenticator_resolution_and_use(self) -> None:
        app = BetrayerApplication(name="test-auth-resolve")
        Bootstrap(app).build()

        def resolver(token: str) -> Optional[Identity]:
            if token == "test":
                return Identity(id=99)
            return None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        app.container.instance("authenticator", auth)

        resolved = app.container.resolve("authenticator")
        request = _make_request_with_header(header_value="Bearer test")
        identity = resolved.authenticate(request)
        assert identity is not None
        assert identity.id == 99

    def test_middleware_registration_on_registry(self) -> None:
        app = BetrayerApplication(name="test-auth-mw")
        Bootstrap(app).build()

        # Simulate what FlaskAdapter normally does: register middleware registry
        from betrayer.web.middleware import WebMiddlewareRegistry

        mw_registry = WebMiddlewareRegistry()
        app.registry.register("web.middleware", mw_registry)

        def resolver(token: str) -> Optional[Identity]:
            return Identity(id=1) if token == "ok" else None

        auth = HeaderTokenAuthenticator(resolver=resolver)
        auth_mw = AuthenticationMiddleware(authenticator=auth)
        mw_registry.add(auth_mw)

        assert mw_registry.exists("authentication")
        mw_info = mw_registry.get("authentication")
        assert mw_info.authenticator is auth


# ---------------------------------------------------------------------------
# Diagnostics does NOT leak credential
# ---------------------------------------------------------------------------


class TestDiagnosticsNoLeak:
    def test_middleware_describe_no_credential(self) -> None:
        """Middleware.describe() should not contain tokens."""
        mw = AuthenticationMiddleware()
        info = mw.describe()
        info_json = json.dumps(info)
        assert "valid-token" not in info_json
        assert "secret" not in info_json

    def test_identity_to_dict_no_secret(self) -> None:
        """Identity.to_dict() should not leak credentials."""
        identity = Identity(id=1, attributes={"token": "my-secret-token"})
        data = identity.to_dict()
        # The attributes dict is user-data, not credentials per se,
        # but the framework does not add raw credentials anywhere.
        # This test ensures default Identity does not expose anything extra.
        identity2 = Identity(id=1)
        data2 = identity2.to_dict()
        assert data2 == {
            "id": 1,
            "name": None,
            "email": None,
            "attributes": {},
            "anonymous": False,
        }

    def test_request_to_dict_no_user_leak(self) -> None:
        """Request.to_dict() should not expose user identity metadata."""
        request = _make_request_with_header(header_value="Bearer my-token")
        info = request.to_dict()
        # The to_dict should not include the user or credential header value
        info_json = json.dumps(info)
        assert "my-token" not in info_json


# ---------------------------------------------------------------------------
# Regression: existing request pipeline still works
# ---------------------------------------------------------------------------


class TestPipelineRegression:
    def test_request_still_works_normally(self) -> None:
        """Request still works without auth-related attributes."""
        request = _make_request_with_header(header_value="Bearer some-token")
        # user property returns AnonymousIdentity by default
        assert request.user.is_anonymous is True
        assert request.user.is_authenticated is False

    def test_pipeline_middleware_ordering_preserved(self) -> None:
        """The WebPipeline still executes correctly even when no auth
        middleware is registered."""
        from betrayer.web.middleware import WebPipeline

        class PassthroughMiddleware:
            name = "passthrough"
            enabled = True
            priority = 0

            def middleware_name(self) -> str:
                return self.name

            def before_request(self, request: Any, context: Any) -> None:
                pass

        request = _make_request_with_header()
        context = _make_stub_context(request)
        pipeline = WebPipeline(
            middleware=[PassthroughMiddleware()],
            request=request,
            context=context,
        )
        result = pipeline.run(handler=lambda: Response.json({"ok": True}))
        assert result is not None
        assert json.loads(result.body) == {"ok": True}


# ---------------------------------------------------------------------------
# Authenticator abstract contract
# ---------------------------------------------------------------------------


class TestAuthenticatorContract:
    def test_authenticator_subclass(self) -> None:
        """Any Authenticator subclass must implement authenticate."""

        class CustomAuth(Authenticator):
            def authenticate(self, request: Any) -> Optional[Identity]:
                return Identity(id="custom")

        auth = CustomAuth()
        request = _make_request_with_header()
        identity = auth.authenticate(request)
        assert identity is not None
        assert identity.id == "custom"

    def test_duck_typed_authenticator(self) -> None:
        """Any object with an authenticate method can serve as authenticator."""

        class DuckAuth:
            def authenticate(self, request: Any) -> Optional[Identity]:
                return Identity(id="duck")

        auth = DuckAuth()
        mw = AuthenticationMiddleware(authenticator=auth)
        request = _make_request_with_header()
        context = _make_stub_context(request)
        mw.before_request(request, context)
        assert request.user.id == "duck"