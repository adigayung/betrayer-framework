"""Persistent & Incremental Project Intelligence Index.

One shared, project-scoped index powers every Betrayer intelligence command
(``bet inspect``, ``bet context``, ``bet impact``, ``bet test affected``) so
the source tree is scanned **once** and reused across CLI invocations.

Behaviour::

    first call   -> build index -> persist (.betrayer/intelligence_index.json)
    next calls   -> reuse persisted index (no source scan)
    file changed -> detect stale -> incremental refresh of changed files only
    corrupt/old  -> full rebuild (never a traceback)

The index is a *cache* of facts derived from the source tree — never a second
source of truth:

* every entry is derived from the current file content (SHA-256 verified);
* it is invalidated automatically when files change;
* it can be rebuilt at any time with :func:`rebuild`.

Public API::

    from betrayer.ai import indexer

    result = indexer.refresh()            # reuse / incremental / rebuild
    index = indexer.get_index()           # ProjectIndex (always current)
    indexer.rebuild()                     # force a full rebuild
    indexer.status()                      # machine readable cache state
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

__all__ = [
    "INDEX_VERSION",
    "INDEX_RELATIVE_PATH",
    "FileEntry",
    "ProjectIndex",
    "IndexResult",
    "find_project_root",
    "index_path",
    "refresh",
    "get_index",
    "rebuild",
    "status",
    "clear",
]

#: Index format version. Bump whenever the persisted structure changes.
INDEX_VERSION: int = 1

#: Hash of the extraction semantics. Bump whenever the *meaning* of a stored
#: entry changes, so an index written by older logic is rebuilt instead of
#: silently answering with outdated facts.
SCHEMA_HASH: str = "bet-intel-v1"

#: Where the index lives inside a project (relative to the project root).
INDEX_RELATIVE_PATH: str = ".betrayer/intelligence_index.json"

#: Directories never scanned.
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules",
    ".tox", ".idea", ".vscode", "build", "dist", ".betrayer",
})

#: Betrayer metadata files cached inside the index.
_METADATA_FILES = ("manifest.json", "architecture.json")

#: Project files whose content participates in invalidation.
_CONFIG_FILES = ("pyproject.toml", "setup.py", "setup.cfg")

#: Role detection: (role, file-name markers).
_ROLE_FILE_MARKERS = {
    "routes": ("routes", "router", "routing", "urls"),
    "service": ("service", "services"),
    "resource": ("resource", "resources"),
    "model": ("model", "models", "schema", "schemas", "entity", "entities"),
}

#: Role detection from symbol names: (role, suffixes).
_ROLE_SYMBOL_SUFFIXES = {
    "routes": ("Route", "Router"),
    "service": ("Service",),
    "resource": ("Resource", "ViewSet"),
    "model": ("Model", "Schema", "Entity"),
}

#: File/classifier helpers.
_MODULE_ROOT_EXCLUDES = frozenset({"tests", "example", "examples"})


# ── Project root ─────────────────────────────────────────────────


def find_project_root(start: Optional[Path] = None) -> Path:
    """Return the project root for ``start`` (default: current directory).

    The project root is the nearest ancestor that owns Betrayer metadata
    (``.betrayer/``), falling back to ``pyproject.toml``/``setup.py`` and
    finally to the directory Betrayer itself lives in.
    """
    env = os.environ.get("BETRAYER_PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    base = Path(start) if start is not None else Path.cwd()
    base = base.resolve()
    if base.is_file():
        base = base.parent
    for candidate in (base, *base.parents):
        if (candidate / ".betrayer").is_dir():
            return candidate
        if (candidate / "pyproject.toml").is_file() or (candidate / "setup.py").is_file():
            return candidate
    # Fall back to the directory that contains the Betrayer package.
    return Path(__file__).resolve().parents[2]


def index_path(root: Optional[Path] = None) -> Path:
    """Absolute path of the persisted index for ``root``."""
    project_root = find_project_root(root)
    return project_root / Path(INDEX_RELATIVE_PATH)


# ── Source extraction ────────────────────────────────────────────


def module_of(file_path: str) -> str:
    """Dotted module name for a project-relative file path."""
    pure = file_path[:-3] if file_path.endswith(".py") else file_path
    if pure.endswith("/__init__"):
        pure = pure[: -len("/__init__")]
    return pure.replace("/", ".")


def classify(rel_path: str, symbols: List[str]) -> List[str]:
    """Deterministic roles of a file (``routes``/``service``/.../``test``)."""
    roles: Set[str] = set()
    lowered = rel_path.lower()
    stem = Path(rel_path).stem.lower()

    if lowered.startswith("tests/") or stem.startswith("test_") or stem.endswith("_test"):
        roles.add("tests")

    for role, markers in _ROLE_FILE_MARKERS.items():
        if any(marker in stem for marker in markers):
            roles.add(role)

    for role, suffixes in _ROLE_SYMBOL_SUFFIXES.items():
        if any(symbol.endswith(suffix) for symbol in symbols for suffix in suffixes):
            roles.add(role)

    return sorted(roles)


def iter_source_files(root: Path) -> List[str]:
    """Every ``*.py`` file under ``root`` as sorted relative POSIX paths."""
    found: List[str] = []
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in parts):
            continue
        found.append(path.relative_to(root).as_posix())
    return sorted(found)


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _parse_symbols(source: str) -> Tuple[List[str], List[str]]:
    """Extract symbol names and imported modules from Python source.

    Import extraction mirrors :mod:`betrayer.ai.intelligence` exactly so the
    index-backed commands stay consistent with the original behaviour:

    * ``import a.b``       -> ``a``
    * ``from a.b import c`` -> ``a.b``
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], []
    symbols: Set[str] = set()
    imports: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return sorted(symbols), sorted(imports)


def scan_file(root: Path, rel_path: str) -> Dict[str, Any]:
    """Extract the index entry for a single source file."""
    path = root / rel_path
    try:
        stat = path.stat()
        mtime_ns, size = stat.st_mtime_ns, stat.st_size
    except OSError:
        mtime_ns, size = 0, 0
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        source = ""
    symbols, imports = _parse_symbols(source)
    return {
        "file": rel_path,
        "module": module_of(rel_path),
        "symbols": symbols,
        "imports": imports,
        "hash": _digest(path),
        "mtime_ns": mtime_ns,
        "size": size,
        "roles": classify(rel_path, symbols),
    }


# ── Index model ──────────────────────────────────────────────────


class FileEntry:
    """One indexed source file (plain dict on disk for transparency)."""

    __slots__ = ("file", "module", "symbols", "imports", "hash", "mtime_ns", "size", "roles")

    def __init__(self, data: Dict[str, Any]) -> None:
        self.file: str = data.get("file", "")
        self.module: str = data.get("module") or module_of(self.file)
        self.symbols: List[str] = list(data.get("symbols", []))
        self.imports: List[str] = list(data.get("imports", []))
        self.hash: str = data.get("hash", "")
        self.mtime_ns: int = int(data.get("mtime_ns", 0))
        self.size: int = int(data.get("size", 0))
        self.roles: List[str] = list(data.get("roles", []))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "module": self.module,
            "symbols": list(self.symbols),
            "imports": list(self.imports),
            "hash": self.hash,
            "mtime_ns": self.mtime_ns,
            "size": self.size,
            "roles": list(self.roles),
        }

    def record(self) -> Dict[str, Any]:
        """Record shape used by the intelligence layer (``file``/``symbols``/``imports``)."""
        return {
            "file": self.file,
            "module": self.module,
            "symbols": list(self.symbols),
            "imports": list(self.imports),
            "roles": list(self.roles),
        }


class ProjectIndex:
    """In-memory view of the persisted project index."""

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        data = data or {}
        self.version: int = int(data.get("version", 0))
        self.schema_hash: str = data.get("schema_hash", "")
        self.root: str = data.get("root", "")
        self.metadata: Dict[str, Any] = data.get("metadata", {}) or {}
        self.files: Dict[str, FileEntry] = {
            path: FileEntry(entry) for path, entry in (data.get("files") or {}).items()
        }
        self.packages: List[str] = list(data.get("packages", []))
        self.symbols: Dict[str, List[str]] = dict(data.get("symbols", {}))
        self.dependencies: Dict[str, List[str]] = dict(data.get("dependencies", {}))
        self.dependents: Dict[str, List[str]] = dict(data.get("dependents", {}))
        self.roles: Dict[str, List[str]] = dict(data.get("roles", {}))
        self.relationships: List[List[str]] = [list(edge) for edge in data.get("relationships", [])]
        self.config_hash: str = data.get("config_hash", "")

    # -- derived views ------------------------------------------------

    def records(self) -> List[Dict[str, Any]]:
        """All file records in deterministic (path sorted) order."""
        return [self.files[path].record() for path in sorted(self.files)]

    def tests(self) -> List[str]:
        return sorted(self.roles.get("tests", []))

    def summary(self) -> Dict[str, Any]:
        """Machine readable index overview (no timestamps -> deterministic)."""
        return {
            "version": self.version,
            "schema_hash": self.schema_hash,
            "total_files": len(self.files),
            "total_packages": len(self.packages),
            "total_symbols": len(self.symbols),
            "total_relationships": len(self.relationships),
            "roles": {role: len(files) for role, files in sorted(self.roles.items())},
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "schema_hash": self.schema_hash,
            "root": self.root,
            "config_hash": self.config_hash,
            "metadata": self.metadata,
            "packages": list(self.packages),
            "symbols": {name: list(paths) for name, paths in sorted(self.symbols.items())},
            "dependencies": {k: list(v) for k, v in sorted(self.dependencies.items())},
            "dependents": {k: list(v) for k, v in sorted(self.dependents.items())},
            "roles": {role: list(files) for role, files in sorted(self.roles.items())},
            "relationships": [list(edge) for edge in self.relationships],
            "files": {path: entry.to_dict() for path, entry in sorted(self.files.items())},
        }


class IndexResult:
    """Outcome of a :func:`refresh` call."""

    def __init__(self, index: ProjectIndex, mode: str, changed: Optional[List[str]] = None,
                 reason: Optional[str] = None) -> None:
        self.index = index
        self.mode = mode          # created | reused | incremental | rebuilt
        self.changed = list(changed or [])
        self.reason = reason

    def info(self) -> Dict[str, Any]:
        """Small dict attached to command output so an LLM sees freshness."""
        info = {"mode": self.mode, "path": INDEX_RELATIVE_PATH}
        info.update(self.index.summary())
        if self.changed:
            info["changed_files"] = list(self.changed)
        if self.reason:
            info["reason"] = self.reason
        return info

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<IndexResult mode={self.mode} files={len(self.index.files)}>"


# ── Build / refresh ──────────────────────────────────────────────


def _read_metadata(root: Path) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for name in _METADATA_FILES:
        path = root / ".betrayer" / name
        if not path.is_file():
            continue
        try:
            meta[name[: -len(".json")]] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return meta


def _config_hash(root: Path) -> str:
    hasher = hashlib.sha256()
    for name in _CONFIG_FILES + tuple(f".betrayer/{m}" for m in _METADATA_FILES):
        path = root / name
        hasher.update(name.encode())
        hasher.update(_digest(path).encode())
    return hasher.hexdigest()


def _recompute(index: ProjectIndex) -> ProjectIndex:
    """Recompute derived data (packages, symbols, deps, dependents, roles).

    Cheap: no file is read, only in-memory relations.  Called after every
    refresh so the persisted index can never drift from its file entries.
    """
    modules = {entry.module for entry in index.files.values()}

    packages: Set[str] = set()
    symbols: Dict[str, List[str]] = {}
    roles: Dict[str, List[str]] = {}
    dependencies: Dict[str, List[str]] = {}
    reverse: Dict[str, Set[str]] = {}
    edges: Set[Tuple[str, str]] = set()

    for path in sorted(index.files):
        entry = index.files[path]
        segments = entry.module.split(".")
        if segments[0] and segments[0] not in _MODULE_ROOT_EXCLUDES:
            packages.update(".".join(segments[:i]) for i in range(1, len(segments) + 1))
        for symbol in entry.symbols:
            symbols.setdefault(symbol, []).append(path)
        for role in entry.roles:
            roles.setdefault(role, []).append(path)

        # Dependency edges: an import naming an indexed module.
        internal = sorted({name for name in entry.imports if name in modules})
        dependencies[path] = internal
        for name in internal:
            reverse.setdefault(name, set()).add(entry.module)
            edges.add((path, name))

    index.packages = sorted(packages)
    index.symbols = {name: sorted(paths) for name, paths in sorted(symbols.items())}
    index.roles = {role: sorted(files) for role, files in sorted(roles.items())}
    index.dependencies = dict(sorted(dependencies.items()))

    dependents: Dict[str, List[str]] = {}
    for target_module, sources in reverse.items():
        targets = sorted(
            path for path, entry in index.files.items() if entry.module == target_module
        )
        for target in targets:
            dependents[target] = sorted(sources)
    index.dependents = dict(sorted(dependents.items()))
    index.relationships = [list(edge) for edge in sorted(edges)]
    return index


def _build(root: Path) -> ProjectIndex:
    index = ProjectIndex({
        "version": INDEX_VERSION,
        "schema_hash": SCHEMA_HASH,
        "root": str(root),
        "config_hash": _config_hash(root),
        "metadata": _read_metadata(root),
        "files": {},
    })
    for rel in iter_source_files(root):
        index.files[rel] = FileEntry(scan_file(root, rel))
    return _recompute(index)


def _load(root: Path) -> Tuple[Optional[ProjectIndex], Optional[str]]:
    """Load the persisted index, or explain why it is unusable."""
    path = root / Path(INDEX_RELATIVE_PATH)
    if not path.is_file():
        return None, "no index found"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - unreadable file
        return None, f"index unreadable: {exc}"
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return None, f"corrupt index: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return None, "corrupt index: unexpected structure"
    index = ProjectIndex(data)
    if index.version != INDEX_VERSION:
        return None, f"incompatible index version {index.version} != {INDEX_VERSION}"
    if index.schema_hash != SCHEMA_HASH:
        return None, "index built by a different extractor"
    expected_root = str(root)
    if index.root and index.root != expected_root:
        return None, "index belongs to a different project"
    if index.config_hash != _config_hash(root):
        return None, "project configuration changed"
    return index, None


def _diff(root: Path, index: ProjectIndex) -> Tuple[List[str], List[str], List[str]]:
    """Return ``(added, removed, modified)`` project-relative paths."""
    current = iter_source_files(root)
    known = set(index.files)

    added: List[str] = []
    modified: List[str] = []
    for rel in current:
        entry = index.files.get(rel)
        if entry is None:
            added.append(rel)
            continue
        path = root / rel
        try:
            stat = path.stat()
        except OSError:
            modified.append(rel)
            continue
        if stat.st_mtime_ns == entry.mtime_ns and stat.st_size == entry.size:
            continue  # cheap check: unchanged
        if _digest(path) == entry.hash:
            # Content identical (touch only) — refresh stat, no re-parse.
            entry.mtime_ns, entry.size = stat.st_mtime_ns, stat.st_size
            continue
        modified.append(rel)

    removed = sorted(known - set(current))
    return added, removed, modified


def _save(root: Path, index: ProjectIndex) -> Path:
    """Atomically persist the index (temp file + replace)."""
    path = root / Path(INDEX_RELATIVE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(index.to_dict(), indent=2, sort_keys=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return path


def refresh(root: Optional[Path] = None, force: bool = False) -> IndexResult:
    """Return an up-to-date index, reusing persisted data when possible.

    ``mode`` reports what happened: ``created`` (first run), ``reused`` (nothing
    changed), ``incremental`` (only changed files re-indexed) or ``rebuilt``
    (forced, corrupt, stale-version or configuration change).
    """
    project_root = find_project_root(root)

    if force:
        index = _build(project_root)
        _save(project_root, index)
        return IndexResult(index, "rebuilt", reason="forced rebuild")

    index, reason = _load(project_root)
    if index is None:
        index = _build(project_root)
        _save(project_root, index)
        return IndexResult(index, "created" if reason == "no index found" else "rebuilt", reason=reason)

    added, removed, modified = _diff(project_root, index)
    if not added and not removed and not modified:
        return IndexResult(index, "reused")

    for rel in added + modified:
        index.files[rel] = FileEntry(scan_file(project_root, rel))
    for rel in removed:
        index.files.pop(rel, None)
    index.root = str(project_root)
    index.metadata = _read_metadata(project_root)
    index.config_hash = _config_hash(project_root)
    _recompute(index)
    _save(project_root, index)

    changed = sorted(added + removed + modified)
    return IndexResult(index, "incremental", changed=changed)


def get_index(root: Optional[Path] = None) -> ProjectIndex:
    """Convenience accessor: the always-current :class:`ProjectIndex`."""
    return refresh(root).index


def rebuild(root: Optional[Path] = None) -> IndexResult:
    """Force a full rebuild of the index."""
    return refresh(root, force=True)


def clear(root: Optional[Path] = None) -> bool:
    """Delete the persisted index. Returns ``True`` when a file was removed."""
    path = index_path(root)
    if path.is_file():
        path.unlink()
        return True
    return False


def status(root: Optional[Path] = None) -> Dict[str, Any]:
    """Cache state without building anything (machine readable)."""
    project_root = find_project_root(root)
    path = project_root / Path(INDEX_RELATIVE_PATH)
    info: Dict[str, Any] = {
        "success": True,
        "path": INDEX_RELATIVE_PATH,
        "absolute_path": str(path),
        "project_root": str(project_root),
        "exists": path.is_file(),
        "valid": False,
        "reason": None,
        "version": INDEX_VERSION,
        "schema_hash": SCHEMA_HASH,
    }
    if not path.is_file():
        info["reason"] = "no index found"
        return info
    index, reason = _load(project_root)
    if index is None:
        info["reason"] = reason
        return info
    info["valid"] = True
    info.update(index.summary())
    return info


# ── Query API (powered by the shared index) ─────────────────────


def _terms(target: Optional[str]) -> List[str]:
    if not target:
        return []
    return [t for t in target.lower().lstrip("/").split("/") if t]


def _match(entry: FileEntry, terms: List[str]) -> bool:
    hay = entry.file.lower()
    symbols = [s.lower() for s in entry.symbols]
    return any(t in hay or any(t in s for s in symbols) for t in terms)


def _select(target: Optional[str], index: ProjectIndex) -> List[str]:
    terms = _terms(target)
    if not terms:
        return sorted(index.files)
    return sorted(p for p, e in index.files.items() if _match(e, terms))


def _cap_lookup(terms: List[str], files: List[str], index: ProjectIndex) -> List[str]:
    """Map a target onto Betrayer capabilities (same logic as intelligence.py)."""
    try:
        from betrayer.ai import discover
    except Exception:  # pragma: no cover
        return []
    queries = list(dict.fromkeys(terms))
    for path in files:
        for seg in module_of(path).split("."):
            if seg and seg not in {"betrayer", "tests", "example"}:
                queries.append(seg)
    names: List[str] = []
    seen: Set[str] = set()
    for q in queries:
        try:
            for r in discover.search(q):
                n = r.get("name")
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)
        except Exception:  # pragma: no cover
            continue
    return names


def inspect(target: Optional[str] = None) -> Dict[str, Any]:
    """Project overview or entity view, powered by the shared index."""
    result = refresh()
    index = result.index
    records = index.records()
    selected = _select(target, index)

    manifest = index.metadata.get("manifest", {})
    architecture = index.metadata.get("architecture", {})

    return {
        "success": True,
        "target": target,
        "project_root": ".",
        "total_files": len(records),
        "total_packages": len(index.packages),
        "framework": manifest.get("framework"),
        "version": manifest.get("version"),
        "architecture_version": manifest.get("architecture_version"),
        "commands": manifest.get("commands", []),
        "layers": [layer.get("name") for layer in architecture.get("layers", [])],
        "packages": list(index.packages),
        "entities": [
            {"file": index.files[p].file, "module": index.files[p].module,
             "symbols": index.files[p].symbols}
            for p in selected
        ],
        "total_entities": len(selected),
        "index_info": result.info(),
    }


def context(target: str) -> Dict[str, Any]:
    """Concise context for ``target``: files, symbols, deps, tests, callers."""
    result = refresh()
    index = result.index
    selected = _select(target, index)
    selected_set = set(selected)
    terms = _terms(target)

    dependencies: Set[str] = set()
    for p in selected:
        for name in index.files[p].imports:
            if name not in {"betrayer", "__future__"}:
                dependencies.add(name)

    selected_symbols = {s.lower() for p in selected for s in index.files[p].symbols}
    related_tests: List[str] = []
    for p in sorted(index.files):
        if not p.startswith("tests/"):
            continue
        if any(t in p.lower() for t in terms):
            related_tests.append(p)
            continue
        if selected_symbols & {s.lower() for s in index.files[p].symbols}:
            related_tests.append(p)

    selected_segments = {module_of(p).split(".")[-1].lower() for p in selected}
    dependents: List[str] = []
    for p in sorted(index.files):
        if p in selected_set:
            continue
        if selected_segments & {n.lower() for n in index.files[p].imports}:
            dependents.append(p)

    return {
        "success": True,
        "target": target,
        "files": [
            {"file": index.files[p].file, "module": index.files[p].module,
             "symbols": index.files[p].symbols}
            for p in selected
        ],
        "symbols": sorted(selected_symbols),
        "dependencies": sorted(dependencies),
        "dependents": sorted(dependents),
        "related_tests": sorted(related_tests),
        "related_capabilities": _cap_lookup(terms, selected, index),
        "index_info": result.info(),
    }


def impact(target: str) -> Dict[str, Any]:
    """Project parts that a change to ``target`` may affect."""
    ctx = context(target)
    affected = sorted(set(ctx["dependents"]) | set(ctx["related_tests"]))
    return {
        "success": True,
        "target": target,
        "source_files": [entry["file"] for entry in ctx["files"]],
        "dependencies": ctx["dependencies"],
        "dependents": ctx["dependents"],
        "related_tests": ctx["related_tests"],
        "related_capabilities": ctx["related_capabilities"],
        "affected": affected,
        "affected_count": len(affected),
        "index_info": ctx.get("index_info", {}),
    }


def affected_tests(changed: Optional[List[str]] = None) -> Dict[str, Any]:
    """Map changed files to tests using the shared intelligence index."""
    import subprocess

    result = refresh()
    index = result.index

    if changed is None:
        changed = []
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"], cwd=Path(index.root or "."),
                capture_output=True, text=True, check=False,
            )
            changed = sorted({ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()})
            r = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"], cwd=Path(index.root or "."),
                capture_output=True, text=True, check=False,
            )
            changed = sorted(set(changed) | {ln.strip().replace("\\", "/") for ln in r.stdout.splitlines() if ln.strip()})
        except OSError:
            pass
    changed = sorted(set(changed))

    tests = [p for p in sorted(index.files) if p.startswith("tests/")]
    selected: Set[str] = set()
    reasons: Dict[str, Set[str]] = {}

    rev: Dict[str, Set[str]] = {}
    for rec in index.records():
        mod = rec["module"]
        for imp in rec["imports"]:
            if imp.startswith("betrayer.") and imp.count(".") >= 1:
                rev.setdefault(imp, set()).add(mod)

    for source in changed:
        if source.startswith("tests/"):
            selected.add(source)
            reasons.setdefault(source, set()).add("changed test")
            continue
        if not source.endswith(".py"):
            stem = Path(source).stem.lower()
            for t in tests:
                if stem and stem in t.lower():
                    selected.add(t)
                    reasons.setdefault(t, set()).add(source)
            continue

        changed_mod = module_of(source)
        affected_mods = {changed_mod} | rev.get(changed_mod, set())
        for t in tests:
            if module_of(t) in affected_mods:
                selected.add(t)
                reasons.setdefault(t, set()).add(f"imports/is {changed_mod}")

    return {
        "success": True,
        "changed_files": changed,
        "affected_tests": sorted(selected),
        "affected_count": len(selected),
        "determined": bool(selected),
        "reasons": {k: sorted(v) for k, v in sorted(reasons.items())},
        "note": None if selected else "no affected tests could be determined",
        "index_info": result.info(),
    }