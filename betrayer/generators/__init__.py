"""Generator package for the Betrayer Framework.

Only implemented generators are exported.  The registry stays the single place
commands are wired up: each generator is used directly by its CLI command in
``betrayer.cli.main``.
"""

from __future__ import annotations

from betrayer.generators.base import (
    BaseGenerator,
    GeneratorError,
    GeneratorOutput,
    TemplateRenderer,
    camel_case,
    package_name,
    snake_case,
    title_case,
    validate_project_name,
)
from betrayer.generators.crud import CrudGenerator, validate_crud_name
from betrayer.generators.extension import (
    ExtensionGenerator,
    validate_extension_name,
)
from betrayer.generators.migration import MigrationGenerator, validate_migration_name
from betrayer.generators.module import ModuleGenerator, validate_module_name
from betrayer.generators.project import ProjectGenerator
from betrayer.generators.resource import ResourceGenerator, validate_resource_name
from betrayer.generators.service import ServiceGenerator, validate_service_name

__all__ = [
    "BaseGenerator",
    "GeneratorError",
    "GeneratorOutput",
    "TemplateRenderer",
    "snake_case",
    "camel_case",
    "title_case",
    "package_name",
    "validate_project_name",
    "ProjectGenerator",
    "ModuleGenerator",
    "validate_module_name",
    "ResourceGenerator",
    "validate_resource_name",
    "ServiceGenerator",
    "validate_service_name",
    "CrudGenerator",
    "validate_crud_name",
    "MigrationGenerator",
    "validate_migration_name",
    "ExtensionGenerator",
    "validate_extension_name",
]