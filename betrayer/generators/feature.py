"""Vertical-slice feature generator for the Betrayer Framework.

Creates a complete feature package with configurable components inside an existing
Betrayer project. A feature is a vertical slice that can include model, schema,
repository, service, routes, tests, and module - all integrated and ready to use.

This follows the LLM-FIRST principle: one command produces a working skeleton,
LLM fills in business logic. No multiple small generators to orchestrate.

Component selection (all optional, sensible defaults):

    --with-model         include models.py (default: True)
    --with-schema        include schema.py for validation (default: False)
    --with-repository    include repository.py (default: True)
    --with-service       include service.py (default: True)
    --with-routes        include routes.py (default: True)
    --with-tests         include tests/ directory (default: True)
    --minimal            only model + repository + module (no service/routes)
    --full               all components including schema and tests

Example usage::

    bet make feature orders
    bet make feature auth --full
    bet make feature notifications --minimal
    bet make feature products --with-schema --with-tests
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Set

from betrayer.generators.base import (
    BaseGenerator,
    GeneratorError,
    GeneratorOutput,
    package_name,
    title_case,
    validate_project_name,
)

__all__ = ["FeatureGenerator", "validate_feature_name", "FEATURE_VERSION"]

#: Initial version assigned to a freshly generated feature.
FEATURE_VERSION = "0.1.0"


def validate_feature_name(name: str) -> Optional[str]:
    """Return a human readable error message, or ``None`` when ``name`` is OK.

    Feature names follow the same convention as project names (letters, digits,
    ``-`` and ``_``; must start with a letter) so the CLI surface stays
    consistent. The message is phrased in terms of a *feature* though.
    """
    error = validate_project_name(name)
    if error:
        return error.replace("project name", "feature name")
    return None


class FeatureGenerator(BaseGenerator):
    """Generate a new vertical-slice feature package.

    ``name`` is the name chosen on the command line; the importable package is
    the ``snake_case`` form of ``name`` (so ``bet make feature blog-post``
    produces ``blog_post/``). Generated class names follow the existing
    convention::

        <TitleCase>Model          the data model (if --with-model)
        <TitleCase>Schema         the validation schema (if --with-schema)
        <TitleCase>Repository     the repository (if --with-repository)
        <TitleCase>Service        the business service (if --with-service)
        <TitleCase>FeatureModule  the feature module

    The module registers components on the application container so routes can
    resolve them through ``WebContext``.
    """

    name = "feature"
    description = "Create a complete vertical-slice feature (model + repository + service + routes + tests) in the current project"

    def __init__(
        self,
        name: str,
        output_dir: Path,
        overwrite: bool = False,
        *,
        with_model: bool = True,
        with_schema: bool = False,
        with_repository: bool = True,
        with_service: bool = True,
        with_routes: bool = True,
        with_tests: bool = True,
        minimal: bool = False,
        full: bool = False,
    ) -> None:
        error = validate_feature_name(name)
        if error:
            raise GeneratorError(f"invalid feature name: {error}")
        self.requested_name = name
        self.package = package_name(name)

        # Resolve component flags with precedence: minimal/full > explicit flags > defaults
        if minimal and full:
            # full wins if both are specified (defensive)
            minimal, full = False, True

        if minimal:
            self._components = {"model", "repository", "module"}
        elif full:
            self._components = {"model", "schema", "repository", "service", "routes", "tests", "module"}
        else:
            self._components: Set[str] = set()
            if with_model:
                self._components.add("model")
            if with_schema:
                self._components.add("schema")
            if with_repository:
                self._components.add("repository")
            if with_service:
                self._components.add("service")
            if with_routes:
                self._components.add("routes")
            if with_tests:
                self._components.add("tests")
            # Module is always included
            self._components.add("module")

        super().__init__(output_dir=Path(output_dir) / self.package, overwrite=overwrite)

    @property
    def target(self) -> Path:
        """The directory the new feature package is created in."""
        return self.output_dir

    @property
    def feature_name(self) -> str:
        """The feature's package name (snake_case)."""
        return self.package

    @property
    def model_class_name(self) -> str:
        """Name of the generated :class:`~betrayer.data.models.Model` subclass."""
        return f"{title_case(self.package)}Model"

    @property
    def schema_class_name(self) -> str:
        """Name of the generated :class:`~betrayer.web.validation.Schema` subclass."""
        return f"{title_case(self.package)}Schema"

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
        """The container service name for the feature service."""
        return f"{self.package}_service"

    @property
    def repository_key(self) -> str:
        """The container service name for the repository."""
        return f"{self.package}_repository"

    @property
    def module_class_name(self) -> str:
        """Name of the generated :class:`~betrayer.core.module.Module` subclass."""
        return f"{title_case(self.package)}FeatureModule"

    @property
    def table_name(self) -> str:
        """Pluralised database table name convention."""
        pkg = self.package
        if pkg.endswith("s"):
            return f"{pkg}es"
        if pkg.endswith("y"):
            return f"{pkg[:-1]}ies"
        return f"{pkg}s"

    @property
    def components(self) -> Set[str]:
        """The set of components to generate."""
        return self._components

    def has(self, component: str) -> bool:
        """Check if a component will be generated."""
        return component in self._components

    # ── structure ──────────────────────────────────────────────────────

    def _files(self) -> Dict[str, str]:
        """Deterministic mapping of relative path -> file content."""
        files: Dict[str, str] = {}

        files["__init__.py"] = self._init_py()
        files["module.py"] = self._module_py()

        if self.has("model"):
            files["models.py"] = self._models_py()

        if self.has("schema"):
            files["schema.py"] = self._schema_py()

        if self.has("repository"):
            files["repository.py"] = self._repository_py()

        if self.has("service"):
            files["service.py"] = self._service_py()

        if self.has("routes"):
            files["routes.py"] = self._routes_py()

        if self.has("tests"):
            files["tests/__init__.py"] = self._tests_init_py()
            files[f"tests/test_{self.package}_unit.py"] = self._tests_unit_py()
            files[f"tests/test_{self.package}_integration.py"] = self._tests_integration_py()

        return files

    def _init_py(self) -> str:
        exports = []
        if self.has("model"):
            exports.append(self.model_class_name)
        if self.has("schema"):
            exports.append(self.schema_class_name)
        if self.has("repository"):
            exports.append(self.repository_class_name)
        if self.has("service"):
            exports.append(self.service_class_name)
        exports.append(self.module_class_name)

        imports = []
        if self.has("model"):
            imports.append(f"from {self.feature_name}.models import {self.model_class_name}")
        if self.has("schema"):
            imports.append(f"from {self.feature_name}.schema import {self.schema_class_name}")
        if self.has("repository"):
            imports.append(f"from {self.feature_name}.repository import {self.repository_class_name}")
        if self.has("service"):
            imports.append(f"from {self.feature_name}.service import {self.service_class_name}")
        imports.append(f"from {self.feature_name}.module import {self.module_class_name}")

        return f'''"""The ``{self.feature_name}`` feature package.

Generated by ``bet make feature {self.requested_name}``.

Public API::

    {chr(10).join(f"    {exp}" for exp in exports)}

Register it on an application::

    from {self.feature_name} import {self.module_class_name}

    app.modules.register({self.module_class_name})
"""

from __future__ import annotations

{chr(10).join(imports)}

__all__ = {exports!r}
'''

    def _models_py(self) -> str:
        pkg = self.package
        cls = self.model_class_name
        table = self.table_name
        return f'''"""The ``{pkg}`` data model.

Generated by ``bet make feature {self.requested_name}``.

Defines the :class:`{cls}` data structure using the framework's
:class:`betrayer.data.models.Model` and :class:`~betrayer.data.models.Field`
abstractions. Extend with additional fields as needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from betrayer.data.models import Field, Model

__all__ = ["{cls}"]


class {cls}(Model):
    """Data model for a ``{pkg}`` feature.

    Fields are declared as class-level :class:`~betrayer.data.models.Field`
    instances. This is the single source of truth for the feature's shape.
    """

    # -- metadata (auto-managed) --
    id: int = Field(int, required=True, description="Primary key")
    created_at: datetime = Field(datetime, default=None, description="Creation timestamp")
    updated_at: datetime = Field(datetime, default=None, description="Last update timestamp")

    # -- feature fields (customise as needed) --
    name: str = Field(str, required=True, description="Display name of the {pkg}")

    # -- introspection helpers --

    @classmethod
    def resource_metadata(cls) -> Dict[str, Any]:
        """Return deterministic metadata about this model."""
        return {{
            "feature": "{pkg}",
            "model": cls.__name__,
            "fields": [f.to_dict() for f in cls._fields.values()],
            "table": "{table}",
        }}
'''

    def _schema_py(self) -> str:
        pkg = self.package
        cls = self.schema_class_name
        return f'''"""Validation schema for the ``{pkg}`` feature.

Generated by ``bet make feature {self.requested_name}``.

Defines the :class:`{cls}` validation schema using the framework's
:class:`betrayer.web.validation.Schema` and :class:`~betrayer.web.validation.Field`
abstractions. Attach to a resource for automatic request validation.
"""

from __future__ import annotations

from betrayer.web.validation import Field, Schema

__all__ = ["{cls}"]


class {cls}(Schema):
    """Validation schema for ``{pkg}`` feature data.

    Used by resources to validate POST/PUT requests before they reach
    the service layer. Fields declared here should match the model.
    """

    name = Field(str, required=True, min_length=1, max_length=255, description="Name of the {pkg}")
'''

    def _repository_py(self) -> str:
        pkg = self.package
        model_cls = self.model_class_name if self.has("model") else "dict"
        repo_cls = self.repository_class_name
        model_import = f"from {self.feature_name}.models import {model_cls}" if self.has("model") else ""
        return f'''"""Repository for the ``{pkg}`` feature.

Generated by ``bet make feature {self.requested_name}``.

Provides CRUD operations (:meth:`get`, :meth:`find`, :meth:`list`,
:meth:`create`, :meth:`update`, :meth:`delete`) for the
{model_cls if self.has("model") else 'feature data'}.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from betrayer.core.container import Container
from betrayer.data.database import DatabaseManager
from betrayer.data.repository import Repository
{model_import}

__all__ = ["{repo_cls}"]


class {repo_cls}(Repository[{model_cls}]):
    """Repository for the ``{pkg}`` feature.

    Extend with feature-specific query methods as needed.
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
        base["feature"] = "{pkg}"
        return base
'''

    def _service_py(self) -> str:
        pkg = self.package
        service_cls = self.service_class_name
        repo_cls = self.repository_class_name if self.has("repository") else "Any"
        repo_import = f"from {self.feature_name}.repository import {repo_cls}" if self.has("repository") else ""
        if self.has("model"):
            create_body = (
                '        model_class = self._repository.model_class\n'
                '        model = model_class.from_dict(data)\n'
                '        return self._repository.create(model)'
            )
            update_body = (
                '        model = self._repository.get(identifier)\n'
                '        if model is None:\n'
                '            return None\n'
                '        for key, value in data.items():\n'
                '            setattr(model, key, value)\n'
                '        return self._repository.update(model)'
            )
        else:
            create_body = '        return self._repository.create(data)'
            update_body = '        return self._repository.update(identifier, data)'
        return f'''"""Business service for the ``{pkg}`` feature.

Generated by ``bet make feature {self.requested_name}``.

The service sits between the web handlers and the repository: handlers stay
thin and delegates to this class, which owns the business logic for the
``{pkg}`` feature. It is resolved from the application container under the
name ``{self.service_key}``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence
{repo_import}

__all__ = ["{service_cls}"]


class {service_cls}:
    """Business service for the ``{pkg}`` feature.

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
        """Return all records for the managed feature."""
        return self._repository.list()

    def create(self, **data: Any) -> Any:
        """Create a new record from ``data``."""
{create_body}

    def update(self, identifier: Any, **data: Any) -> Any:
        """Update the record ``identifier`` with ``data``."""
{update_body}

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
            "feature": "{pkg}",
            "repository": "{repo_cls}",
        }}
'''

    def _routes_py(self) -> str:
        pkg = self.package
        table = self.table_name
        svc = self.service_key
        has_svc = self.has("service")
        has_model = self.has("model")
        if has_svc:
            resolve_line = '    service = context.resolve("' + svc + '")'
        else:
            resolve_line = '    # TODO: implement service wiring'
        list_get = '    service = context.resolve("' + svc + '")' if has_svc else '# TODO: implement service wiring'
        items_line = '    items = [item.to_dict() for item in service.list()]' if (has_svc and has_model) else ('    items = list(service.list())' if has_svc else '    items = []')
        get_item = '    item = service.get(resource_id)' if has_svc else '    item = None'
        create_item = '    item = service.create(**request.json)' if has_svc else '    item = request.json'
        update_item = '    item = service.update(resource_id, **request.json)' if has_svc else '    item = None'
        delete_line = '    deleted = service.delete(resource_id)' if has_svc else '    deleted = False'
        resp_get = '    return ApiResponse.success(data=item.to_dict())' if has_model else '    return ApiResponse.success(data=item)'
        resp_create = '    return ApiResponse.success(data=item.to_dict(), status=201)' if has_model else '    return ApiResponse.success(data=item, status=201)'
        resp_update = '    return ApiResponse.success(data=item.to_dict())' if has_model else '    return ApiResponse.success(data=item)'
        return f'''"""Web routes for the ``{pkg}`` feature.

Generated by ``bet make feature {self.requested_name}``.

Provides standard RESTful endpoints. Handlers use the documented
``handler(request, context)`` signature from :mod:`betrayer.web.routing` and
delegate to the {pkg} service resolved through the ``WebContext`` container.
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
{resolve_line}
{items_line}
    return ApiResponse.success(data=items, meta={{"feature": "{pkg}", "count": len(items)}})


async def get_{pkg}(request: Request, context: WebContext) -> Response:
    """GET /{table}/<id> -- retrieve a single {pkg} resource."""
{resolve_line}
    resource_id = request.param("id")
{get_item}
    if item is None:
        return ApiResponse.error("RESOURCE_NOT_FOUND", "{pkg} not found", status=404)
{resp_get}


async def create_{pkg}(request: Request, context: WebContext) -> Response:
    """POST /{table} -- create a new {pkg} resource."""
{resolve_line}
{create_item}
{resp_create}


async def update_{pkg}(request: Request, context: WebContext) -> Response:
    """PUT /{table}/<id> -- update an existing {pkg} resource."""
{resolve_line}
    resource_id = request.param("id")
{update_item}
    if item is None:
        return ApiResponse.error("RESOURCE_NOT_FOUND", "{pkg} not found", status=404)
{resp_update}


async def delete_{pkg}(request: Request, context: WebContext) -> Response:
    """DELETE /{table}/<id> -- delete a {pkg} resource."""
{resolve_line}
    resource_id = request.param("id")
{delete_line}
    if not deleted:
        return ApiResponse.error("RESOURCE_NOT_FOUND", "{pkg} not found", status=404)
    return Response.no_content()


# -- registration ---------------------------------------------------


def register_routes(web_router: WebRouter, prefix: str = "") -> None:
    """Register all feature routes on an existing ``WebRouter``.

    Args:
        web_router: The target router to register routes on.
        prefix: Optional path prefix (e.g. ``"/api/v1"``).
    """
    base = f"{{prefix}}/{table}"
    web_router.get(base, list_{pkg})
    web_router.get("{{base}}/<id>", get_{pkg})
    web_router.post(base, create_{pkg})
    web_router.put("{{base}}/<id>", update_{pkg})
    web_router.delete("{{base}}/<id>", delete_{pkg})
'''

    def _module_py(self) -> str:
        pkg = self.package
        module_cls = self.module_class_name
        has_repo = self.has("repository")
        has_svc = self.has("service")

        imports = ["from betrayer.core.module import Module"]
        if has_repo and self.has("model"):
            imports.append(f"from {self.feature_name}.models import {self.model_class_name}")
        if has_repo:
            imports.append(f"from {self.feature_name}.repository import {self.repository_class_name}")
        if has_svc:
            imports.append(f"from {self.feature_name}.service import {self.service_class_name}")

        services_list = []
        if has_repo:
            services_list.append(f'"{self.repository_key}"')
        if has_svc:
            services_list.append(f'"{self.service_key}"')

        register_body = '''        container = context.container
'''
        if has_repo:
            register_body += f'''
        def _build_repository() -> {self.repository_class_name}:
            database = container.resolve("database")
            return {self.repository_class_name}(database=database)

        container.singleton("{self.repository_key}", _build_repository)
'''
        if has_svc:
            register_body += f'''
        def _build_service() -> {self.service_class_name}:
            repository = container.resolve("{self.repository_key}")
            return {self.service_class_name}(repository=repository)

        container.singleton("{self.service_key}", _build_service)
'''

        metadata_dict = {
            "description": f"the {pkg} feature module",
        }
        if self.has("model"):
            metadata_dict["model"] = self.model_class_name
        if has_repo:
            metadata_dict["repository"] = self.repository_class_name
        if has_svc:
            metadata_dict["service"] = self.service_class_name

        return f'''"""Feature module for ``{pkg}``.

Generated by ``bet make feature {self.requested_name}``.

The feature module integrates all components into the Betrayer module system.
It is the single point of registration for the feature on an application:
components are registered on the container so routes can resolve them.
"""

from __future__ import annotations

from typing import Any, Tuple
{chr(10).join(imports)}

__all__ = ["{module_cls}"]


class {module_cls}(Module):
    """Betrayer module for the ``{pkg}`` feature.

    Registers components on the application container.
    """

    name = "{pkg}"
    version = "{FEATURE_VERSION}"
    dependencies: Tuple[str, ...] = ()
    services: Tuple[str, ...] = ({', '.join(services_list)},)
    metadata = {metadata_dict!r}

    def register(self, context: Any) -> None:
        """Declare the feature: register components on the container."""
{register_body}

    def initialize(self, context: Any) -> None:
        """Initialize the feature module."""

    def shutdown(self, context: Any) -> None:
        """Tear down the feature module."""
'''

    def _tests_init_py(self) -> str:
        return '''"""Tests for this feature package."""
'''

    def _tests_unit_py(self) -> str:
        pkg = self.package
        return f'''"""Unit tests for the ``{pkg}`` feature.

Generated by ``bet make feature {self.requested_name}``.
"""

import pytest


class Test{title_case(pkg)}Unit:
    """Unit tests for {pkg} feature components."""

    def test_placeholder(self) -> None:
        """Placeholder test - replace with real tests."""
        assert True

    # Add unit tests for model, schema, service logic here
'''

    def _tests_integration_py(self) -> str:
        pkg = self.package
        return f'''"""Integration tests for the ``{pkg}`` feature.

Generated by ``bet make feature {self.requested_name}``.
"""

import pytest


class Test{title_case(pkg)}Integration:
    """Integration tests for {pkg} feature end-to-end flows."""

    def test_placeholder(self) -> None:
        """Placeholder test - replace with real tests."""
        assert True

    # Add integration tests for routes, database, service wiring here
'''

    # ── generation ──────────────────────────────────────────────────────

    def generate(self) -> GeneratorOutput:
        """Create the feature package and every generated file.

        Raises :class:`GeneratorError` when the target already exists and is
        not empty and ``overwrite`` is False, so an existing feature is never
        overwritten silently.
        """
        if not self.overwrite and self._target_occupied():
            raise GeneratorError(
                "feature already exists (use --force to overwrite): "
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
