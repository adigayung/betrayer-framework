"""Canonical Scheduler abstraction.

Defines scheduled work based on time intervals::

    scheduler = Scheduler()
    scheduler.every(60).seconds.do(MyJob())  # every 60 seconds
    scheduler.every(5).minutes.do(MyJob())   # every 5 minutes

    due = scheduler.due_jobs()   # jobs whose interval has elapsed
    scheduler.run_due()          # execute all due jobs via the JobRunner
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from betrayer.jobs.job import Job, JobResult
from betrayer.jobs.queue import Queue
from betrayer.jobs.runner import JobRunner


@dataclass
class _ScheduleEntry:
    """Internal representation of one scheduled job."""

    name: str
    job: Job
    interval_seconds: float
    last_run_at: float = 0.0
    run_count: int = 0

    def is_due(self, now: float) -> bool:
        """Return True if this entry's interval has elapsed since last run."""
        return (now - self.last_run_at) >= self.interval_seconds


class _IntervalBuilder:
    """Fluent API for ``scheduler.every(N).seconds.do(job)``."""

    def __init__(self, scheduler: Scheduler, interval: float) -> None:
        self._scheduler = scheduler
        self._interval = interval

    @property
    def seconds(self) -> "_TimingBuilder":
        return _TimingBuilder(self._scheduler, self._interval)

    @property
    def minutes(self) -> "_TimingBuilder":
        return _TimingBuilder(self._scheduler, self._interval * 60)

    @property
    def hours(self) -> "_TimingBuilder":
        return _TimingBuilder(self._scheduler, self._interval * 3600)


class _TimingBuilder:
    """Fluent API that accepts ``.do(job)``."""

    def __init__(self, scheduler: Scheduler, interval_seconds: float) -> None:
        self._scheduler = scheduler
        self._interval_seconds = interval_seconds

    def do(self, job: Job) -> _ScheduleEntry:
        return self._scheduler._add(job, self._interval_seconds)


class Scheduler:
    """Simple interval-based scheduler.

    All time is measured via ``time.time()`` by default; inject a custom
    ``clock`` function for deterministic testing.

    Usage::

        scheduler = Scheduler(queue=my_queue)
        scheduler.every(30).seconds.do(SendEmail(to="user@example.com"))
        scheduler.run_due()  # run jobs whose interval has elapsed
    """

    def __init__(
        self,
        queue: Optional[Queue] = None,
        runner: Optional[JobRunner] = None,
        *,
        clock=None,
    ) -> None:
        self._queue = queue or Queue()
        self._runner = runner or JobRunner(self._queue)
        self._entries: Dict[str, _ScheduleEntry] = {}
        self._clock = clock or time.time

    @property
    def queue(self) -> Queue:
        return self._queue

    @property
    def runner(self) -> JobRunner:
        return self._runner

    # -- fluent API ----------------------------------------------------

    def every(self, interval: float) -> _IntervalBuilder:
        """Start a fluent chain: ``scheduler.every(30).seconds.do(job)``."""
        return _IntervalBuilder(self, interval)

    # -- canonical API -------------------------------------------------

    def schedule(self, job: Job, interval_seconds: float) -> _ScheduleEntry:
        """Schedule a Job to run every ``interval_seconds`` seconds."""
        return self._add(job, interval_seconds)

    def due_jobs(self) -> List[Job]:
        """Return Jobs whose interval has elapsed since last run."""
        now = self._clock()
        due: List[Job] = []
        for entry in list(self._entries.values()):
            if entry.is_due(now):
                due.append(entry.job)
        return due

    def run_due(self) -> List[JobResult]:
        """Execute all due Jobs and return their results."""
        results: List[JobResult] = []
        for job in self.due_jobs():
            result = self._runner.execute(job)
            self._mark_run(job)
            results.append(result)
        return results

    # -- introspection -------------------------------------------------

    def list_jobs(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": entry.name,
                "job": type(entry.job).__name__,
                "interval_seconds": entry.interval_seconds,
                "last_run_at": entry.last_run_at,
                "run_count": entry.run_count,
            }
            for entry in self._entries.values()
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scheduled": len(self._entries),
            "jobs": self.list_jobs(),
        }

    # -- internal ------------------------------------------------------

    def _add(self, job: Job, interval_seconds: float) -> _ScheduleEntry:
        name = f"{type(job).__name__}_{job.job_id}"
        entry = _ScheduleEntry(
            name=name,
            job=job,
            interval_seconds=interval_seconds,
            last_run_at=self._clock(),
        )
        self._entries[name] = entry
        return entry

    def _mark_run(self, job: Job) -> None:
        now = self._clock()
        name = f"{type(job).__name__}_{job.job_id}"
        entry = self._entries.get(name)
        if entry is not None:
            entry.last_run_at = now
            entry.run_count += 1

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Scheduler jobs={len(self._entries)}>"


__all__ = ["Scheduler"]