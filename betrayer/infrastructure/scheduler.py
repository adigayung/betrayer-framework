"""Scheduler abstraction for scheduled task execution.

Design decisions:
- ``Scheduler`` is an abstract interface; concrete schedulers implement it.
- ``SimpleScheduler`` uses ``threading.Timer`` — no external scheduler dep.
- Scheduler does NOT auto-start on import; explicit ``start()`` / ``stop()``.
- Configuration is explicit via ``SchedulerConfig``.
- Each task is a callable with a cron-like or interval schedule.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from betrayer.infrastructure.exceptions import SchedulerError

logger = logging.getLogger(__name__)


class SchedulerState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ScheduleTask:
    """A single scheduled task definition."""

    name: str
    fn: Callable[..., Any]
    interval_seconds: float
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    run_immediately: bool = False
    max_runs: Optional[int] = None  # None = unlimited


@dataclass
class ScheduledJob:
    """Runtime state of a scheduled job."""

    task: ScheduleTask
    run_count: int = 0
    last_error: Optional[str] = None
    last_run_at: Optional[float] = None
    next_run_at: Optional[float] = None


@dataclass
class SchedulerConfig:
    """Configuration for the scheduler."""

    enabled: bool = False
    daemon: bool = True
    default_interval_seconds: float = 60.0


class Scheduler(ABC):
    """Abstract scheduler. Subclass to provide a concrete implementation."""

    @abstractmethod
    def start(self) -> None:
        """Start the scheduler."""

    @abstractmethod
    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler."""

    @abstractmethod
    def add_task(self, task: ScheduleTask) -> None:
        """Register a new scheduled task."""

    @abstractmethod
    def remove_task(self, name: str) -> None:
        """Remove a scheduled task by name."""

    @abstractmethod
    def list_tasks(self) -> List[ScheduledJob]:
        """Return snapshot of all scheduled jobs."""

    @abstractmethod
    def state(self) -> SchedulerState:
        """Return current scheduler state."""

    def introspect(self) -> Dict[str, Any]:
        """Return machine-readable metadata for LLM introspection."""
        return {
            "state": self.state().value,
            "tasks": [
                {
                    "name": j.task.name,
                    "interval_seconds": j.task.interval_seconds,
                    "run_count": j.run_count,
                    "last_error": j.last_error,
                    "last_run_at": j.last_run_at,
                }
                for j in self.list_tasks()
            ],
        }


class SimpleScheduler(Scheduler):
    """Lightweight scheduler using ``threading.Timer``.

    Suitable for development and simple use cases. For production,
    replace with APScheduler or similar via the Scheduler interface.
    """

    def __init__(self, config: Optional[SchedulerConfig] = None) -> None:
        self._config = config or SchedulerConfig()
        self._tasks: Dict[str, ScheduleTask] = {}
        self._jobs: Dict[str, ScheduledJob] = {}
        self._timers: Dict[str, threading.Timer] = {}
        self._state = SchedulerState.STOPPED
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._state is SchedulerState.RUNNING:
            return
        self._state = SchedulerState.RUNNING
        # Schedule existing tasks
        for name, task in list(self._tasks.items()):
            if task.run_immediately:
                self._run_task(name)
            else:
                self._schedule_task(name)
        logger.info("Scheduler started with %d task(s)", len(self._tasks))

    def stop(self, wait: bool = True) -> None:
        self._state = SchedulerState.STOPPED
        for name, timer in list(self._timers.items()):
            timer.cancel()
        self._timers.clear()
        logger.info("Scheduler stopped")

    def add_task(self, task: ScheduleTask) -> None:
        if task.name in self._tasks:
            raise SchedulerError(f"Task '{task.name}' already registered")
        self._tasks[task.name] = task
        self._jobs[task.name] = ScheduledJob(task=task)
        if self._state is SchedulerState.RUNNING:
            if task.run_immediately:
                self._run_task(task.name)
            else:
                self._schedule_task(task.name)

    def remove_task(self, name: str) -> None:
        if name not in self._tasks:
            raise SchedulerError(f"Task '{name}' not found")
        timer = self._timers.pop(name, None)
        if timer:
            timer.cancel()
        self._tasks.pop(name, None)
        self._jobs.pop(name, None)

    def list_tasks(self) -> List[ScheduledJob]:
        return list(self._jobs.values())

    def state(self) -> SchedulerState:
        return self._state

    def _schedule_task(self, name: str) -> None:
        task = self._tasks.get(name)
        if not task or self._state is not SchedulerState.RUNNING:
            return
        timer = threading.Timer(task.interval_seconds, self._run_task, args=[name])
        timer.daemon = self._config.daemon
        timer.start()
        self._timers[name] = timer
        job = self._jobs.get(name)
        if job:
            job.next_run_at = (
                __import__("time").time() + task.interval_seconds
            )

    def _run_task(self, name: str) -> None:
        task = self._tasks.get(name)
        if not task or self._state is not SchedulerState.RUNNING:
            return
        job = self._jobs.get(name)
        try:
            task.fn(*task.args, **task.kwargs)
            if job:
                job.run_count += 1
                job.last_error = None
                job.last_run_at = __import__("time").time()
        except Exception as exc:
            logger.error("Task '%s' failed: %s", name, exc)
            if job:
                job.last_error = f"{type(exc).__name__}: {exc}"
                job.last_run_at = __import__("time").time()
        finally:
            # Re-schedule if unlimited runs or under limit
            if task.max_runs is None or (job and job.run_count < task.max_runs):
                self._schedule_task(name)


__all__ = [
    "Scheduler",
    "SimpleScheduler",
    "SchedulerConfig",
    "SchedulerState",
    "ScheduleTask",
    "ScheduledJob",
]