"""Storage abstraction: file storage with swappable backends.

Provides a ``StorageBackend`` interface and a ``StorageManager``.
The default backend is the local filesystem.  Path handling is safe,
predictable, and Windows-compatible (uses ``pathlib``).

Design rules:
- ``StorageBackend`` has: save, read, exists, delete.
- ``StorageManager`` wraps a backend and enforces a base path / namespace.
- No upload/web handling in this layer.
"""

from __future__ import annotations

import abc
import io
import os
import pathlib
from typing import BinaryIO, Optional, Union

from betrayer.data.exceptions import StorageError


class StorageBackend(abc.ABC):
    """Abstract storage backend."""

    @abc.abstractmethod
    def save(self, path: str, content: Union[bytes, BinaryIO]) -> None:
        """Write content to the given path."""
        ...

    @abc.abstractmethod
    def read(self, path: str) -> bytes:
        """Read and return the content at path as bytes."""
        ...

    @abc.abstractmethod
    def exists(self, path: str) -> bool:
        """Return True if the path exists."""
        ...

    @abc.abstractmethod
    def delete(self, path: str) -> None:
        """Remove the resource at path."""
        ...

    @abc.abstractmethod
    def metadata(self) -> dict:
        """Return backend metadata for introspection."""
        ...


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage backend.

    Operates within a *root* directory and prevents path traversal.
    """

    def __init__(self, root: Optional[Union[str, pathlib.Path]] = None) -> None:
        self._root = pathlib.Path(root or ".").resolve()

    @property
    def root(self) -> pathlib.Path:
        return self._root

    def _resolve(self, path: str) -> pathlib.Path:
        """Resolve a relative path safely inside the root directory."""
        candidate = (self._root / path).resolve()
        # Prevent path traversal
        try:
            candidate.relative_to(self._root)
        except ValueError:
            raise StorageError(
                message=f"Path traversal detected: {path}",
                stage="resolve",
            )
        return candidate

    def save(self, path: str, content: Union[bytes, BinaryIO]) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            with target.open("wb") as f:
                while True:
                    chunk = content.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

    def read(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.is_file():
            raise StorageError(
                message=f"File not found: {path}",
                stage="read",
            )
        return target.read_bytes()

    def exists(self, path: str) -> bool:
        target = self._resolve(path)
        return target.is_file()

    def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.is_file():
            target.unlink()

    def metadata(self) -> dict:
        return {
            "backend": "local",
            "root": str(self._root),
        }


class StorageManager:
    """Owning wrapper around a ``StorageBackend``."""

    def __init__(self, backend: Optional[StorageBackend] = None) -> None:
        self._backend: StorageBackend = backend or LocalStorageBackend()

    @property
    def backend(self) -> StorageBackend:
        return self._backend

    def save(self, path: str, content: Union[bytes, BinaryIO]) -> None:
        self._backend.save(path, content)

    def read(self, path: str) -> bytes:
        return self._backend.read(path)

    def exists(self, path: str) -> bool:
        return self._backend.exists(path)

    def delete(self, path: str) -> None:
        self._backend.delete(path)

    def metadata(self) -> dict:
        return {
            "manager": "StorageManager",
            "backend": self._backend.metadata(),
        }


__all__ = [
    "StorageBackend",
    "StorageManager",
    "LocalStorageBackend",
]