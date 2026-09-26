# Betrayer Framework — Lifecycle

## Lifecycle States

| State         | Description                              |
|---------------|------------------------------------------|
| CREATED       | Application object created               |
| BOOTSTRAPPING | Bootstrap process running                |
| READY         | Bootstrap complete, initialized          |
| RUNNING       | Application is running                   |
| STOPPING      | Shutdown initiated                       |
| STOPPED       | Application stopped                      |
| FAILED        | An error occurred during any transition  |

## Lifecycle Events (in order)

1. **on_bootstrap** — During bootstrap phase. Environment detection, config loading.
2. **on_initialize** — After bootstrap, before ready. Runtime initialization.
3. **on_ready** — Application is ready to run.
4. **on_start** — Application starts running.
5. **on_stop** — Application stops running.
6. **on_shutdown** — After stop, before destroyed. Cleanup.
7. **on_error** — When any stage fails.

## Lifecycle Manager

The `Lifecycle` class manages state transitions deterministically:

```python
lifecycle = Lifecycle()
lifecycle.transition(LifecycleState.BOOTSTRAPPING)
lifecycle.transition(LifecycleState.READY)
lifecycle.transition(LifecycleState.RUNNING)
```

### Transition Rules

- Only valid transitions are allowed.
- Invalid transitions raise `LifecycleError`.
- Each transition triggers registered handlers for that state.
- If a handler raises an exception, the lifecycle transitions to FAILED.

## Registering Handlers

```python
def my_handler(state: LifecycleState, app: BetrayerApplication) -> None:
    print(f"Lifecycle changed to: {state}")

lifecycle.register_handler(LifecycleState.READY, my_handler)
```

Handlers are called in registration order.

## Failure Handling

If any lifecycle stage fails:
1. The framework transitions to FAILED.
2. The error is recorded with stage, component, code, and cause.
3. `on_error` handlers are called.
4. The framework can be inspected via `Application.lifecycle`.

## Determinism

- Bootstrap always follows the same sequence.
- Lifecycle transitions always follow the same order.
- State is never ambiguous — there is always exactly one current state.
