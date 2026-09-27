"""Canonical JobRunner.

Pops Jobs from a Queue, calls ``handle()``, and returns structured results::

    runner = JobRunner(queue)
    result = runner.run_once()   # one job
    results = runner.run_available()  # all available jobs
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from betrayer.jobs.job import Job, JobResult, JobStatus
from betrayer.jobs.queue import Queue


class JobRunner:
    """Executes Jobs from a Queue.

    Does **not** create background threads or worker processes.  All
    execution is synchronous and single-threaded — that is intentional
    for this canonical layer.  A future QueueBackend or adapter can add
    async/threaded execution without changing the Job contract.
    """

    def __init__(self, queue: Queue) -> None:
        self._queue = queue

    @property
    def queue(self) -> Queue:
        return self._queue

    # -- execution -----------------------------------------------------

    def run_once(self) -> Optional[JobResult]:
        """Pop one Job from the queue, execute it, return the result.

        Returns ``None`` if the queue was empty.
        """
        job = self._queue.pop()
        if job is None:
            return None
        return self._execute(job)

    def run_available(self) -> List[JobResult]:
        """Execute every Job currently in the queue, draining it.

        Jobs are executed in FIFO order.  A failing job does **not** stop
        the remaining jobs from executing.
        """
        results: List[JobResult] = []
        while True:
            result = self.run_once()
            if result is None:
                break
            results.append(result)
        return results

    def execute(self, job: Job) -> JobResult:
        """Execute a single Job directly without the queue.

        This is useful for testing or immediate synchronous execution::

            result = runner.execute(MyJob())
        """
        return self._execute(job)

    # -- introspection -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runner": type(self).__name__,
            "queue": self._queue.name,
        }

    # -- internal ------------------------------------------------------

    def _execute(self, job: Job) -> JobResult:
        start = time.time()
        job_name = type(job).__name__
        try:
            result = job.handle()
            if not isinstance(result, JobResult):
                # Treat any non-JobResult return as success
                elapsed = time.time() - start
                return JobResult.ok(job_name=job_name, duration=elapsed)
            result.job = job_name
            result.duration = time.time() - start
            return result
        except Exception as exc:
            elapsed = time.time() - start
            return JobResult.fail(
                job_name=job_name,
                duration=elapsed,
                code="JOB_HANDLE_ERROR",
                message=f"{type(exc).__name__}: {exc}",
                suggested_actions=[
                    "Check the job handle() implementation",
                    "Verify job dependencies are available",
                ],
            )


__all__ = ["JobRunner"]