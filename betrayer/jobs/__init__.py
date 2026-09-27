"""Canonical Events / Jobs / Queue / Scheduler system.

One import for everything::

    from betrayer.jobs import (
        Job, JobResult,
        Queue, InMemoryQueue,
        JobRunner,
        Scheduler,
    )
"""

from __future__ import annotations

from betrayer.jobs.job import Job, JobResult, JobStatus
from betrayer.jobs.queue import Queue
from betrayer.jobs.runner import JobRunner
from betrayer.jobs.scheduler import Scheduler

__all__ = [
    "Job",
    "JobResult",
    "JobStatus",
    "Queue",
    "JobRunner",
    "Scheduler",
]