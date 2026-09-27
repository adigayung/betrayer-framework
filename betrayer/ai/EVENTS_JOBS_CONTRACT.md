# Events / Jobs / Queue / Scheduler — Canonical Contract

## Event System

The existing `betrayer.core.events` module provides a synchronous,
deterministic, in-process event bus. This is the **only** canonical
Event system in Betrayer.

### API

```
Event(name, payload, sequence, bus)
EventBus(name)
├── .on(event, handler, priority=0, once=False, owner="") -> EventHandler
├── .off(event, handler=None) -> int
├── .off_handler(entry) -> bool
├── .emit(event, payload=None, strict=False) -> [(handler_id, ok, error)]
├── .names() -> [str]
├── .handlers(event) -> [EventHandler]
├── .count(event) -> int
├── .has_handlers(event) -> bool
├── .total_handlers() -> int
├── .clear(event=None) -> int
└── .describe() -> dict
```

### Usage

```python
from betrayer.core import EventBus

bus = EventBus()

# Listen
def on_user_created(event):
    user = event.payload
    print(f"User created: {user['id']}")

bus.on("user.created", on_user_created)

# Dispatch (synchronous)
bus.emit("user.created", {"id": 123, "name": "Alice"})
```

### Rules

- Event names are dotted lowercase: `"user.created"`
- Handlers run in deterministic order (priority descending, then registration order)
- A failing handler does **not** stop other handlers (unless `strict=True`)
- Results are returned as a list of `(handler_id, ok, error)` tuples

---

## Job Contract

A **Job** is a self-contained unit of work. Every job:

1. Subclasses `Job` from `betrayer.jobs`
2. Implements `handle() -> JobResult`
3. Returns a structured `JobResult` (success/failure with metadata)

### API

```
Job(**kwargs)
├── .job_id -> str
├── .created_at -> float
└── .handle() -> JobResult         # override this

JobResult(success, status, job, duration, error)
├── .ok(job_name, duration)        # factory for success
├── .fail(job_name, duration, code, message, context, suggested_actions)
├── .to_dict() -> dict
```

### Usage

```python
from betrayer.jobs import Job, JobResult

class SendEmail(Job):
    def handle(self) -> JobResult:
        try:
            # ... send email ...
            return JobResult.ok("SendEmail")
        except Exception as exc:
            return JobResult.fail(
                "SendEmail",
                message=str(exc),
                suggested_actions=["Check SMTP configuration"],
            )

job = SendEmail(to="user@example.com")
result = job.handle()
```

### JobResult (structured)

**Success:**
```json
{
  "success": true,
  "status": "success",
  "job": "SendEmail",
  "duration": 0.12,
  "error": null
}
```

**Failure:**
```json
{
  "success": false,
  "status": "failed",
  "job": "SendEmail",
  "duration": 0.05,
  "error": {
    "code": "JOB_FAILED",
    "message": "ConnectionError: SMTP server refused",
    "context": {},
    "suggested_actions": ["Check SMTP configuration"]
  }
}
```

---

## Queue

A **Queue** holds Jobs for sequential execution. The default backend is
in-memory (for dev/test).

### API

```
Queue(name="default", backend=None)
├── .push(job, priority=0) -> str    # enqueue a Job, returns job ID
├── .pop() -> Job | None             # dequeue next Job
├── .size() -> int
├── .clear()
└── .to_dict() -> dict
```

### Usage

```python
from betrayer.jobs import Queue, Job

queue = Queue()
job = SendEmail(to="user@example.com")
queue.push(job)

next_job = queue.pop()   # returns the Job
size = queue.size()      # remaining count
queue.clear()            # remove all
```

### Queue Backend

The queue backend can be replaced via the `backend` parameter, but
must implement:

- `enqueue(message, priority, ttl) -> str`
- `dequeue(timeout) -> QueueMessage | None`
- `acknowledge(message_id) -> bool`
- `size() -> int`
- `clear()`

---

## JobRunner

A **JobRunner** pops Jobs from a Queue and calls `handle()` on each.

### API

```
JobRunner(queue)
├── .run_once() -> JobResult | None   # pop + execute one job
├── .run_available() -> [JobResult]   # execute all available jobs
├── .execute(job) -> JobResult        # direct execution (no queue)
└── .to_dict() -> dict
```

### Usage

```python
from betrayer.jobs import Queue, JobRunner

queue = Queue()
runner = JobRunner(queue)

# Process one job
result = runner.run_once()

# Process all available jobs
results = runner.run_available()

# Execute directly (bypass queue)
result = runner.execute(MyJob())
```

---

## Scheduler

A **Scheduler** defines periodic job execution using time intervals.

### API

```
Scheduler(queue=None, runner=None, clock=time.time)
├── .every(interval) -> _IntervalBuilder
│   └── .seconds.do(job)  /  .minutes.do(job)  /  .hours.do(job)
├── .schedule(job, interval_seconds)
├── .due_jobs() -> [Job]
├── .run_due() -> [JobResult]
├── .list_jobs() -> [dict]
└── .to_dict() -> dict
```

### Usage

```python
from betrayer.jobs import Scheduler, Queue, JobRunner

queue = Queue()
runner = JobRunner(queue)
scheduler = Scheduler(queue=queue, runner=runner)

# Fluent API
scheduler.every(60).seconds.do(SendEmail(to="user@example.com"))
scheduler.every(5).minutes.do(SendEmail(to="admin@example.com"))

# Or explicit
scheduler.schedule(MyJob(), interval_seconds=3600)

# Run all due jobs
results = scheduler.run_due()
```

### Deterministic Testing

Inject a custom `clock` function:

```python
import time

fake_now = 1000.0
def fake_clock():
    return fake_now

scheduler = Scheduler(clock=fake_clock)
scheduler.every(60).seconds.do(MyJob())

fake_now = 1060.0
due = scheduler.due_jobs()  # returns the job
```

---

## CLI Commands

```
bet queue           # show queue state
bet queue run       # run all available queued jobs
bet queue --json    # machine-readable output

bet schedule        # list scheduled jobs
bet schedule run    # run all due scheduled jobs
bet schedule --json # machine-readable output
```

---

## Lifecycle Integration

Jobs, Queue, Runner, and Scheduler are standalone components. They
can be registered with the Container for full lifecycle integration:

```python
from betrayer.jobs import Queue, JobRunner, Scheduler
from betrayer.core import Container

container = Container()
queue = Queue()
runner = JobRunner(queue)
scheduler = Scheduler(queue=queue, runner=runner)

container.register("queue", queue)
container.register("job_runner", runner)
container.register("scheduler", scheduler)
```

---

## Limitations (current task)

- No persistent queue backend (in-memory only)
- No cron-expression scheduler (interval-based only)
- No daemon/worker process (all execution is synchronous)
- No distributed queue support
- No WebSocket/realtime delivery
- No automatic retry in the runner (retry metadata exists on QueueMessages)