"""Shared LLM Project Intelligence core.

This is the single intelligence layer behind the ``bet inspect``,
``bet context`` and ``bet impact`` commands.  It reads *existing* project
structure and Betrayer metadata (``.betrayer/manifest.json`` and
``.betrayer/architecture.json``) plus a light AST scan of the source tree.

It is intentionally **not** a second repository/graph system: it does not
persist state, does not run a server, and does not duplicate knowledge that
the framework already exposes.  Every function returns a plain,
JSON-serialisable ``dict`` so the CLI can print it directly and an LLM can
consume it deterministically.

Public API::

    from betrayer.ai import intelligence

    intelligence.inspect()             # whole project overview
    intelligence.inspect("UserService")# entity/module/service/model view
    intelligence.context("UserService")# files, symbols, deps, dependents, tests
    intelligence.impact("UserService") # potentially affected project parts
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Optional

__all__ = ["inspect", "context", "impact", "affected_tests"]

#: Repository root (``.../betrayer/ai/intelligence.py`` -> project root).
ROOT: Path = Path(__file__).resolve().parents[2]

#: Directories never scanned for source intelligence.
_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules"}

#: Metadata files that Betrayer already generates and exposes.
_METADATA_FILES = ("manifest.json", "architecture.json")


def _iter_py_files() -> list[Path]:
    """Every ``*.py`` file under the project root, deterministic order."""
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def _symbols(tree: ast.AST) -> list[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return sorted(names)


def _imports(tree: ast.AST) -> list[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return sorted(names)


def _record(path: Path) -> dict[str, Any]:
    """Light, LLM-relevant facts for a single source file."""
    rel = path.relative_to(ROOT).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {"file": rel, "symbols": [], "imports": []}
    return {"file": rel, "symbols": _symbols(tree), "imports": _imports(tree)}


def _index() -> list[dict[str, Any]]:
    """Build the (recomputed) source index. Deterministic and stateless."""
    return [_record(path) for path in _iter_py_files()]


def _metadata() -> dict[str, Any]:
    """Read the existing Betrayer metadata files, if present."""
    meta: dict[str, Any] = {}
    for name in _METADATA_FILES:
        path = ROOT / ".betrayer" / name
        if not path.is_file():
            continue
        try:
            meta[name[: -len(".json")]] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return meta


def _target_terms(target: Optional[str]) -> list[str]:
    if not target:
        return []
    # A route like ``/login`` matches by its normalized path segments.
    return [term for term in target.lower().lstrip("/").split("/") if term]


def _match(record: dict[str, Any], terms: list[str]) -> bool:
    haystack = record["file"].lower()
    symbols = [s.lower() for s in record["symbols"]]
    for term in terms:
        if term in haystack:
            return True
        if any(term in symbol for symbol in symbols):
            return True
    return False


def _select(target: Optional[str], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = _target_terms(target)
    if not terms:
        return records
    return [record for record in records if _match(record, terms)]


def _module_of(file_path: str) -> str:
    """Betrayer package/module name for a file (``betrayer.cli.main``)."""
    pure = file_path[:-3] if file_path.endswith(".py") else file_path
    if pure.endswith("/__init__"):
        pure = pure[: -len("/__init__")]
    return pure.replace("/", ".")


def inspect(target: Optional[str] = None) -> dict[str, Any]:
    """Structured information about the project, or one entity within it.

    With no ``target`` the result is a concise project overview; with a
    ``target`` it is the set of matching source entities.
    """
    records = _index()
    selected = _select(target, records)
    metadata = _metadata()
    manifest = metadata.get("manifest", {})
    architecture = metadata.get("architecture", {})

    packages = sorted({_module_of(r["file"]) for r in records if r["file"].startswith("betrayer/")})
    return {
        "success": True,
        "target": target,
        "project_root": ".",
        "total_files": len(records),
        "total_packages": len(packages),
        "framework": manifest.get("framework"),
        "version": manifest.get("version"),
        "architecture_version": manifest.get("architecture_version"),
        "commands": manifest.get("commands", []),
        "layers": [layer.get("name") for layer in architecture.get("layers", [])],
        "packages": packages,
        "entities": [
            {
                "file": record["file"],
                "module": _module_of(record["file"]),
                "symbols": record["symbols"],
            }
            for record in selected
        ],
        "total_entities": len(selected),
    }


def context(target: str) -> dict[str, Any]:
    """Concise context for ``target``: files, symbols, deps, tests, callers."""
    records = _index()
    selected = _select(target, records)
    selected_files = {record["file"] for record in selected}
    terms = _target_terms(target)

    # External dependencies referenced by the selected files.
    dependencies: set[str] = set()
    for record in selected:
        for name in record["imports"]:
            if name not in {"betrayer", "__future__"}:
                dependencies.add(name)

    # Related tests: any test file mentioning a target term or a selected symbol.
    selected_symbols = {symbol.lower() for record in selected for symbol in record["symbols"]}
    related_tests: list[str] = []
    for record in records:
        if not record["file"].startswith("tests/"):
            continue
        haystack = record["file"].lower()
        if any(term in haystack for term in terms):
            related_tests.append(record["file"])
            continue
        if selected_symbols and selected_symbols & {s.lower() for s in record["symbols"]}:
            related_tests.append(record["file"])

    # Dependents: files importing any selected module's last path segment.
    selected_segments = {
        _module_of(file_path).split(".")[-1].lower() for file_path in selected_files
    }
    dependents: list[str] = []
    for record in records:
        if record["file"] in selected_files:
            continue
        if selected_segments & {name.lower() for name in record["imports"]}:
            dependents.append(record["file"])

    # Which Betrayer capabilities this target relates to (existing subsystem).
    related_capabilities = _related_capabilities(terms, selected)

    return {
        "success": True,
        "target": target,
        "files": [
            {"file": record["file"], "module": _module_of(record["file"]), "symbols": record["symbols"]}
            for record in selected
        ],
        "symbols": sorted(selected_symbols),
        "dependencies": sorted(dependencies),
        "dependents": sorted(dependents),
        "related_tests": sorted(related_tests),
        "related_capabilities": related_capabilities,
    }


def impact(target: str) -> dict[str, Any]:
    """Project parts that a change to ``target`` may affect."""
    ctx = context(target)
    affected: set[str] = set(ctx["dependents"])
    affected.update(ctx["related_tests"])
    dependents = sorted(affected)
    return {
        "success": True,
        "target": target,
        "source_files": [entry["file"] for entry in ctx["files"]],
        "dependencies": ctx["dependencies"],
        "dependents": ctx["dependents"],
        "related_tests": ctx["related_tests"],
        "related_capabilities": ctx["related_capabilities"],
        "affected": dependents,
        "affected_count": len(dependents),
    }


def _related_capabilities(terms: list[str], selected: list[dict[str, Any]]) -> list[str]:
    """Map a target onto existing Betrayer capabilities (no new registry)."""
    try:
        from betrayer.ai import discover
    except Exception:  # pragma: no cover - defensive: discovery is optional
        return []

    names: list[str] = []
    seen: set[str] = set()
    queries = list(dict.fromkeys(term for term in terms))
    for record in selected:
        for segment in _module_of(record["file"]).split("."):
            if segment and segment not in {"betrayer", "tests", "example"}:
                queries.append(segment)
    for query in queries:
        try:
            results = discover.search(query)
        except Exception:  # pragma: no cover - defensive
            continue
        for result in results:
            name = result.get("name")
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _changed_files() -> list[str]:
    """Return tracked files changed from the repository base, if available."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        files = set(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
        # Include untracked Python files: they are real changes for a coding agent.
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT,
            capture_output=True, text=True, check=False,
        )
        files.update(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
        return sorted(files)
    except OSError:
        return []


def _import_graph() -> dict[str, set[str]]:
    """Build reverse import map: module -> set(modules that import it)."""
    index = _index()
    rev: dict[str, set[str]] = {}
    for rec in index:
        mod = _module_of(rec["file"])
        for imp in rec["imports"]:
            # Only track full-module imports (skip parent packages like "betrayer",
            # "betrayer.core" to avoid transitive closure explosion).
            if imp.startswith("betrayer.") and imp.count(".") >= 1:
                rev.setdefault(imp, set()).add(mod)
    return rev


def affected_tests(changed: Optional[list[str]] = None) -> dict[str, Any]:
    """Map changed files to tests using the shared intelligence index."""
    records = _index()
    tests = [r for r in records if r["file"].startswith("tests/")]
    changed = sorted(set(changed if changed is not None else _changed_files()))
    selected: set[str] = set()
    reasons: dict[str, set[str]] = {}

    # Build reverse import graph: module -> set(modules that import it directly)
    rev_imports = _import_graph()

    for source in changed:
        if source.startswith("tests/"):
            selected.add(source)
            reasons.setdefault(source, set()).add("changed test")
            continue

        # Identify changed module(s) -- only for Python sources.
        changed_mods = {_module_of(source)} if source.endswith(".py") else set()

        if not changed_mods:
            # Non-Python files: filename stem is the only weak signal available.
            stem = Path(source).stem.lower()
            for rec in tests:
                if stem and stem in rec["file"].lower():
                    selected.add(rec["file"])
                    reasons.setdefault(rec["file"], set()).add(source)
            continue

        # Direct dependents only -- NO transitive closure.
        # Only modules that directly import the changed module.
        affected_mods: set[str] = set()
        for mod in changed_mods:
            affected_mods.update(rev_imports.get(mod, ()))
            affected_mods.add(mod)  # the changed module itself

        # Select test files that directly depend on changed modules.
        for rec in tests:
            mod = _module_of(rec["file"])
            if mod in affected_mods:
                selected.add(rec["file"])
                reasons.setdefault(rec["file"], set()).add(
                    f"imports/is {', '.join(sorted(changed_mods))}"
                )

    result = {
        "success": True,
        "changed_files": changed,
        "affected_tests": sorted(selected),
        "affected_count": len(selected),
        "determined": bool(selected),
        "reasons": {k: sorted(v) for k, v in sorted(reasons.items())},
        "note": None if selected else "no affected tests could be determined",
    }
    return result
