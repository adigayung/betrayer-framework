# tests/test_events_jobs.py — Events / Jobs / Queue / Scheduler Tests (Task 14)
"""Focused tests for the canonical Events/Jobs/Queue/Scheduler system.

Covers:
- Events: dispatch, listener invocation, multiple listeners, error handling
- Jobs: synchronous execution, success, failure, structured result/error
- Queue: push/pop, FIFO, empty, size, clear
- Runner: run_once, run_available, multiple jobs, failed job behavior
- Scheduler: schedule, due detection, run_due, deterministic time testing
- Integration: Event → Job → Queue → Runner, Container integration
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from betrayer.core import EventBus, Event
from betrayer.jobs import Job, JobResult, JobStatus, Queue, JobRunner, Scheduler


# ===================================================================
# Events
# ===================================================================


class TestEvents:
    """Canonical Event system tests."""

    def test_dispatch_event(self):
        bus = EventBus()
        results: List[str] = []

        def handler(event: Event) -> None:
            results.append(event.payload["msg"])

        bus.on("test.event", handler)
        bus.emit("test.event", {"msg": "hello"})
        assert results == ["hello"]

    def test_listener_invoked(self):
        bus = EventBus()
        invoked = False

        def handler(event: Event) -> None:
            nonlocal invoked
            invoked = True

        bus.on("user.created", handler)
        bus.emit("user.created", {"id": 1})
        assert invoked

    def test_multiple_listeners(self):
        bus = EventBus()
        order: List[int] = []

        def handler_a(event: Event) -> None:
            order.append(1)

        def handler_b(event: Event) -> None:
            order.append(2)

        bus.on("test", handler_a)
        bus.on("test", handler_b)
        bus.emit("test")
        assert order == [1, 2]  # registration order

    def test_listener_priority_order(self):
        bus = EventBus()
        order: List[int] = []

        def low(event: Event) -> None:
            order.append(2)

        def high(event: Event) -> None:
            order.append(1)

        bus.on("test", low, priority=0)
        bus.on("test", high, priority=10)
        bus.emit("test")
        assert order == [1, 2]  # higher priority first

    def test_listener_error_does_not_stop_others(self):
        bus = EventBus()
        results: List[str] = []

        def failing(event: Event) -> None:
            raise ValueError("oops")

        def succeeding(event: Event) -> None:
            results.append("ok")

        bus.on("test", failing)
        bus.on("test", succeeding)
        emitted_results = bus.emit("test")
        assert results == ["ok"]  # succeeding still runs
        assert len(emitted_results) == 2
        # First handler failed
        assert emitted_results[0][1] is False
        assert emitted_results[0][2] is not None
        # Second handler succeeded
        assert emitted_results[1][1] is True

    def test_strict_mode_raises(self):
        bus = EventBus()

        def failing(event: Event) -> None:
            raise ValueError("boom")

        bus.on("test", failing)
        with pytest.raises(Exception) as exc_info:
            bus.emit("test", strict=True)
        assert "EVENT_HANDLER_FAILED" in str(exc_info.value)

    def test_off_removes_handler(self):
        bus = EventBus()
        results: List[str] = []

        def handler(event: Event) -> None:
            results.append("called")

        bus.on("test", handler)
        bus.off("test", handler)
        bus.emit("test")
        assert results == []

    def test_clear_removes_all(self):
        bus = EventBus()

        def handler(event: Event) -> None:
            pass

        bus.on("a", handler)
        bus.on("b", handler)
        assert bus.total_handlers() == 2
        bus.clear()
        assert bus.total_handlers() == 0

    def test_event_name_validation(self):
        bus = EventBus()
        with pytest.raises(Exception):
            bus.emit("InvalidName")

    def test_event_payload_structure(self):
        bus = EventBus()
        captured: List[Event] = []

        def handler(event: Event) -> None:
            captured.append(event)

        bus.on("order.placed", handler)
        bus.emit("order.placed", {"order_id": 42, "total": 99.99})
        assert len(captured) == 1
        event = captured[0]
        assert event.name == "order.placed"
        assert event.payload["order_id"] == 42
        assert event.payload["total"] == 99.99
        assert event.sequence == 1
        assert event.bus is bus


# ===================================================================
# Jobs
# ===================================================================


class TestJobs:
    """Canonical Job contract tests."""

    def test_job_creates_job_id(self):
        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        job = MyJob()
        assert job.job_id is not None
        assert len(job.job_id) == 12

    def test_job_accepts_kwargs(self):
        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        job = MyJob(name="test", value=42)
        assert job.name == "test"
        assert job.value == 42

    def test_synchronous_execution(self):
        class Counter(Job):
            def __init__(self) -> None:
                super().__init__()
                self.count = 0

            def handle(self) -> JobResult:
                self.count += 1
                return JobResult.ok("Counter")

        job = Counter()
        result = job.handle()
        assert result.success is True
        assert result.status == JobStatus.SUCCESS
        assert result.job == "Counter"
        assert job.count == 1

    def test_success_result(self):
        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob", duration=0.5)

        result = MyJob().handle()
        assert result.success is True
        assert result.status == JobStatus.SUCCESS
        assert result.job == "MyJob"
        assert result.duration == 0.5

    def test_failure_result(self):
        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.fail(
                    "MyJob",
                    code="CUSTOM_ERROR",
                    message="Something went wrong",
                    context={"key": "value"},
                    suggested_actions=["Check configuration"],
                )

        result = MyJob().handle()
        assert result.success is False
        assert result.status == JobStatus.FAILED
        assert result.job == "MyJob"
        assert result.error is not None
        assert result.error["code"] == "CUSTOM_ERROR"
        assert result.error["message"] == "Something went wrong"
        assert result.error["context"] == {"key": "value"}
        assert result.error["suggested_actions"] == ["Check configuration"]

    def test_job_handle_exception(self):
        class BrokenJob(Job):
            def handle(self) -> JobResult:
                raise RuntimeError("critical failure")

        with pytest.raises(RuntimeError):
            BrokenJob().handle()

    def test_job_result_to_dict(self):
        result = JobResult.fail(
            "TestJob",
            duration=1.23,
            code="TIMEOUT",
            message="timeout",
        )
        d = result.to_dict()
        assert d["success"] is False
        assert d["status"] == "failed"
        assert d["job"] == "TestJob"
        assert d["duration"] == 1.23
        assert d["error"]["code"] == "TIMEOUT"
        assert d["error"]["message"] == "timeout"


# ===================================================================
# Queue
# ===================================================================


class TestQueue:
    """Canonical Queue tests."""

    def test_push_and_pop(self):
        queue = Queue()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        job = MyJob()
        msg_id = queue.push(job)
        assert msg_id is not None
        assert len(msg_id) > 0

        popped = queue.pop()
        assert popped is not None
        assert popped.job_id == job.job_id

    def test_fifo_order(self):
        queue = Queue()

        class JobA(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        class JobB(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        a = JobA()
        b = JobB()
        queue.push(a)
        queue.push(b)

        assert queue.pop().job_id == a.job_id
        assert queue.pop().job_id == b.job_id

    def test_pop_empty_returns_none(self):
        queue = Queue()
        assert queue.pop() is None

    def test_size(self):
        queue = Queue()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        assert queue.size() == 0
        queue.push(MyJob())
        assert queue.size() == 1
        queue.push(MyJob())
        assert queue.size() == 2
        queue.pop()
        assert queue.size() == 1

    def test_clear(self):
        queue = Queue()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        queue.push(MyJob())
        queue.push(MyJob())
        assert queue.size() == 2
        queue.clear()
        assert queue.size() == 0
        assert queue.pop() is None

    def test_len(self):
        queue = Queue()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        assert len(queue) == 0
        queue.push(MyJob())
        assert len(queue) == 1

    def test_to_dict(self):
        queue = Queue()
        d = queue.to_dict()
        assert d["name"] == "default"
        assert d["size"] == 0
        assert "InMemoryQueue" in d["backend"]


# ===================================================================
# JobRunner
# ===================================================================


class TestJobRunner:
    """Canonical JobRunner tests."""

    def test_run_once_with_empty_queue_returns_none(self):
        queue = Queue()
        runner = JobRunner(queue)
        assert runner.run_once() is None

    def test_run_once_executes_job(self):
        queue = Queue()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        queue.push(MyJob())
        runner = JobRunner(queue)
        result = runner.run_once()
        assert result is not None
        assert result.success is True
        assert result.job == "MyJob"

    def test_run_available_executes_all(self):
        queue = Queue()

        class MyJob(Job):
            def __init__(self) -> None:
                super().__init__()
                self.executed = False

            def handle(self) -> JobResult:
                self.executed = True
                return JobResult.ok(type(self).__name__)

        a = MyJob()
        b = MyJob()
        queue.push(a)
        queue.push(b)

        runner = JobRunner(queue)
        results = runner.run_available()
        assert len(results) == 2
        assert a.executed is True
        assert b.executed is True
        assert queue.size() == 0

    def test_failed_job_does_not_block_others(self):
        queue = Queue()

        class GoodJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("GoodJob")

        class BadJob(Job):
            def handle(self) -> JobResult:
                return JobResult.fail("BadJob", message="fail")

        queue.push(BadJob())
        queue.push(GoodJob())

        runner = JobRunner(queue)
        results = runner.run_available()
        assert len(results) == 2
        assert results[0].success is False
        assert results[0].job == "BadJob"
        assert results[1].success is True
        assert results[1].job == "GoodJob"

    def test_execute_direct(self):
        queue = Queue()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        runner = JobRunner(queue)
        result = runner.execute(MyJob())
        assert result.success is True

    def test_execute_handles_exception(self):
        queue = Queue()

        class BrokenJob(Job):
            def handle(self) -> JobResult:
                raise ValueError("broken")

        runner = JobRunner(queue)
        result = runner.execute(BrokenJob())
        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "JOB_HANDLE_ERROR"
        assert "ValueError" in result.error["message"]

    def test_non_jobresult_return_is_ok(self):
        queue = Queue()

        class MyJob(Job):
            def handle(self):  # returns None instead of JobResult
                return 42

        runner = JobRunner(queue)
        result = runner.execute(MyJob())
        assert result.success is True


# ===================================================================
# Scheduler
# ===================================================================


class TestScheduler:
    """Canonical Scheduler tests."""

    def test_schedule_job(self):
        scheduler = Scheduler()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        scheduler.schedule(MyJob(), interval_seconds=60)
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["interval_seconds"] == 60
        assert jobs[0]["run_count"] == 0

    def test_fluent_api(self):
        scheduler = Scheduler()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        scheduler.every(30).seconds.do(MyJob())
        jobs = scheduler.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["interval_seconds"] == 30

    def test_fluent_minutes(self):
        scheduler = Scheduler()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        scheduler.every(5).minutes.do(MyJob())
        jobs = scheduler.list_jobs()
        assert jobs[0]["interval_seconds"] == 300  # 5 * 60

    def test_fluent_hours(self):
        scheduler = Scheduler()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        scheduler.every(2).hours.do(MyJob())
        jobs = scheduler.list_jobs()
        assert jobs[0]["interval_seconds"] == 7200  # 2 * 3600

    def test_due_jobs_empty_initially(self):
        scheduler = Scheduler()
        assert scheduler.due_jobs() == []

    def test_due_jobs_after_interval(self):
        fake_now = 1000.0

        def fake_clock() -> float:
            return fake_now

        scheduler = Scheduler(clock=fake_clock)

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        scheduler.schedule(MyJob(), interval_seconds=60)
        # Not due yet
        assert scheduler.due_jobs() == []
        # Advance past interval
        fake_now = 1060.0
        due = scheduler.due_jobs()
        assert len(due) == 1

    def test_run_due_executes_due_jobs(self):
        fake_now = 1000.0

        def fake_clock() -> float:
            return fake_now

        scheduler = Scheduler(clock=fake_clock)

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok("MyJob")

        scheduler.schedule(MyJob(), interval_seconds=60)
        fake_now = 1060.0
        results = scheduler.run_due()
        assert len(results) == 1
        assert results[0].success is True
        # After run, next run is not due immediately
        assert scheduler.due_jobs() == []

    def test_run_due_updates_run_count(self):
        fake_now = 1000.0

        def fake_clock() -> float:
            return fake_now

        scheduler = Scheduler(clock=fake_clock)

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        scheduler.schedule(MyJob(), interval_seconds=60)
        fake_now = 1060.0
        scheduler.run_due()
        jobs = scheduler.list_jobs()
        assert jobs[0]["run_count"] == 1
        assert jobs[0]["last_run_at"] == 1060.0

    def test_multiple_schedules(self):
        scheduler = Scheduler()

        class MyJob(Job):
            def handle(self) -> JobResult:
                return JobResult.ok()

        scheduler.every(10).seconds.do(MyJob())
        scheduler.every(20).seconds.do(MyJob())
        assert len(scheduler.list_jobs()) == 2

    def test_to_dict(self):
        scheduler = Scheduler()
        d = scheduler.to_dict()
        assert d["scheduled"] == 0
        assert d["jobs"] == []


# ===================================================================
# Integration Tests
# ===================================================================


class TestIntegration:
    """Integration tests: Event → Job → Queue → Runner."""

    def test_event_triggers_job_via_queue(self):
        """Simulate: event → listener creates job → queue → runner executes."""
        from betrayer.core import EventBus

        bus = EventBus()
        queue = Queue()
        runner = JobRunner(queue)

        results: List[str] = []

        class ProcessOrder(Job):
            def __init__(self, order_id: int) -> None:
                super().__init__()
                self.order_id = order_id

            def handle(self) -> JobResult:
                results.append(f"processing order {self.order_id}")
                return JobResult.ok("ProcessOrder")

        def on_order_placed(event: Event) -> None:
            order_id = event.payload["order_id"]
            job = ProcessOrder(order_id=order_id)
            queue.push(job)

        bus.on("order.placed", on_order_placed)
        bus.emit("order.placed", {"order_id": 42})

        # Queue should have 1 job
        assert queue.size() == 1

        # Run the job
        runner.run_available()

        assert results == ["processing order 42"]
        assert queue.size() == 0

    def test_event_with_multiple_jobs(self):
        """Multiple events each create their own jobs."""
        bus = EventBus()
        queue = Queue()
        runner = JobRunner(queue)
        results: List[int] = []

        class LogEvent(Job):
            def __init__(self, event_id: int) -> None:
                super().__init__()
                self.event_id = event_id

            def handle(self) -> JobResult:
                results.append(self.event_id)
                return JobResult.ok()

        def on_event(event: Event) -> None:
            queue.push(LogEvent(event.payload["id"]))

        bus.on("item.created", on_event)
        bus.emit("item.created", {"id": 1})
        bus.emit("item.created", {"id": 2})
        bus.emit("item.created", {"id": 3})

        assert queue.size() == 3
        runner.run_available()
        assert results == [1, 2, 3]

    def test_scheduler_with_runner(self):
        """Scheduler run_due uses the JobRunner internally."""
        fake_now = 1000.0

        def fake_clock() -> float:
            return fake_now

        queue = Queue()
        runner = JobRunner(queue)
        scheduler = Scheduler(queue=queue, runner=runner, clock=fake_clock)
        results: List[str] = []

        class ReportJob(Job):
            def handle(self) -> JobResult:
                results.append("report generated")
                return JobResult.ok()

        scheduler.every(30).seconds.do(ReportJob())
        fake_now = 1030.0
        scheduler.run_due()
        assert results == ["report generated"]

    def test_container_integration(self):
        """Jobs/Queue/Runner can be registered with the Container."""
        from betrayer.core import Container

        container = Container()
        queue = Queue()
        runner = JobRunner(queue)
        scheduler = Scheduler(queue=queue, runner=runner)

        container.instance("queue", queue)
        container.instance("job_runner", runner)
        container.instance("scheduler", scheduler)

        resolved_queue = container.resolve("queue")
        resolved_runner = container.resolve("job_runner")
        resolved_scheduler = container.resolve("scheduler")

        assert resolved_queue is queue
        assert resolved_runner is runner
        assert resolved_scheduler is scheduler

    def test_diagnostics_integration(self):
        """Job failures produce structured errors compatible with diagnostics."""
        from betrayer.diagnostics.store import DiagnosticsStore, LEVEL_ERROR

        queue = Queue()
        runner = JobRunner(queue)
        store = DiagnosticsStore()

        class FailingJob(Job):
            def handle(self) -> JobResult:
                return JobResult.fail(
                    "FailingJob",
                    code="JOB_FAILED",
                    message="Intentional failure for testing",
                )

        runner.execute(FailingJob())

        # The JobResult follows the same structured error pattern
        # as Betrayer diagnostics records
        result = runner.execute(FailingJob())
        assert result.success is False
        assert result.error["code"] == "JOB_FAILED"
        assert result.error["message"] == "Intentional failure for testing"
        # Diagnostics integration: can be recorded
        record = store.record(
            level=LEVEL_ERROR,
            component="jobs",
            message=result.error["message"],
            context=result.error["context"],
        )
        assert record is not None