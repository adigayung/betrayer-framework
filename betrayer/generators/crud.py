"""CRUD generator for the Betrayer Framework.

Creates a complete CRUD resource package inside an existing Betrayer project.
A CRUD resource composes the existing Betrayer abstractions -- model
(:class:`betrayer.data.models.Model`), repository
(:class:`betrayer.data.repository.Repository`), a business *service* layer,
and web routes (:class:`betrayer.web.routing.WebRouter`) -- all integrated
with a :class:`betrayer.core.module.Module`.

The CRUD generator intentionally extends the resource stack: the resource
generator already covers ``model -> repository -> routes -> module``; CRUD
adds the *service* layer between the repository and the routes.  Handlers stay
thin and resolve the service through the request ``WebContext`` (the Framework
container), which is the documented handler signature ``handler(request,
context)`` from :mod:`betrayer.web.routing`.

Example usage::

    bet make crud product
    bet make crud order-item --force
    bet make crud blog-post --json
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from betrayer.generators.base import (
    BaseGenerator,
    GeneratorError,
    GeneratorOutput,
    package_name,
    title_case,
    validate_project_name,
)

__all__ = ["CrudGenerator", "validate_crud_name", "CRUD_VERSION"]

#: Initial version assigned to a freshly generated CRUD resource.
CRUD_VERSION = "0.1.0"


def validate_crud_name(name: str) -> Optional[str]:
    """Return a human readable error message, or ``None`` when ``name`` is OK.

    CRUD resource names follow the same convention as project / module /
    resource / service names (letters, digits, ``-`` and ``_``; must start
    with a letter) so the CLI surface stays consistent.  The message is
    phrased in terms of a *resource* though.
    """
    error = validate_project_name(name)
    if error:
        return error.replace("project name", "resource name")
    return None


class CrudGenerator(BaseGenerator):
    """Generate a new CRUD resource package.

    ``name`` is the name chosen on the command line; the importable package is
    the ``snake_case`` form of ``name`` (so ``bet make crud blog-post``
    produces ``blog_post/``).  Generated class names follow the existing
    convention::

        <TitleCase>Model          the data model
        <TitleCase>Repository     the repository (CRUD operations)
        <TitleCase>Service        the business service layer
        <TitleCase>CrudModule     the resource module

    The module registers ``<snake_case>`` and ``<snake_case>_service`` on the
    application container so routes can resolve them through ``WebContext``.
    """

    name = "crud"
    description = "Create a complete CRUD resource (model + repository + service + routes) in the current project"

    def __init__(
        self,
        name: str,
        output_dir: Path,
        overwrite: bool = False,
    ) -> None:
        error = validate_crud_name(name)
        if error:
            raise GeneratorError(f"invalid resource name: {error}")
        self.requested_name = name
        self.package = package_name(name)
        super().__init__(output_dir=Path(output_dir) / self.package, overwrite=overwrite)

    @property
    def target(self) -> Path:
        """The directory the new CRUD resource package is created in."""
        return self.output_dir

    @property
    def resource_name(self) -> str:
        """The resource's package name (snake_case)."""
        return self.package

    @property
    def model_class_name(self) -> str:
        """Name of the generated :class:`~betrayer.data.models.Model` subclass."""
        return f"{title_case(self.package)}Model"

    @property
    def repository_class_name(self) -> str:
        """Name of the generated :class:`~betrayer.data.repository.Repository` subclass."""
        return f"{title_case(self.package)}Repository"

    @property
    def service_class_name(self) -> str:
        """Name of the generated service class."""
        return f"{title_case(self.package)}Service"

    @property
    def service_key(self) -> str:
        """The container service name for the CRUD service."""
        return f"{self.package}_service"

    @property
    def repository_key(self) -> str:
        """The container service name for the repository."""
        return f"{self.package}_repository"

    @property
    def module_class_name(self) -> str:
        """Name of the generated :class:`~betrayer.core.module.Module` subclass."""
        return f"{title_case(self.package)}CrudModule"

    @property
    def table_name(self) -> str:
        """Pluralised database table name convention."""
        pkg = self.package
        if pkg.endswith("s"):
            return f"{pkg}es"
        if pkg.endswith("y"):
            return f"{pkg[:-1]}ies"
        return f"{pkg}s"

    # ── structure ──────────────────────────────────────────────────────

    def _files(self) -> Dict[str, str]:
        """Deterministic mapping of relative path -> file content."""
        return {
            "__init__.py": self._init_py(),
            "models.py": self._models_py(),
            "repository.py": self._repository_py(),
            "service.py": self._service_py(),
            "routes.py": self._routes_py(),
            "module.py": self._module_py(),
        }

    def _init_py(self) -> str:
        model_cls = self.model_class_name
        repo_cls = self.repository_class_name
        service_cls = self.service_class_name
        module_cls = self.module_class_name
        return f'''"""The ``{self.resource_name}`` CRUD resource package.

Generated by ``bet make crud {self.requested_name}``.

Public API::

    {model_cls}           the data model (a ``Model`` subclass)
    {repo_cls}            the repository (a ``Repository`` subclass)
    {service_cls}         the business service layer
    {module_cls}          the CRUD module (a ``Module`` subclass)
    router                the ``WebRouter`` with CRUD routes

Register it on an application::

    from {self.resource_name} import {module_cls}

    app.modules.register({module_cls})
"""

from __future__ import annotations

from {self.resource_name}.models import {model_cls}
from {self.resource_name}.module import {module_cls}
from {self.resource_name}.repository import {repo_cls}
from {self.resource_name}.service import {service_cls}

__all__ = [
    "{model_cls}",
    "{repo_cls}",
    "{service_cls}",
    "{module_cls}",
]
'''

    def _models_py(self) -> str:
        pkg = self.package
        cls = self.model_class_name
        table = self.table_name
        return f'''"""The ``{pkg}`` data model.

Generated by ``bet make crud {self.requested_name}``.

Defines the :class:`{cls}` data structure using the framework's
:class:`betrayer.data.models.Model` and :class:`~betrayer.data.models.Field`
abstractions.  Extend with additional fields as needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from betrayer.data.models import Field, Model

__all__ = ["{cls}"]


class {cls}(Model):
    """Data model for a ``{pkg}`` resource.

    Fields are declared as class-level :class:`~betrayer.data.models.Field`
    instances.  This is the single source of truth for the resource's shape.
    """

    # -- metadata (auto-managed) --
    id: int = Field(int, required=True, description="Primary key")
    created_at: datetime = Field(datetime, default=None, description="Creation timestamp")
    updated_at: datetime = Field(datetime, default=None, description="Last update timestamp")

    # -- resource fields (customise as needed) --
    name: str = Field(str, required=True, description="Display name of the {pkg}")
    description: str = Field(str, default="", description="Optional description")

    # -- introspection helpers --

    @classmethod
    def resource_metadata(cls) -> Dict[str, Any]:
        """Return deterministic metadata about this model."""
        return {{
            "resource": "{pkg}",
            "model": cls.__name__,
            "fields": [f.to_dict() for f in cls._fields.values()],
            "table": "{table}",
        }}
'''

    def _repository_py(self) -> str:
        pkg = self.package
        model_cls = self.model_class_name
        repo_cls = self.repository_class_name
        return f'''"""Repository for the ``{pkg}`` resource.

Generated by ``bet make crud {self.requested_name}``.

Provides CRUD operations (:meth:`get`, :meth:`find`, :meth:`list`,
:meth:`create`, :meth:`update`, :meth:`delete`) for the
:class:`{model_cls}` model.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from betrayer.core.container import Container
from betrayer.data.database import DatabaseManager
from betrayer.data.repository import Repository
from {self.resource_name}.models import {model_cls}

__all__ = ["{repo_cls}"]


class {repo_cls}(Repository[{model_cls}]):
    """CRUD repository for the ``{pkg}`` resource.

    Extend with resource-specific query methods as needed.
    """

    def __init__(
        self,
        database: DatabaseManager,
        container: Optional[Container] = None,
    ) -> None:
        super().__init__(model_class={model_cls}, database=database, container=container)

    # -- introspection --

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata."""
        base = super().introspect()
        base["resource"] = "{pkg}"
        return base
'''

    def _service_py(self) -> str:
        pkg = self.package
        repo_cls = self.repository_class_name
        service_cls = self.service_class_name
        return f'''"""Business service for the ``{pkg}`` CRUD resource.

Generated by ``bet make crud {self.requested_name}``.

The service sits between the web handlers and the repository: handlers stay
thin and delegates to this class, which owns the business logic for the
``{pkg}`` resource.  It is resolved from the application container under the
name ``{self.service_key}``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from {self.resource_name}.repository import {repo_cls}

__all__ = ["{service_cls}"]


class {service_cls}:
    """Business service for the ``{pkg}`` resource.

    ``repository`` is injected (resolved from the framework container) so this
    class stays unit-testable without web or database wiring.
    """

    name = "{self.service_key}"

    def __init__(self, repository: {repo_cls}) -> None:
        self._repository = repository

    @property
    def repository(self) -> {repo_cls}:
        """The underlying repository instance."""
        return self._repository

    # -- CRUD operations (thin, explicit delegation) --

    def get(self, identifier: Any) -> Optional[Any]:
        """Retrieve a single record by primary identifier."""
        return self._repository.get(identifier)

    def find(self, **filters: Any) -> Sequence[Any]:
        """Find records matching the given field/value filters."""
        return self._repository.find(**filters)

    def list(self) -> Sequence[Any]:
        """Return all records for the managed model."""
        return self._repository.list()

    def create(self, **data: Any) -> Any:
        """Create a new record from ``data``."""
        model_class = self._repository.model_class
        model = model_class.from_dict(data)
        return self._repository.create(model)

    def update(self, identifier: Any, **data: Any) -> Any:
        """Update the record ``identifier`` with ``data``."""
        model = self._repository.get(identifier)
        if model is None:
            return None
        for key, value in data.items():
            setattr(model, key, value)
        return self._repository.update(model)

    def delete(self, identifier: Any) -> bool:
        """Delete a record by identifier. Returns True if deleted."""
        return self._repository.delete(identifier)

    # -- introspection --

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata."""
        return {{
            "type": "service",
            "name": self.name,
            "class": type(self).__name__,
            "resource": "{pkg}",
            "repository": "{repo_cls}",
        }}
'''

    def _routes_py(self) -> str:
        pkg = self.package
        table = self.table_name
        return f'''"""Web routes for the ``{pkg}`` CRUD resource.

Generated by ``bet make crud {self.requested_name}``.

Provides standard RESTful CRUD endpoints.  Handlers use the documented
``handler(request, context)`` signature from :mod:`betrayer.web.routing` and
delegate to the {pkg} service resolved through the ``WebContext`` container
(``context.resolve("{self.service_key}")``).
"""

from __future__ import annotations

from typing import Any

from betrayer.web.context import WebContext
from betrayer.web.request import Request
from betrayer.web.response import ApiResponse, Response
from betrayer.web.routing import WebRouter

__all__ = ["router", "register_routes"]

router = WebRouter(name="{pkg}")


# -- handlers -------------------------------------------------------


async def list_{pkg}(request: Request, context: WebContext) -> Response:
    """GET /{table} -- list all {pkg} resources."""
    service = context.resolve("{self.service_key}")
    items = [item.to_dict() for item in service.list()]
    return ApiResponse.success(data=items, meta={{"resource": "{pkg}", "count": len(items)}})


async def get_{pkg}(request: Request, context: WebContext) -> Response:
    """GET /{table}/<id> -- retrieve a single {pkg} resource."""
    service = context.resolve("{self.service_key}")
    item = service.get(request.param("id"))
    if item is None:
        return ApiResponse.error("RESOURCE_NOT_FOUND", "{pkg} not found", status=404)
    return ApiResponse.success(data=item.to_dict())


async def create_{pkg}(request: Request, context: WebContext) -> Response:
    """POST /{table} -- create a new {pkg} resource."""
    service = context.resolve("{self.service_key}")
    item = service.create(**request.json)
    return ApiResponse.success(data=item.to_dict(), status=201)


async def update_{pkg}(request: Request, context: WebContext) -> Response:
    """PUT /{table}/<id> -- update an existing {pkg} resource."""
    service = context.resolve("{self.service_key}")
    item = service.update(request.param("id"), **request.json)
    if item is None:
        return ApiResponse.error("RESOURCE_NOT_FOUND", "{pkg} not found", status=404)
    return ApiResponse.success(data=item.to_dict())


async def delete_{pkg}(request: Request, context: WebContext) -> Response:
    """DELETE /{table}/<id> -- delete a {pkg} resource."""
    service = context.resolve("{self.service_key}")
    deleted = service.delete(request.param("id"))
    if not deleted:
        return ApiResponse.error("RESOURCE_NOT_FOUND", "{pkg} not found", status=404)
    return Response.no_content()


# -- registration ---------------------------------------------------


def register_routes(web_router: WebRouter, prefix: str = "") -> None:
    """Register all CRUD routes on an existing ``WebRouter``.

    Args:
        web_router: The target router to register routes on.
        prefix: Optional path prefix (e.g. ``"/api/v1"``).
    """
    base = f"{{prefix}}/{table}"
    web_router.get(base, list_{pkg})
    web_router.get(f"{{base}}/<id>", get_{pkg})
    web_router.post(base, create_{pkg})
    web_router.put(f"{{base}}/<id>", update_{pkg})
    web_router.delete(f"{{base}}/<id>", delete_{pkg})
'''

    def _module_py(self) -> str:
        pkg = self.package
        model_cls = self.model_class_name
        repo_cls = self.repository_class_name
        service_cls = self.service_class_name
        module_cls = self.module_class_name
        return f'''"""CRUD module for ``{pkg}``.

Generated by ``bet make crud {self.requested_name}``.

The CRUD module integrates the :class:`{model_cls}`,
:class:`{repo_cls}`, :class:`{service_cls}` and web routes into the Betrayer
module system.  It is the single point of registration for the resource on an
application: the repository and the service are registered on the container so
routes can resolve them through ``WebContext``.
"""

from __future__ import annotations

from typing import Any, Tuple

from betrayer.core.module import Module

from {self.resource_name}.models import {model_cls}
from {self.resource_name}.repository import {repo_cls}
from {self.resource_name}.service import {service_cls}

__all__ = ["{module_cls}"]


class {module_cls}(Module):
    """Betrayer module for the ``{pkg}`` CRUD resource.

    Registers the repository and the service on the application container.
    """

    name = "{pkg}"
    version = "{CRUD_VERSION}"
    dependencies: Tuple[str, ...] = ()
    services: Tuple[str, ...] = ("{self.repository_key}", "{self.service_key}")
    metadata = {{
        "description": "the {pkg} CRUD resource module",
        "model": "{model_cls}",
        "repository": "{repo_cls}",
        "service": "{service_cls}",
    }}

    def register(self, context: Any) -> None:
        """Declare the resource: register the repository and the service."""
        container = context.container

        def _build_repository() -> {repo_cls}:
            database = container.resolve("database")
            return {repo_cls}(database=database)

        container.singleton("{self.repository_key}", _build_repository)

        def _build_service() -> {service_cls}:
            repository = container.resolve("{self.repository_key}")
            return {service_cls}(repository=repository)

        container.singleton("{self.service_key}", _build_service)

    def initialize(self, context: Any) -> None:
        """Initialise the CRUD module."""

    def shutdown(self, context: Any) -> None:
        """Tear down the CRUD module."""
'''

    # ── generation ──────────────────────────────────────────────────────

    def generate(self) -> GeneratorOutput:
        """Create the CRUD resource package and every generated file.

        Raises :class:`GeneratorError` when the target already exists and is
        not empty and ``overwrite`` is False, so an existing resource is never
        overwritten silently.
        """
        if not self.overwrite and self._target_occupied():
            raise GeneratorError(
                "resource already exists (use --force to overwrite): "
                f"{self.output_dir}"
            )
        self._ensure_directory(self.output_dir)
        for relative, content in self._files().items():
            try:
                self._write(relative, content)
            except GeneratorError as exc:  # pragma: no cover - defensive
                self.output.add_error(relative, exc)
        return self.output

    def _target_occupied(self) -> bool:
        """True when the target directory exists and is not empty."""
        if not self.output_dir.exists():
            return False
        try:
            return any(self.output_dir.iterdir())
        except OSError:
            return True