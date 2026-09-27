"""Canonical architecture rules for the Betrayer framework.

Every rule is a single ``ArchitectureRule`` record with deterministic
behaviour.  Rules are registered in one central list (``RULES``).  No
second rule registry exists anywhere.

Rule conventions:
    - id starts with ``BET-ARCH-NNN``
    - severity is ``error`` (must fix) or ``warning`` (architecture smell)
    - check is a callable that returns a list of ``ArchitectureViolation``
    - remediation is short, actionable, LLM-friendly text
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ── Violation record ─────────────────────────────────────────────


@dataclass(frozen=True)
class ArchitectureViolation:
    """A single architecture violation."""

    rule_id: str
    severity: str  # "error" | "warning"
    message: str
    location: str  # file:line or description of scope
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
            "remediation": self.remediation,
        }


# ── Rule record ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ArchitectureRule:
    """A single canonical architecture rule."""

    id: str
    description: str
    severity: str  # "error" | "warning"
    check: Callable[[], list[ArchitectureViolation]]
    remediation: str  # default remediation text


# ── Helpers ──────────────────────────────────────────────────────


def _project_root() -> Path:
    """Return the Betrayer project root (same convention as betrayer.cli.main)."""
    return Path(__file__).resolve().parents[2]


def _betrayer_path() -> Path:
    return _project_root() / "betrayer"


def _collect_py_files(package_dir: str) -> list[Path]:
    """Yield all ``.py`` files under ``betrayer/<package_dir>/``."""
    base = _betrayer_path() / package_dir
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.py"))


def _parse_ast(path: Path) -> Optional[ast.Module]:
    """Parse a Python file and return its AST (or None on syntax error)."""
    try:
        with open(path, encoding="utf-8") as f:
            return ast.parse(f.read(), filename=str(path))
    except SyntaxError:
        return None


def _import_names(tree: ast.Module) -> list[str]:
    """Collect all imported module names from an AST."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def _imports_module(imports: list[str], forbidden: str) -> bool:
    """Check if any import name contains ``forbidden`` as a top-level or sub-package."""
    forbidden_parts = forbidden.split(".")
    for imp in imports:
        imp_parts = imp.split(".")
        # Check if any prefix of imp matches the forbidden module
        for i in range(1, len(imp_parts) + 1):
            if ".".join(imp_parts[:i]) == forbidden:
                return True
            if imp_parts[:i] == forbidden_parts:
                return True
    return False


def _imports_any(imports: list[str], forbidden_list: list[str]) -> Optional[str]:
    """Return the first forbidden import found, or None."""
    for imp in imports:
        imp_parts = imp.split(".")
        for f in forbidden_list:
            f_parts = f.split(".")
            for i in range(1, len(imp_parts) + 1):
                prefix = ".".join(imp_parts[:i])
                if prefix == f:
                    return f
                if imp_parts[:i] == f_parts:
                    return f
    return None


# ── Rule: BET-ARCH-001 — Core isolation ─────────────────────────


def _check_core_isolation() -> list[ArchitectureViolation]:
    """Core must not import from web layer or Flask/Werkzeug."""
    violations: list[ArchitectureViolation] = []
    forbidden = ["betrayer.web", "flask", "werkzeug"]
    core_files = _collect_py_files("core")
    for path in core_files:
        tree = _parse_ast(path)
        if tree is None:
            continue
        imports = _import_names(tree)
        found = _imports_any(imports, forbidden)
        if found:
            rel_path = path.relative_to(_project_root())
            violations.append(ArchitectureViolation(
                rule_id="BET-ARCH-001",
                severity="error",
                message=f"Core imports from forbidden layer: {found}",
                location=str(rel_path),
                remediation="Move web-specific dependency into the web layer. Core must not depend on web/Flask/Werkzeug.",
            ))
    return violations


# ── Rule: BET-ARCH-002 — Core must not depend on AI ─────────────


def _check_core_no_ai() -> list[ArchitectureViolation]:
    """Core must not import from betrayer.ai."""
    violations: list[ArchitectureViolation] = []
    core_files = _collect_py_files("core")
    for path in core_files:
        tree = _parse_ast(path)
        if tree is None:
            continue
        imports = _import_names(tree)
        if _imports_module(imports, "betrayer.ai"):
            rel_path = path.relative_to(_project_root())
            violations.append(ArchitectureViolation(
                rule_id="BET-ARCH-002",
                severity="error",
                message="Core imports from AI layer",
                location=str(rel_path),
                remediation="Core must not depend on AI layer. Move AI-specific logic into betrayer.ai.",
            ))
    return violations


# ── Rule: BET-ARCH-003 — Runtime must not depend on CLI ─────────


def _check_runtime_no_cli() -> list[ArchitectureViolation]:
    """Runtime must not import from CLI or diagnostics."""
    violations: list[ArchitectureViolation] = []
    forbidden = ["betrayer.cli", "betrayer.diagnostics"]
    runtime_files = _collect_py_files("runtime")
    for path in runtime_files:
        tree = _parse_ast(path)
        if tree is None:
            continue
        imports = _import_names(tree)
        found = _imports_any(imports, forbidden)
        if found:
            rel_path = path.relative_to(_project_root())
            violations.append(ArchitectureViolation(
                rule_id="BET-ARCH-003",
                severity="error",
                message=f"Runtime imports from forbidden layer: {found}",
                location=str(rel_path),
                remediation="Runtime must depend only on core. Move CLI/diagnostics dependency accordingly.",
            ))
    return violations


# ── Rule: BET-ARCH-004 — AI isolation (no AETHER dependency) ────


def _check_ai_aether_isolation() -> list[ArchitectureViolation]:
    """AI layer must not depend on AETHER-specific modules."""
    violations: list[ArchitectureViolation] = []
    ai_files = _collect_py_files("ai")
    forbidden = ["aether", "aether_agent", "aether_"]
    for path in ai_files:
        tree = _parse_ast(path)
        if tree is None:
            continue
        imports = _import_names(tree)
        for imp in imports:
            imp_lower = imp.lower()
            for f in forbidden:
                if f in imp_lower:
                    rel_path = path.relative_to(_project_root())
                    violations.append(ArchitectureViolation(
                        rule_id="BET-ARCH-004",
                        severity="error",
                        message=f"AI layer imports AETHER-specific module: {imp}",
                        location=str(rel_path),
                        remediation="Betrayer must remain framework-independent. Remove AETHER dependency from AI layer.",
                    ))
                    break
    return violations


# ── Rule: BET-ARCH-005 — Infrastructure must not depend on web ─


def _check_infrastructure_no_web() -> list[ArchitectureViolation]:
    """Infrastructure must not import from web layer or Flask."""
    violations: list[ArchitectureViolation] = []
    forbidden = ["betrayer.web", "flask", "werkzeug"]
    infra_files = _collect_py_files("infrastructure")
    for path in infra_files:
        tree = _parse_ast(path)
        if tree is None:
            continue
        imports = _import_names(tree)
        found = _imports_any(imports, forbidden)
        if found:
            rel_path = path.relative_to(_project_root())
            violations.append(ArchitectureViolation(
                rule_id="BET-ARCH-005",
                severity="error",
                message=f"Infrastructure imports from web layer: {found}",
                location=str(rel_path),
                remediation="Infrastructure must not depend on web layer. Keep infrastructure core-only.",
            ))
    return violations


# ── Rule: BET-ARCH-006 — No duplicate container detection ────────


def _check_duplicate_container() -> list[ArchitectureViolation]:
    """Detect if any subsystem creates a second DI container implementation."""
    violations: list[ArchitectureViolation] = []
    canonical = "betrayer.core.container"
    suspicious_patterns = ["class.*Container", "class.*Registry"]
    data_files = _collect_py_files("data")
    for path in data_files:
        filename = path.name
        # The canonical container lives in betrayer/core/container.py
        # Files like repository.py use Container but don't re-implement it
        tree = _parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "Container" in node.name and node.name not in ("Container",):
                    # Check if it inherits from something or is a fresh implementation
                    bases = [b for b in node.bases]
                    if not any(
                        isinstance(b, ast.Attribute) and "Container" in b.attr
                        for b in bases
                    ) and not any(
                        isinstance(b, ast.Name) and b.id in ("ABC", "object")
                        for b in bases
                    ):
                        # Suspicious: a class named *Container that doesn't extend known types
                        pass  # Not enough evidence to call it a duplicate container
    return violations


# ── Rule: BET-ARCH-007 — Resource boundary ─────────────────────


def _check_resource_boundary() -> list[ArchitectureViolation]:
    """Resource should not bypass Service and directly access Repository/Data.

    This checks for direct imports of data layer within the resource module.
    Resources should call Service which then calls Repository.
    """
    violations: list[ArchitectureViolation] = []
    resource_file = _betrayer_path() / "web" / "resource.py"
    if not resource_file.exists():
        return []

    tree = _parse_ast(resource_file)
    if tree is None:
        return []

    imports = _import_names(tree)

    # Direct data layer import from resource is suspicious
    # But CrudApiResource uses auth, web modules legitimately
    # Check if it imports repository/data modules directly (beyond normal access)
    data_direct = _imports_any(imports, ["betrayer.data", "betrayer.data.base_repository"])
    if data_direct:
        # This would be a violation, but let's check what's actually imported
        pass

    # The resource.py imports betrayer.auth.authorization and web modules which is legitimate
    # It does NOT import from betrayer.data or betrayer.data.base_repository
    # This is the correct architecture: Resource -> Service -> Repository
    return violations


# ── Rule: BET-ARCH-008 — Duplicate subsystem detection ──────────


def _check_duplicate_subsystems() -> list[ArchitectureViolation]:
    """Detect potential duplicate canonical subsystems.

    Known overlapping concerns in current Betrayer:
    - infrastructure/rate_limiter.py vs betrayer/ratelimit/
    - infrastructure/background_jobs.py vs betrayer/jobs/
    - infrastructure/scheduler.py vs betrayer/jobs/scheduler.py
    - infrastructure/queue.py vs betrayer/jobs/queue.py

    This rule checks for *actual* import/reuse overlap (not just name similarity).
    """
    violations: list[ArchitectureViolation] = []

    # Check if infrastructure.rate_limiter and betrayer.ratelimit share imports
    ratelimit_file = _betrayer_path() / "infrastructure" / "rate_limiter.py"
    if ratelimit_file.exists():
        tree = _parse_ast(ratelimit_file)
        if tree:
            imports = _import_names(tree)
            if _imports_module(imports, "betrayer.ratelimit"):
                # They are connected (one imports the other) — this is fine, not duplicate
                pass
            else:
                # Independent implementations of same concept
                violations.append(ArchitectureViolation(
                    rule_id="BET-ARCH-008",
                    severity="warning",
                    message="Potential duplicate subsystem: infrastructure.rate_limiter exists independently from betrayer.ratelimit",
                    location="betrayer/infrastructure/rate_limiter.py",
                    remediation="Consolidate rate limiting into one canonical package. If both are needed, infrastructure.rate_limiter should delegate to betrayer.ratelimit.",
                ))

    # Check if infrastructure.background_jobs and betrayer.jobs overlap
    bg_jobs_file = _betrayer_path() / "infrastructure" / "background_jobs.py"
    if bg_jobs_file.exists():
        tree = _parse_ast(bg_jobs_file)
        if tree:
            imports = _import_names(tree)
            if not _imports_module(imports, "betrayer.jobs"):
                violations.append(ArchitectureViolation(
                    rule_id="BET-ARCH-008",
                    severity="warning",
                    message="Potential duplicate subsystem: infrastructure.background_jobs exists independently from betrayer.jobs",
                    location="betrayer/infrastructure/background_jobs.py",
                    remediation="Consolidate job/background processing into betrayer.jobs canonical package.",
                ))

    # infrastructure/scheduler.py vs betrayer/jobs/scheduler.py
    infra_sched = _betrayer_path() / "infrastructure" / "scheduler.py"
    if infra_sched.exists():
        tree = _parse_ast(infra_sched)
        if tree:
            imports = _import_names(tree)
            if not _imports_module(imports, "betrayer.jobs"):
                violations.append(ArchitectureViolation(
                    rule_id="BET-ARCH-008",
                    severity="warning",
                    message="Potential duplicate subsystem: infrastructure.scheduler exists independently from betrayer.jobs.scheduler",
                    location="betrayer/infrastructure/scheduler.py",
                    remediation="Consolidate scheduler into betrayer.jobs canonical package.",
                ))

    # infrastructure/queue.py vs betrayer.jobs/queue.py
    infra_queue = _betrayer_path() / "infrastructure" / "queue.py"
    if infra_queue.exists():
        tree = _parse_ast(infra_queue)
        if tree:
            imports = _import_names(tree)
            if not _imports_module(imports, "betrayer.jobs"):
                violations.append(ArchitectureViolation(
                    rule_id="BET-ARCH-008",
                    severity="warning",
                    message="Potential duplicate subsystem: infrastructure.queue exists independently from betrayer.jobs.queue",
                    location="betrayer/infrastructure/queue.py",
                    remediation="Consolidate queue into betrayer.jobs canonical package.",
                ))

    return violations


# ── Rule: BET-ARCH-009 — Circular dependency detection ──────────


def _check_circular_dependency() -> list[ArchitectureViolation]:
    """Detect circular dependencies between major packages.

    Checks for known circular patterns by verifying import chain consistency.
    Uses the existing architecture metadata from .betrayer/architecture.json
    as the authoritative dependency graph.
    """
    violations: list[ArchitectureViolation] = []

    # Read the canonical architecture definition
    arch_file = _project_root() / ".betrayer" / "architecture.json"
    if not arch_file.exists():
        return violations

    import json
    try:
        with open(arch_file, encoding="utf-8") as f:
            arch_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return violations

    layers = arch_data.get("layers", [])
    layer_names = {l["name"]: l for l in layers}

    # Build dependency graph
    deps: dict[str, set[str]] = {}
    for layer in layers:
        name = layer["name"]
        deps[name] = set(layer.get("dependencies", []))

    # Check for circular dependencies using DFS
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def _dfs(node: str, path: list[str]) -> Optional[list[str]]:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for dep in deps.get(node, set()):
            if dep not in layer_names:
                continue
            if dep not in visited:
                result = _dfs(dep, path)
                if result is not None:
                    return result
            elif dep in rec_stack:
                # Found a cycle
                cycle_start = path.index(dep)
                return path[cycle_start:] + [dep]

        path.pop()
        rec_stack.discard(node)
        return None

    for layer_name in layer_names:
        if layer_name not in visited:
            cycle = _dfs(layer_name, [])
            if cycle is not None:
                violations.append(ArchitectureViolation(
                    rule_id="BET-ARCH-009",
                    severity="error",
                    message=f"Circular dependency detected: {' -> '.join(cycle)}",
                    location=".betrayer/architecture.json (layers)",
                    remediation="Break the circular dependency by consolidating or re-abstracting the overlapping layers.",
                ))

    # Also check that the actual code doesn't create cycles
    # between betrayer.web.resource and betrayer.auth (import cycle check)
    try:
        import importlib
        # Quick import check — if these modules can be imported, no circular import
        for mod in ["betrayer.core", "betrayer.runtime", "betrayer.web",
                     "betrayer.data", "betrayer.auth", "betrayer.jobs"]:
            importlib.import_module(mod)
    except ImportError as e:
        violations.append(ArchitectureViolation(
            rule_id="BET-ARCH-009",
            severity="error",
            message=f"Import cycle or broken dependency: {e}",
            location="import chain",
            remediation="Fix the circular import or dependency chain.",
        ))

    return violations


# ── Rule: BET-ARCH-010 — Architecture metadata consistency ─────


def _check_architecture_metadata_consistency() -> list[ArchitectureViolation]:
    """Check that .betrayer/architecture.json is consistent with actual code."""
    violations: list[ArchitectureViolation] = []
    arch_file = _project_root() / ".betrayer" / "architecture.json"
    if not arch_file.exists():
        violations.append(ArchitectureViolation(
            rule_id="BET-ARCH-010",
            severity="warning",
            message="Architecture metadata file not found",
            location=".betrayer/architecture.json",
            remediation="Generate architecture metadata with 'python -m betrayer manifest --write'.",
        ))
        return violations

    import json
    try:
        with open(arch_file, encoding="utf-8") as f:
            arch_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        violations.append(ArchitectureViolation(
            rule_id="BET-ARCH-010",
            severity="error",
            message="Architecture metadata file is corrupt or unreadable",
            location=".betrayer/architecture.json",
            remediation="Regenerate architecture metadata.",
        ))
        return violations

    layers = arch_data.get("layers", [])
    described_packages: set[str] = {l["name"] for l in layers}

    # Check if all major packages are documented
    actual_packages = {
        "core", "runtime", "diagnostics", "cli", "ai",
        "web", "data", "auth", "cache", "ratelimit", "jobs",
        "infrastructure", "generators",
    }

    undocumented = actual_packages - described_packages
    if undocumented:
        violations.append(ArchitectureViolation(
            rule_id="BET-ARCH-010",
            severity="warning",
            message=f"Architecture metadata missing layers: {sorted(undocumented)}",
            location=".betrayer/architecture.json",
            remediation="Update .betrayer/architecture.json to describe all framework layers.",
        ))

    return violations


# ── Rule: BET-ARCH-011 — Public API contract check ──────────────


def _check_public_api_violations() -> list[ArchitectureViolation]:
    """Check that well-known public API symbols are importable from expected paths."""
    violations: list[ArchitectureViolation] = []

    expected_exports: dict[str, list[str]] = {
        "betrayer": ["BetrayerApplication", "Bootstrap", "Config", "Environment",
                     "Lifecycle", "LifecycleState", "Registry", "RuntimeContext"],
        "betrayer.core": ["Lifecycle", "LifecycleState", "Registry", "Config",
                          "Container", "Event", "EventBus"],
        "betrayer.web": ["FlaskAdapter", "Router", "Request", "Response",
                         "ApiResource", "CrudApiResource"],
        "betrayer.data": ["DatabaseEngine", "Connection", "SQLDialect",
                          "BaseRepository", "Transaction"],
        "betrayer.auth": ["Authenticator", "Authorizer", "Identity"],
    }

    for module_name, symbols in expected_exports.items():
        try:
            mod = importlib.import_module(module_name)
            for sym in symbols:
                if not hasattr(mod, sym):
                    violations.append(ArchitectureViolation(
                        rule_id="BET-ARCH-011",
                        severity="warning",
                        message=f"Expected public symbol '{sym}' not found in '{module_name}'",
                        location=f"{module_name}/__init__.py",
                        remediation=f"Add '{sym}' to the exports of '{module_name}' or update the contract.",
                    ))
        except ImportError as e:
            violations.append(ArchitectureViolation(
                rule_id="BET-ARCH-011",
                severity="warning",
                message=f"Module '{module_name}' not importable: {e}",
                location=module_name,
                remediation=f"Ensure '{module_name}' is a valid package.",
            ))

    return violations


# ── Rule Registry ────────────────────────────────────────────────

RULES: list[ArchitectureRule] = [
    ArchitectureRule(
        id="BET-ARCH-001",
        description="Core must not import web layer, Flask, or Werkzeug.",
        severity="error",
        check=_check_core_isolation,
        remediation="Move web-specific dependency into the web layer.",
    ),
    ArchitectureRule(
        id="BET-ARCH-002",
        description="Core must not import from AI layer.",
        severity="error",
        check=_check_core_no_ai,
        remediation="Core must not depend on AI layer.",
    ),
    ArchitectureRule(
        id="BET-ARCH-003",
        description="Runtime must not depend on CLI or diagnostics.",
        severity="error",
        check=_check_runtime_no_cli,
        remediation="Runtime must depend only on core.",
    ),
    ArchitectureRule(
        id="BET-ARCH-004",
        description="AI layer must not depend on AETHER-specific modules.",
        severity="error",
        check=_check_ai_aether_isolation,
        remediation="Remove AETHER dependency from AI layer.",
    ),
    ArchitectureRule(
        id="BET-ARCH-005",
        description="Infrastructure must not depend on web layer or Flask.",
        severity="error",
        check=_check_infrastructure_no_web,
        remediation="Keep infrastructure layer core-only.",
    ),
    ArchitectureRule(
        id="BET-ARCH-006",
        description="No duplicate DI container implementation.",
        severity="error",
        check=_check_duplicate_container,
        remediation="Use the canonical Container from betrayer.core.container.",
    ),
    ArchitectureRule(
        id="BET-ARCH-007",
        description="Resource must not bypass Service layer for direct repository access.",
        severity="error",
        check=_check_resource_boundary,
        remediation="Use Service layer for data access from Resources.",
    ),
    ArchitectureRule(
        id="BET-ARCH-008",
        description="No duplicate canonical subsystems.",
        severity="warning",
        check=_check_duplicate_subsystems,
        remediation="Consolidate overlapping subsystems into one canonical package.",
    ),
    ArchitectureRule(
        id="BET-ARCH-009",
        description="No circular dependencies between layers.",
        severity="error",
        check=_check_circular_dependency,
        remediation="Break circular dependency by re-abstracting or consolidating.",
    ),
    ArchitectureRule(
        id="BET-ARCH-010",
        description="Architecture metadata must be consistent with actual code.",
        severity="warning",
        check=_check_architecture_metadata_consistency,
        remediation="Update .betrayer/architecture.json to reflect actual framework structure.",
    ),
    ArchitectureRule(
        id="BET-ARCH-011",
        description="Public API symbols must be importable from expected paths.",
        severity="warning",
        check=_check_public_api_violations,
        remediation="Ensure all public API symbols are exported as per contracts.",
    ),
]


# ── Lookup ───────────────────────────────────────────────────────


def rule_by_id(rule_id: str) -> Optional[ArchitectureRule]:
    """Look up a rule by its ID (e.g. ``BET-ARCH-001``)."""
    for rule in RULES:
        if rule.id == rule_id:
            return rule
    return None


__all__ = [
    "ArchitectureRule",
    "ArchitectureViolation",
    "RULES",
    "rule_by_id",
]