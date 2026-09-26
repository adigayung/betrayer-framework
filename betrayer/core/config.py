"""Configuration system for Betrayer.

Design rules
------------
* No global mutable state - every configuration is an instance.
* Values are addressed with dotted keys (``app.name``); nested dicts are
  flattened automatically so ``{"app": {"name": "x"}}`` == ``app.name``.
* Precedence: defaults < explicit values < environment variables.
* ``finalise()`` freezes the configuration for the rest of the run.
* Secret looking keys are masked by ``safe_data()`` and hidden from
  ``keys(safe=True)`` so diagnostics can never leak credentials.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Optional

from betrayer.core.exceptions import ConfigurationError

DEFAULT_ENV_PREFIX = "BETRAYER_"
MASK = "****"
SECRET_TOKENS = (
    "secret",
    "password",
    "passwd",
    "token",
    "credential",
    "private_key",
    "api_key",
    "apikey",
    "access_key",
    "auth_key",
)
TRUE_VALUES = {"1", "true", "yes", "on", "enable", "enabled"}
FALSE_VALUES = {"0", "false", "no", "off", "disable", "disabled"}

__all__ = [
    "Config",
    "DEFAULT_ENV_PREFIX",
    "MASK",
    "coerce_env_value",
    "env_key_to_config_key",
    "flatten",
    "is_secret_key",
]


def is_secret_key(key: str) -> bool:
    """Return True when ``key`` looks like it holds a secret."""
    lowered = str(key).lower()
    return any(token in lowered for token in SECRET_TOKENS)


def flatten(data: Mapping, prefix: str = "") -> dict:
    """Flatten a nested mapping into dotted keys."""
    flat: dict = {}
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, prefix=f"{full}."))
        else:
            flat[full] = value
    return flat


def coerce_env_value(raw: str) -> Any:
    """Convert an environment string into bool/int/float/str."""
    text = str(raw).strip()
    lowered = text.lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    if text == "":
        return ""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return raw


def env_key_to_config_key(env_key: str, prefix: str) -> Optional[str]:
    """``BETRAYER_APP__DEBUG`` -> ``app.debug`` (None when prefix missing)."""
    if not env_key.startswith(prefix):
        return None
    remainder = env_key[len(prefix):].lower()
    if not remainder:
        return None
    return remainder.replace("__", ".")


class Config:
    """Instance scoped, dotted-key configuration container."""

    def __init__(
        self,
        defaults: Optional[Mapping] = None,
        values: Optional[Mapping] = None,
        env_prefix: str = DEFAULT_ENV_PREFIX,
        environ: Optional[Mapping] = None,
    ) -> None:
        self._values: dict = {}
        self._defaults: dict = {}
        self._finalised = False
        self._env_prefix = env_prefix
        self._environ = dict(environ) if environ is not None else None
        if defaults:
            self._defaults = flatten(defaults)
            self._values.update(self._defaults)
        if values:
            self._values.update(flatten(values))

    # -- state -----------------------------------------------------
    @property
    def finalised(self) -> bool:
        return self._finalised

    @property
    def env_prefix(self) -> str:
        return self._env_prefix

    def finalise(self) -> "Config":
        """Freeze the configuration; later ``set``/``load_env`` fail."""
        self._finalised = True
        return self

    # American spelling kept as an explicit alias.
    finalize = finalise

    def is_finalised(self) -> bool:
        return self._finalised

    # -- read ------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._values

    def require(self, key: str) -> Any:
        if key not in self._values:
            raise ConfigurationError(
                message=f"Required configuration key missing: {key}",
                code="CONFIG_KEY_MISSING",
                context={"key": key},
            )
        return self._values[key]

    def get_str(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = self._values.get(key, default)
        if value is None:
            return default
        return value if isinstance(value, str) else str(value)

    def get_bool(self, key: str, default: Optional[bool] = None) -> Optional[bool]:
        value = self._values.get(key, default)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in TRUE_VALUES:
                return True
            if lowered in FALSE_VALUES:
                return False
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        raise ConfigurationError(
            message=f"Configuration value '{key}' is not a boolean: {value!r}",
            code="CONFIG_TYPE_ERROR",
            context={"key": key, "expected": "bool"},
        )

    def get_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        value = self._values.get(key, default)
        if value is None:
            return default
        if isinstance(value, bool):
            raise ConfigurationError(
                message=f"Configuration value '{key}' is not an int: {value!r}",
                code="CONFIG_TYPE_ERROR",
                context={"key": key, "expected": "int"},
            )
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                message=f"Configuration value '{key}' is not an int: {value!r}",
                code="CONFIG_TYPE_ERROR",
                cause=exc,
                context={"key": key, "expected": "int"},
            ) from exc

    def get_float(self, key: str, default: Optional[float] = None) -> Optional[float]:
        value = self._values.get(key, default)
        if value is None:
            return default
        if isinstance(value, bool):
            raise ConfigurationError(
                message=f"Configuration value '{key}' is not a float: {value!r}",
                code="CONFIG_TYPE_ERROR",
                context={"key": key, "expected": "float"},
            )
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                message=f"Configuration value '{key}' is not a float: {value!r}",
                code="CONFIG_TYPE_ERROR",
                cause=exc,
                context={"key": key, "expected": "float"},
            ) from exc

    # -- write -----------------------------------------------------
    def set(self, key: str, value: Any) -> "Config":
        if self._finalised:
            raise ConfigurationError(
                message=f"Configuration is finalised, cannot set '{key}'",
                code="CONFIG_FINALISED",
                context={"key": key},
            )
        self._values[key] = value
        return self

    def setdefault(self, key: str, value: Any) -> Any:
        if key not in self._values and not self._finalised:
            self._values[key] = value
        return self._values.get(key, value)

    # ``ensure`` is the explicit alias used by Application bootstrap.
    ensure = setdefault

    def update(self, values: Mapping) -> "Config":
        for key, value in flatten(values).items():
            self.set(key, value)
        return self

    def load_env(
        self,
        prefix: Optional[str] = None,
        environ: Optional[Mapping] = None,
    ) -> "Config":
        """Load ``PREFIX_NAME__KEY`` environment variables into the config."""
        if self._finalised:
            raise ConfigurationError(
                message="Configuration is finalised, cannot load environment",
                code="CONFIG_FINALISED",
            )
        active_prefix = prefix or self._env_prefix
        source = environ if environ is not None else (self._environ or os.environ)
        for env_key, env_value in source.items():
            config_key = env_key_to_config_key(env_key, active_prefix)
            if config_key is None:
                continue
            self._values[config_key] = coerce_env_value(env_value)
        return self

    # -- introspection ---------------------------------------------
    def data(self) -> dict:
        """Raw copy of every value (may contain secrets - use with care)."""
        return dict(self._values)

    def keys(self, safe: bool = False) -> list[str]:
        names = list(self._values)
        if safe:
            names = [name for name in names if not is_secret_key(name)]
        return sorted(names)

    def safe_data(self) -> dict:
        """Copy of every value with secrets replaced by ``****``."""
        return {
            key: (MASK if is_secret_key(key) else value)
            for key, value in self._values.items()
        }

    def describe(self) -> dict:
        return {
            "finalised": self._finalised,
            "env_prefix": self._env_prefix,
            "count": len(self._values),
            "keys": self.keys(safe=True),
            "hidden_keys": [k for k in sorted(self._values) if is_secret_key(k)],
        }

    # -- dunder ----------------------------------------------------
    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return (
            f"Config(keys={len(self._values)}, finalised={self._finalised})"
        )
