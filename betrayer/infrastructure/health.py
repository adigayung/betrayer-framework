"""Health check abstraction for application/infrastructure dependencies.

Design decisions:
- ``HealthCheck`` is the abstract interface; concrete checks implement it.
- ``HealthChecker`` owns registered checks and runs them on demand.
- ``HealthCheckResult`` result with status, duration, details.
- ``HealthStatus`` enum: HEALTHY, DEGRADED, UNHEALTHY.
- Results are structured and easy to consume by agents/monitoring.
- No overlap with monitoring/observability — this is purely a dependency health
  snapshot.
- Checks are independent and fail-isolated (one failing check does not abort
  the others).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Health Status ──────────────────────────────────────────────────────


class HealthStatus(Enum):
    """Health status enum."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


# ── Health Check Result ────────────────────────────────────────────────


@dataclass
class HealthCheckResult:
    """Structured result from a single health check."""

    name: str
    status: HealthStatus
    duration: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializable representation."""
        return {
            "name": self.name,
            "status": self.status.value,
            "duration": self.duration,
            "details": self.details,
            "error": self.error,
        }

    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


# ── Health Check ───────────────────────────────────────────────────────


class HealthCheck(ABC):
    """Abstract health check."""

    name: str

    @abstractmethod
    def check(self) -> HealthCheckResult:
        """Run the health check and return a result."""
        ...


class HealthCheckRegistry:
    """Simple registry for named health check callables."""

    def __init__(self) -> None:
        self._checks: Dict[str, Callable[[], HealthCheckResult]] = {}

    def register(self, name: str, check_fn: Callable[[], HealthCheckResult]) -> None:
        """Register a health check function."""
        if name in self._checks:
            logger.warning("Health check '%s' already registered, overwriting", name)
        self._checks[name] = check_fn

    def unregister(self, name: str) -> None:
        """Unregister a health check."""
        self._checks.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._checks

    def list(self) -> List[str]:
        return list(self._checks.keys())

    def run(self, name: str) -> HealthCheckResult:
        """Run a single check by name."""
        check_fn = self._checks.get(name)
        if check_fn is None:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                details={},
                error=f"No check registered with name '{name}'",
            )
        start = time.monotonic()
        try:
            result = check_fn()
            if not isinstance(result, HealthCheckResult):
                result = HealthCheckResult(
                    name=name,
                    status=HealthStatus.HEALTHY,
                    details={"raw": result},
                )
            result.duration = time.monotonic() - start
            return result
        except Exception as exc:
            duration = time.monotonic() - start
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                duration=duration,
                details={},
                error=str(exc),
            )

    def run_all(self) -> Dict[str, HealthCheckResult]:
        """Run all registered checks."""
        results: Dict[str, HealthCheckResult] = {}
        for name in self._checks:
            results[name] = self.run(name)
        return results

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable representation of all checks."""
        return {
            "checks": {name: fn.__name__ for name, fn in self._checks.items()},
            "count": len(self._checks),
        }

    def __repr__(self) -> str:
        return f"HealthCheckRegistry(checks={len(self._checks)})"


class HealthChecker:
    """High-level health checker that wraps a registry with convenience methods.

    This is the main entry point for LLM/AETHER to run health checks.
    """

    def __init__(self) -> None:
        self._registry = HealthCheckRegistry()

    @property
    def registry(self) -> HealthCheckRegistry:
        return self._registry

    def register(self, name: str, check_fn: Callable[[], HealthCheckResult]) -> None:
        """Register a health check function."""
        self._registry.register(name, check_fn)

    def check(self, name: str) -> HealthCheckResult:
        """Run a single check by name."""
        return self._registry.run(name)

    def check_all(self) -> Dict[str, HealthCheckResult]:
        """Run all registered checks."""
        return self._registry.run_all()

    def summary(self) -> Dict[str, Any]:
        """Get a structured summary of all checks."""
        results = self.check_all()
        healthy = sum(1 for r in results.values() if r.is_healthy())
        unhealthy = sum(1 for r in results.values() if not r.is_healthy())
        return {
            "total": len(results),
            "healthy": healthy,
            "unhealthy": unhealthy,
            "checks": {name: r.to_dict() for name, r in results.items()},
        }


__all__ = [
    "HealthStatus",
    "HealthCheckResult",
    "HealthCheck",
    "HealthCheckRegistry",
    "HealthChecker",
]