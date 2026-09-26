"""Transaction abstraction: context manager for atomic database operations.

Provides a ``Transaction`` context that wraps a database connection,
supporting commit on success and rollback on exception.

Design rules:
- ``Transaction`` is a context manager (``with transaction: ...``).
- ``commit()`` and ``rollback()`` are explicit for non-context-manager usage.
- Lifecycle: CREATED → ACTIVE → COMMITTED / ROLLED_BACK.
- Integrates with DatabaseManager to obtain a connection.
- No second transaction manager — this is the single abstraction.
"""

from __future__ import annotations

import threading
from enum import Enum
from types import TracebackType
from typing import Any, Dict, Optional, Type

from betrayer.core.lifecycle import LifecycleState
from betrayer.data.database import DatabaseManager
from betrayer.data.exceptions import TransactionError


class TransactionState(Enum):
    """Deterministic states for a transaction."""

    CREATED = "created"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class Transaction:
    """A single database transaction with explicit lifecycle.

    ``Transaction`` is a context manager.  When the context exits without
    an exception the transaction is committed; on exception it is rolled back.

    Parameters
    ----------
    database : DatabaseManager
        The database manager whose connection is used.
    savepoint : Optional[str]
        Optional savepoint name for nested transactions.
    """

    def __init__(
        self,
        database: DatabaseManager,
        savepoint: Optional[str] = None,
    ) -> None:
        self._database: DatabaseManager = database
        self._state: TransactionState = TransactionState.CREATED
        self._savepoint: Optional[str] = savepoint
        self._lock = threading.Lock()

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def state(self) -> TransactionState:
        """Current transaction state."""
        return self._state

    @property
    def is_active(self) -> bool:
        """True when the transaction is active (not yet committed/rolled back)."""
        return self._state == TransactionState.ACTIVE

    @property
    def database(self) -> DatabaseManager:
        """Database manager bound to this transaction."""
        return self._database

    # ── Context manager ─────────────────────────────────────────────────

    def __enter__(self) -> Transaction:
        if self._state != TransactionState.CREATED:
            raise TransactionError(
                message=f"Cannot enter transaction in state {self._state.value}",
                stage="enter",
            )
        if not self._database.connected:
            raise TransactionError(
                message="Database is not connected",
                stage="enter",
            )
        self._begin()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        if exc_type is not None:
            self.rollback()
            return False  # re-raise
        self.commit()
        return None

    # ── Public API ──────────────────────────────────────────────────────

    def commit(self) -> None:
        """Commit the transaction."""
        with self._lock:
            if self._state != TransactionState.ACTIVE:
                raise TransactionError(
                    message=f"Cannot commit in state {self._state.value}",
                    stage="commit",
                )
            try:
                self._commit()
                self._state = TransactionState.COMMITTED
            except Exception as exc:
                self._state = TransactionState.FAILED
                raise TransactionError(
                    message="Commit failed",
                    stage="commit",
                    cause=exc,
                ) from exc

    def rollback(self) -> None:
        """Roll back the transaction."""
        with self._lock:
            if self._state not in (TransactionState.ACTIVE, TransactionState.FAILED):
                raise TransactionError(
                    message=f"Cannot rollback in state {self._state.value}",
                    stage="rollback",
                )
            try:
                self._rollback()
                self._state = TransactionState.ROLLED_BACK
            except Exception as exc:
                self._state = TransactionState.FAILED
                raise TransactionError(
                    message="Rollback failed",
                    stage="rollback",
                    cause=exc,
                ) from exc

    # ── Engine hooks (override in concrete backends) ────────────────────

    def _begin(self) -> None:
        """Begin the transaction on the underlying connection."""
        self._state = TransactionState.ACTIVE

    def _commit(self) -> None:
        """Execute commit on the underlying connection."""
        engine = self._database._engine
        if hasattr(engine, "commit"):
            engine.commit()

    def _rollback(self) -> None:
        """Execute rollback on the underlying connection."""
        engine = self._database._engine
        if hasattr(engine, "rollback"):
            engine.rollback()

    # ── Introspection ───────────────────────────────────────────────────

    def introspect(self) -> Dict[str, Any]:
        """Machine readable metadata for LLM inspection."""
        return {
            "type": "transaction",
            "state": self._state.value,
            "savepoint": self._savepoint,
            "database": str(self._database),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Transaction(state={self._state.value}, "
            f"savepoint={self._savepoint!r})"
        )


__all__ = [
    "Transaction",
    "TransactionState",
]