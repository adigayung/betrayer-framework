"""Canonical Job contract for Betrayer.

A **Job** is a self-contained unit of work with a ``handle()`` method::

    class SendEmail(Job):
        def handle(self) -> JobResult:
            ...

Jobs are dispatched to a **Queue** and executed by a **JobRunner**::

    job = SendEmail(to="user@example.com", subject="Hello")
    queue.push(job)
    runner.run_once()  # pops one job from the queue and calls handle()

Every ``handle()`` returns a structured ``JobResult`` (success/failure).
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class JobStatus(Enum):
    """Lifecycle states of a job execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class JobResult:
    """Structured result returned by ``Job.handle()``.

    Always JSON-serialisable.  Follows the existing Betrayer error contract
    for failure reporting.
    """

    success: bool
    status: JobStatus = JobStatus.PENDING
    job: str = ""
    duration: float = 0.0
    error: Optional[Dict[str, Any]] = None

    @classmethod
    def ok(cls, job_name: str = "", duration: float = 0.0) -> JobResult:
        return cls(
            success=True,
            status=JobStatus.SUCCESS,
            job=job_name,
            duration=duration,
        )

    @classmethod
    def fail(
        cls,
        job_name: str = "",
        duration: float = 0.0,
        *,
        code: str = "JOB_FAILED",
        message: str = "",
        context: Optional[Dict[str, Any]] = None,
        suggested_actions: Optional[list[str]] = None,
    ) -> JobResult:
        return cls(
            success=False,
            status=JobStatus.FAILED,
            job=job_name,
            duration=duration,
            error={
                "code": code,
                "message": message,
                "context": context or {},
                "suggested_actions": suggested_actions or [],
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "job": self.job,
            "duration": round(self.duration, 4),
            "error": self.error,
        }

    def __bool__(self) -> bool:
        return self.success


class Job(ABC):
    """Canonical unit of work.

    Subclasses must implement ``handle()`` and return a ``JobResult``::

        class MyJob(Job):
            def handle(self) -> JobResult:
                try:
                    ...
                    return JobResult.ok("MyJob")
                except Exception as exc:
                    return JobResult.fail("MyJob", message=str(exc))
    """

    def __init__(self, **kwargs: Any) -> None:
        self._job_id: str = uuid.uuid4().hex[:12]
        self._created_at: float = time.time()
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def created_at(self) -> float:
        return self._created_at

    @abstractmethod
    def handle(self) -> JobResult:
        """Execute the job and return a structured result."""
        ...

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} id={self._job_id!r}>"


__all__ = [
    "Job",
    "JobResult",
    "JobStatus",
]