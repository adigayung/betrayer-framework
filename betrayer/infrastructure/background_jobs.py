"""Background jobs abstraction for asynchronous task execution.

Design decisions:
- ``JobRunner`` is an abstract interface; concrete runners implement it.
- ``SimpleJobRunner`` uses a thread pool (``concurrent.futures.ThreadPoolExecutor``).
- Job lifecycle states (PENDING, RUNNING, SUCCESS, FAILED) are explicit.
- Error state is captured and exposed for LLM introspection.
- No overlap with Scheduler: scheduler is for periodic execution,
  background jobs are for one-off async tasks triggered on demand.
"""

from __future__ import annotations

import enum
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ── Job lifecycle ────────────────────────────────────────────────


class JobState(enum.Enum):
    """Explicit lifecycle states for a background job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


# ── Data objects ─────────────────────────────────────────────────


@dataclass
class Job:
    """A single background job with tracked metadata."""

    id: str
    name: str
    state: JobState = JobState.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Any = None


@dataclass
class BackgroundJobConfig:
    """Explicit configuration for a background job runner."""

    max_workers: int = 4
    job_queue_maxsize: int = 0  # 0 = unlimited


# ── Abstraction ──────────────────────────────────────────────────


class JobRunner:
    """Abstract interface for background job execution.

    Subclasses implement ``_run_job`` and provide the execution context.
    """

    def __init__(self, config: Optional[BackgroundJobConfig] = None) -> None:
        self._config = config or BackgroundJobConfig()
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    # -- public API -------------------------------------------------

    @property
    def config(self) -> BackgroundJobConfig:
        """Return the runner configuration."""
        return self._config

    def submit(
        self,
        fn: Callable[..., Any],
        *args: Any,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Submit a job for execution. Returns the job ID."""
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, name=name or fn.__name__)
        self._register_job(job)
        self._execute_async(job, fn, args, kwargs)
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[Job]:
        """List all tracked jobs."""
        with self._lock:
            return list(self._jobs.values())

    def list_jobs_by_state(self, state: JobState) -> List[Job]:
        """List jobs filtered by state."""
        return [j for j in self.list_jobs() if j.state == state]

    def has_job(self, job_id: str) -> bool:
        """Check if a job exists."""
        return self.get_job(job_id) is not None

    @property
    def pending_count(self) -> int:
        return len(self.list_jobs_by_state(JobState.PENDING))

    @property
    def running_count(self) -> int:
        return len(self.list_jobs_by_state(JobState.RUNNING))

    @property
    def failed_count(self) -> int:
        return len(self.list_jobs_by_state(JobState.FAILED))

    @property
    def success_count(self) -> int:
        return len(self.list_jobs_by_state(JobState.SUCCESS))

    def report(self) -> Dict[str, Any]:
        """Return structured metadata for LLM introspection."""
        return {
            "type": type(self).__name__,
            "config": {
                "max_workers": self._config.max_workers,
            },
            "jobs": {
                "total": len(self._jobs),
                "pending": self.pending_count,
                "running": self.running_count,
                "success": self.success_count,
                "failed": self.failed_count,
            },
        }

    # -- internal ---------------------------------------------------

    def _register_job(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def _execute_async(self, job: Job, fn: Callable, args: tuple, kwargs: dict) -> None:
        raise NotImplementedError  # pragma: no cover


class SimpleJobRunner(JobRunner):
    """Default thread-pool based background job runner.

    Uses ``threading.Thread`` with a shared work queue. Designed for
    development and moderate workloads.
    """

    def __init__(self, config: Optional[BackgroundJobConfig] = None) -> None:
        super().__init__(config)
        self._work_queue: queue.Queue = queue.Queue(maxsize=self._config.job_queue_maxsize)
        self._workers: List[threading.Thread] = []
        self._running = False

    def start(self) -> None:
        """Start worker threads."""
        if self._running:
            return
        self._running = True
        for _ in range(self._config.max_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop worker threads gracefully."""
        self._running = False
        for _ in self._workers:
            self._work_queue.put(None)  # sentinel
        for t in self._workers:
            t.join(timeout=timeout)
        self._workers.clear()

    def _worker_loop(self) -> None:
        while self._running:
            item = self._work_queue.get()
            if item is None:
                break
            job, fn, args, kwargs = item
            self._execute_job_sync(job, fn, args, kwargs)

    def _execute_async(self, job: Job, fn: Callable, args: tuple, kwargs: dict) -> None:
        self._work_queue.put((job, fn, args, kwargs))

    @staticmethod
    def _execute_job_sync(job: Job, fn: Callable, args: tuple, kwargs: dict) -> None:
        job.state = JobState.RUNNING
        job.started_at = time.time()
        try:
            result = fn(*args, **kwargs)
            job.state = JobState.SUCCESS
            job.result = result
        except Exception as exc:
            job.state = JobState.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = time.time()


# ── Convenience factory ──────────────────────────────────────────


def create_job_runner(config: Optional[BackgroundJobConfig] = None) -> SimpleJobRunner:
    """Create a pre-configured SimpleJobRunner.

    This is the recommended way to get a job runner for development.
    """
    runner = SimpleJobRunner(config=config)
    runner.start()
    return runner


__all__ = [
    "JobState",
    "Job",
    "BackgroundJobConfig",
    "JobRunner",
    "SimpleJobRunner",
    "create_job_runner",
]