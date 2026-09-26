# Betrayer Framework — Environment Detection

## EnvironmentInfo

`EnvironmentInfo` is a frozen (immutable) dataclass containing runtime environment details.

## Fields

| Field              | Description                          | Example              |
|--------------------|--------------------------------------|----------------------|
| python_version     | Python version string                | "3.11.5"            |
| python_implementation | Python implementation             | "CPython"           |
| os_name            | Operating system name                | "Windows"           |
| os_version         | Operating system version             | "10"                |
| architecture       | System architecture                  | "AMD64"             |
| processor          | Processor identifier                 | "Intel64 Family..." |
| executable         | Python executable path               | "C:\\...\\python.exe" |
| is_virtualenv      | Whether running in a virtual env     | True                |
| virtualenv_path    | Path to virtual environment          | Path("...")         |
| cwd                | Current working directory            | Path("J:\\...")     |
| project_root       | Project root directory               | Path("J:\\...")     |
| development_mode   | Whether in development mode          | True                |
| env_vars           | Relevant environment variables       | {...}               |
| platform           | Full platform string                 | "Windows-10-10.0.19044-AMD64-..." |

## Detection

```python
from betrayer.core.environment import Environment

env = Environment.detect()
print(env.python_version)
print(env.os_name)
print(env.is_virtualenv)
```

## Windows First-Class Support

- Uses `platform.system()` which returns `"Windows"` on Windows.
- Uses `pathlib.Path` for all path operations (no hardcoded slashes).
- Uses `os.name` and `sys.platform` for platform checks.
- Virtual environment detection works on Windows (checks `VIRTUAL_ENV`, `CONDA_PREFIX`, `sys.prefix`).

## Development Mode

Development mode is enabled when:
- `BETRAYER_DEVELOPMENT=1` environment variable is set, OR
- A `.betrayer` directory exists in the project root, OR
- `sys.prefix != sys.base_prefix` (running in a virtualenv)

## No Environment Mutation

Environment detection is read-only. It never:
- Sets environment variables
- Changes the current working directory
- Modifies system configuration
- Installs or removes packages

## Extension Point

Future tasks can add custom environment checks (e.g., dependency versions,
GPU availability) by extending `EnvironmentInfo` or adding new detection methods.
