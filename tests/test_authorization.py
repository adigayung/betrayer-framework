"""Focused tests for Betrayer Authorization (Task 16.2).

Tests cover:

* Authorizer allow / deny
* explicit ``authorize()`` check (allow → continue, deny → ForbiddenError)
* authenticated vs anonymous identity behaviour
* protected resource (declarative ``authorization_required``)
* allowed access, denied access → 403 FORBIDDEN
* 401 still originates from authentication
* structured error envelope (no new error format)
* Container/DI integration (canonical ``"authorizer"`` key)
* existing unprotected resources keep working
* no sensitive information leaks in denial errors
* middleware ordering: Authentication before Authorization
* regression: existing Resource/API behaviour
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from betrayer.application import BetrayerApplication
from betrayer.bootstrap import Bootstrap

# -- auth imports ---------------------------------------------------------
from betrayer.auth import (
    AllowAllAuthorizer,
    AnonymousIdentity,
    AuthenticationMiddleware,
    AuthorizationMiddleware,
    Authorizer,
    CallbackAuthorizer,
    CallbackAuthenticator,
    HeaderTokenAuthenticator,
    Identity,
    authorize,
)
from betrayer.auth.authorization import DEFAULT_AUTHORIZER_KEY
from betrayer.auth.errors import UnauthenticatedError
from betrayer.web.exceptions import ForbiddenError

# -- web imports (existing pipeline) --------------------------------------
from betrayer.web import (
    ApiResource,
    ApiResponse,
    CrudApiResource,
    Request,
    WebContext,
    WebMiddlewareRegistry,
)
from betrayer.web.errors import web_error_to_response
from betrayer.web.middleware import WebPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request() -> Request:
    """Minimal Request (no Flask needed) with a stub raw request."""
    request = Request()
    request._raw = type(
        "StubFlaskRequest",
        (),
        {
            "headers": type("_H", (), {"get": lambda self, n, d="": d, "keys": lambda self: []})(),
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


def _make_context(request: Request) -> WebContext:
    app = BetrayerApplication(name="test-authz")
    Bootstrap(app).build()
    route = type("Route", (), {"module": "test", "endpoint": "test.handler"})()
    return WebContext(application=app, adapter=None, request=request, route=route)


class DenyAllAuthorizer(Authorizer):
    """Always denies — the deterministic counter-example."""

    def authorize(self, identity, action, resource=None, context=None) -> bool:
        return False


class ViewOnlyAuthorizer(Authorizer):
    """Allows only ``action == "view"`` on any resource."""

    def authorize(self, identity, action, resource=None, context=None) -> bool:
        return action == "view"


# ---------------------------------------------------------------------------
# 1/2. Authorizer allow / deny
# ---------------------------------------------------------------------------


class TestAuthorizerPolicy:
    def test_authorizer_allow(self) -> None:
        identity = Identity(id=1)
        assert ViewOnlyAuthorizer().authorize(identity, "view") is True

    def test_authorizer_deny(self) -> None:
        identity = Identity(id=1)
        assert ViewOnlyAuthorizer().authorize(identity, "update") is False

    def test_callback_authorizer(self) -> None:
        policy = CallbackAuthorizer(lambda identity, action, resource, context: action != "delete")
        assert policy.authorize(Identity(id=1), "view") is True
        assert policy.authorize(Identity(id=1), "delete") is False

    def test_allow_all_rejects_anonymous(self) -> None:
        assert AllowAllAuthorizer().authorize(Identity(id=1), "view") is True
        assert AllowAllAuthorizer().authorize(AnonymousIdentity(), "view") is False

    def test_subclass_contract(self) -> None:
        """Authorizer is an ABC with the canonical single method."""
        assert issubclass(DenyAllAuthorizer, Authorizer)
        assert callable(DenyAllAuthorizer().describe)


# ---------------------------------------------------------------------------
# 5. Explicit authorization check
# ---------------------------------------------------------------------------


class TestExplicitAuthorize:
    def test_allow_continues(self) -> None:
        """Allowed → returns None, nothing is raised."""
        authorize(Identity(id=1), "view", authorizer=ViewOnlyAuthorizer())

    def test_deny_raises_forbidden(self) -> None:
        with pytest.raises(ForbiddenError) as exc_info:
            authorize(Identity(id=1), "update", authorizer=DenyAllAuthorizer())
        assert exc_info.value.http_status == 403
        assert exc_info.value.code == "FORBIDDEN"

    def test_deny_with_resource_object(self) -> None:
        with pytest.raises(ForbiddenError) as exc_info:
            authorize(Identity(id=1), "update", resource={"id": 7}, authorizer=DenyAllAuthorizer())
        # context carries only the action and the resource TYPE, never values
        assert exc_info.value.context["action"] == "update"
        assert exc_info.value.context["resource_type"] == "dict"

    def test_no_authorizer_is_explicit_failure(self) -> None:
        """Missing DI wiring is a loud configuration error, never an allow."""
        with pytest.raises(RuntimeError):
            authorize(Identity(id=1), "view", context=None)

    def test_resolves_from_context_container(self) -> None:
        context = _make_context(_make_request())
        context.container.instance(DEFAULT_AUTHORIZER_KEY, ViewOnlyAuthorizer())
        authorize(Identity(id=1), "view", context=context)  # allowed
        with pytest.raises(ForbiddenError):
            authorize(Identity(id=1), "update", context=context)  # denied


# ---------------------------------------------------------------------------
# 3/4. Authenticated vs anonymous identity
# ---------------------------------------------------------------------------


class TestIdentityInAuthorization:
    def test_authenticated_identity_passes(self) -> None:
        authorize(Identity(id=1), "view", authorizer=AllowAllAuthorizer())

    def test_anonymous_identity_denied(self) -> None:
        with pytest.raises(ForbiddenError):
            authorize(AnonymousIdentity(), "view", authorizer=AllowAllAuthorizer())

    def test_authorizer_receives_request_user(self) -> None:
        """The identity given to the authorizer IS request.user (no new identity)."""
        request = _make_request()
        identity = Identity(id=42)
        request.set_user(identity)
        seen: list = []

        class Recorder(Authorizer):
            def authorize(self, identity, action, resource=None, context=None) -> bool:
                seen.append(identity)
                return True

        context = _make_context(request)
        authorize(request.user, "view", context=context, authorizer=Recorder())
        assert seen == [identity]


# ---------------------------------------------------------------------------
# 6/7/8. Protected resource: allow / deny / 403
# ---------------------------------------------------------------------------


class ProductsResource(CrudApiResource):
    name = "product"
    authorization_required = True
    authorization_action = "view"
    authorization_actions = {"POST": "create", "PUT": "update", "DELETE": "delete"}

    def __init__(self, *, service: Any) -> None:
        super().__init__(service_key="product_service")
        self.service = service


class TestProtectedResource:
    def _resource(self) -> ProductsResource:
        class _Service:
            def list(self):
                return [{"id": 1, "name": "widget"}]

            def get(self, identifier):
                return None

        return ProductsResource(service=_Service())

    def test_allowed_resource_access(self) -> None:
        import asyncio

        request = _make_request()
        request.set_user(Identity(id=1))
        context = _make_context(request)
        context.container.instance(DEFAULT_AUTHORIZER_KEY, ViewOnlyAuthorizer())

        response = asyncio.run(self._resource().list_handler(request, context))
        assert response.status == 200
        payload = json.loads(response.body)
        assert payload["success"] is True

    def test_denied_resource_access_raises_403(self) -> None:
        import asyncio

        request = _make_request()
        request.set_user(Identity(id=1))
        context = _make_context(request)
        context.container.instance(DEFAULT_AUTHORIZER_KEY, DenyAllAuthorizer())

        with pytest.raises(ForbiddenError) as exc_info:
            asyncio.run(self._resource().list_handler(request, context))
        assert exc_info.value.http_status == 403
        assert exc_info.value.code == "FORBIDDEN"

    def test_unprotected_resource_is_untouched(self) -> None:
        """A resource without the flag never runs an authorization check."""

        class OpenResource(ApiResource):
            name = "open"
            authentication_required = False
            authorization_required = False

        resource = OpenResource()
        request = _make_request()  # anonymous
        context = _make_context(request)
        # No authorizer registered, no flag set: must NOT raise anything.
        resource._enforce_authorization(request, context)
        resource.require_authorization(request, context)


# ---------------------------------------------------------------------------
# 9. 401 still comes from authentication
# ---------------------------------------------------------------------------


class TestAuthenticationStaysSeparate:
    def test_401_originates_from_authentication(self) -> None:
        resource = ApiResource()
        resource.authentication_required = True
        request = _make_request()  # anonymous
        with pytest.raises(UnauthenticatedError) as exc_info:
            resource._enforce_authentication(request)
        assert exc_info.value.http_status == 401
        assert exc_info.value.code == "UNAUTHENTICATED"

    def test_authorization_never_raises_401(self) -> None:
        """Authorization answers 'not allowed' (403), never 'who are you' (401)."""
        request = _make_request()
        request.set_user(AnonymousIdentity())
        context = _make_context(request)
        with pytest.raises(ForbiddenError) as exc_info:
            authorize(request.user, "view", context=context, authorizer=AllowAllAuthorizer())
        assert exc_info.value.http_status != 401

    def test_authentication_and_authorization_are_distinct_errors(self) -> None:
        assert UnauthenticatedError().http_status == 401
        assert ForbiddenError().http_status == 403
        assert UnauthenticatedError().code == "UNAUTHENTICATED"
        assert ForbiddenError().code == "FORBIDDEN"


# ---------------------------------------------------------------------------
# 10. Structured error envelope (existing format)
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    def test_forbidden_uses_existing_envelope(self) -> None:
        response = web_error_to_response(ForbiddenError(message="Not allowed to perform 'update'"))
        payload = json.loads(response.body)
        assert response.status == 403
        assert payload["success"] is False
        assert payload["data"] is None
        assert payload["error"]["code"] == "FORBIDDEN"
        assert payload["error"]["message"] == "Not allowed to perform 'update'"

    def test_deny_via_authorize_maps_to_envelope(self) -> None:
        try:
            authorize(Identity(id=1), "update", authorizer=DenyAllAuthorizer())
        except ForbiddenError as error:
            response = web_error_to_response(error)
            assert response.status == 403
            payload = json.loads(response.body)
            assert payload["error"]["code"] == "FORBIDDEN"
        else:  # pragma: no cover
            pytest.fail("deny must raise ForbiddenError")


# ---------------------------------------------------------------------------
# 11. DI / Container integration
# ---------------------------------------------------------------------------


class TestContainerIntegration:
    def test_authorizer_registration(self) -> None:
        app = BetrayerApplication(name="test-authz-di")
        Bootstrap(app).build()

        authorizer = ViewOnlyAuthorizer()
        app.container.instance("authorizer", authorizer)

        assert app.container.has("authorizer")
        assert app.container.resolve("authorizer") is authorizer

    def test_authorize_uses_container_authorizer(self) -> None:
        request = _make_request()
        request.set_user(Identity(id=1))
        context = _make_context(request)
        context.container.instance("authorizer", DenyAllAuthorizer())

        with pytest.raises(ForbiddenError):
            authorize(request.user, "view", context=context)


# ---------------------------------------------------------------------------
# 13. No sensitive information leaks
# ---------------------------------------------------------------------------


class TestNoInformationLeak:
    def test_denial_context_has_no_resource_values(self) -> None:
        resource = {"id": 7, "name": "secret-product", "price": 9999}
        try:
            authorize(Identity(id=1), "update", resource=resource, authorizer=DenyAllAuthorizer())
        except ForbiddenError as error:
            dumped = json.dumps({"context": dict(error.context), "message": error.message})
            assert "secret-product" not in dumped
            assert "9999" not in dumped
            assert error.context["action"] == "update"
        else:  # pragma: no cover
            pytest.fail("deny must raise ForbiddenError")

    def test_describe_does_not_leak(self) -> None:
        class Policy(Authorizer):
            def authorize(self, identity, action, resource=None, context=None) -> bool:
                return False

        info = json.dumps(Policy().describe())
        assert "secret" not in info


# ---------------------------------------------------------------------------
# 14. Middleware ordering: Authentication -> Authorization
# ---------------------------------------------------------------------------


class OrderedRecorder:
    """Middleware that records when it ran (helper for ordering assertions)."""

    def __init__(self, name: str, log: list) -> None:
        self.name = name
        self._log = log

    def before_request(self, request: Any, context: Any) -> None:
        self._log.append(self.name)


class TestMiddlewareOrdering:
    def test_authorization_runs_after_authentication(self) -> None:
        request = _make_request()
        context = _make_context(request)
        log: list = []

        pipeline = WebPipeline(
            middleware=[
                OrderedRecorder("authentication", log),
                OrderedRecorder("authorization", log),
            ],
            request=request,
            context=context,
        )

        def handler():
            return "ok"

        pipeline.run(handler)
        assert log == ["authentication", "authorization"]

    def test_priority_ordering_is_deterministic(self) -> None:
        """AuthenticationMiddleware.priority(0) < AuthorizationMiddleware.priority(10)."""
        assert AuthenticationMiddleware.priority < AuthorizationMiddleware.priority

    def test_authorization_middleware_checks_flagged_route(self) -> None:
        request = _make_request()
        identity = Identity(id=1)
        request.set_user(identity)

        route = type(
            "Route",
            (),
            {
                "module": "test",
                "authorization_required": True,
                "authorization_action": "update",
                "authorization_resource_key": None,
                "metadata": {},
            },
        )()
        request.route = route
        context = _make_context(request)
        context.container.instance(DEFAULT_AUTHORIZER_KEY, DenyAllAuthorizer())

        middleware = AuthorizationMiddleware()
        with pytest.raises(ForbiddenError):
            middleware.before_request(request, context)

    def test_authorization_middleware_skips_unflagged_route(self) -> None:
        request = _make_request()  # anonymous, route without the flag
        context = _make_context(request)
        # No authorizer registered: untouched route must not raise.
        AuthorizationMiddleware().before_request(request, context)


# ---------------------------------------------------------------------------
# 12/15. Regression: existing Resource/API keeps working
# ---------------------------------------------------------------------------


class TestRegression:
    def test_unprotected_resource_access(self) -> None:
        import asyncio

        class PublicResource(CrudApiResource):
            name = "public"

            def __init__(self) -> None:
                super().__init__(service=PublicResource.Service())

            class Service:
                def list(self):
                    return []

        request = _make_request()  # anonymous
        context = _make_context(request)
        response = asyncio.run(PublicResource().list_handler(request, context))
        assert response.status == 200
        payload = json.loads(response.body)
        assert payload["success"] is True
        assert payload["data"] == []

    def test_authentication_middleware_unchanged(self) -> None:
        request = _make_request()
        authenticator = CallbackAuthenticator(lambda req: Identity(id=5))
        AuthenticationMiddleware(authenticator=authenticator).before_request(
            request, None
        )
        assert request.user.is_authenticated is True
        assert request.user.id == 5

    def test_authentication_middleware_anonymous_fallback(self) -> None:
        request = _make_request()
        AuthenticationMiddleware().before_request(request, None)
        assert isinstance(request.user, AnonymousIdentity)

    def test_middleware_registry_describe_introspection(self) -> None:
        registry = WebMiddlewareRegistry()
        registry.add(AuthenticationMiddleware())
        registry.add(AuthorizationMiddleware())
        rows = registry.describe()
        names = [row["name"] for row in rows]
        assert names.index("authentication") < names.index("authorization")
