"""Transaction abstraction: context manager for atomic database operations.

Provides a ``Transaction`` context that wraps a database connection,
supporting commit on success and rollback on exception.

Contract (Task 09.1)
--------------------
* ``Transaction`` is a context manager (``with transaction: ...``).
* ``commit()`` and ``rollback()`` are explicit for non-context-manager usage.
* Semantics:

    enter -> BEGIN -> operations -> success -> COMMIT
    exception -> ROLLBACK -> re-raise original exception

* The transaction never swallows exceptions.
* Lifecycle: CREATED → ACTIVE → COMMITTED / ROLLED_BACK / FAILED.

The transaction drives COMMIT/ROLLBACK through the ``Connection`` contract;
a fallback keeps working with older engines that expose ``commit()`` /
``rollback()`` methods directly (backward compatibility).
"""

from __future__ import annotations

import threading
from enum import Enum
from types import TracebackType
from typing import Any, Dict, Optional, Type, Union

from betrayer.core.lifecycle import LifecycleState
from betrayer.data.database import Connection, DatabaseEngine, DatabaseManager
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
    an exception the transaction is committed; on exception it is rolled back
    and the original exception is re-raised.

    Parameters
    ----------
    database : DatabaseManager
        The database manager whose connection is used.
    connection : Optional[Connection]
        Optional explicit connection (defaults to the manager's active
        connection, or the engine's own ``connect()`` when available).
    savepoint : Optional[str]
        Optional savepoint name for nested transactions.
    """

    def __init__(
        self,
        database: Union[DatabaseManager, DatabaseEngine],
        connection: Optional[Connection] = None,
        savepoint: Optional[str] = None,
    ) -> None:
        self._database: Union[DatabaseManager, DatabaseEngine] = database
        self._engine: DatabaseEngine = (
            database.engine if isinstance(database, DatabaseManager) else database
        )
        self._connection: Optional[Connection] = connection
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
    def database(self) -> Union[DatabaseManager, DatabaseEngine]:
        """Database manager/engine bound to this transaction."""
        return self._database

    @property
    def connection(self) -> Optional[Connection]:
        """The connection used by this transaction (may be ``None``)."""
        return self._connection

    # ── Context manager ─────────────────────────────────────────────────

    def __enter__(self) -> Transaction:
        if self._state != TransactionState.CREATED:
            raise TransactionError(
                message=f"Cannot enter transaction in state {self._state.value}",
                stage="enter",
            )
        # Resolve the target connection (manager's active one or engine's own).
        self._connection = self._resolve_connection()
        if self._connection is None:
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
            return False  # re-raise the original exception
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

    # ── Resolution / engine hooks ───────────────────────────────────────

    def _resolve_connection(self) -> Optional[Connection]:
        if self._connection is not None:
            return self._connection
        if isinstance(self._database, DatabaseManager):
            if self._database.connected and self._database.connection is not None:
                return self._database.connection
            return None
        # Engine without a manager: use the engine's own connection.
        try:
            return self._engine.connect()
        except Exception:
            return None

    def _begin(self) -> None:
        """Begin the transaction on the underlying connection."""
        self._state = TransactionState.ACTIVE

    def _commit(self) -> None:
        """Execute commit on the underlying connection."""
        connection = self._connection
        if connection is not None:
            connection.commit()
            return
        # Backward compatibility: engines without a Connection object.
        engine = self._engine
        if hasattr(engine, "commit"):
            engine.commit()

    def _rollback(self) -> None:
        """Execute rollback on the underlying connection."""
        connection = self._connection
        if connection is not None:
            connection.rollback()
            return
        # Backward compatibility: engines without a Connection object.
        engine = self._engine
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
            "engine": type(self._engine).__name__,
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