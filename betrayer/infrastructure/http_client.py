"""HTTP client abstraction for outbound HTTP requests.

Design decisions:
- ``HttpClient`` is an abstract interface; concrete backends implement it.
- ``HttpClientConfig`` holds timeout, retry policy, and other options.
- ``HttpClientResponse`` normalizes the response from any backend.
- ``RequestsHttpClient`` uses the ``requests`` library as default backend.
- Backend can be replaced via Container registration.
- Error handling is predictable via ``HTTPClientError`` hierarchy.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from betrayer.infrastructure.exceptions import (
    HTTPClientError,
    HTTPConnectionError,
    HTTPTimeoutError,
    HTTPStatusError,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HttpClientResponse
# ---------------------------------------------------------------------------

@dataclass
class HttpClientResponse:
    """Normalized HTTP response."""

    status_code: int
    headers: Dict[str, str]
    body: str
    elapsed: float = 0.0
    _json_cache: Optional[Any] = None

    @property
    def text(self) -> str:
        return self.body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        if self._json_cache is not None:
            return self._json_cache
        self._json_cache = json.loads(self.body)
        return self._json_cache

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_code": self.status_code,
            "headers": self.headers,
            "body_length": len(self.body),
            "elapsed": self.elapsed,
            "ok": self.ok,
        }


# ---------------------------------------------------------------------------
# HttpClientConfig
# ---------------------------------------------------------------------------

@dataclass
class HttpClientConfig:
    """Configuration for HTTP clients."""

    timeout: float = 30.0
    retry_policy: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = None
    default_headers: Dict[str, str] = field(default_factory=dict)
    max_redirects: int = 10
    verify_ssl: bool = True


# ---------------------------------------------------------------------------
# HttpClient
# ---------------------------------------------------------------------------

class HttpClient(ABC):
    """Abstract HTTP client interface.

    Subclasses must implement: get, post, put, patch, delete, head, options.
    """

    def __init__(self, config: Optional[HttpClientConfig] = None) -> None:
        self._config = config or HttpClientConfig()

    @property
    def config(self) -> HttpClientConfig:
        return self._config

    @abstractmethod
    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        ...

    @abstractmethod
    def post(
        self,
        url: str,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        ...

    @abstractmethod
    def put(
        self,
        url: str,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        ...

    @abstractmethod
    def patch(
        self,
        url: str,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        ...

    @abstractmethod
    def delete(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        ...

    @abstractmethod
    def head(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        ...

    @abstractmethod
    def options(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        ...

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "config": {
                "timeout": self._config.timeout,
                "base_url": self._config.base_url,
                "retry_policy": self._config.retry_policy,
            },
        }


# ---------------------------------------------------------------------------
# RequestsHttpClient
# ---------------------------------------------------------------------------

class RequestsHttpClient(HttpClient):
    """HTTP client backed by the ``requests`` library."""

    def __init__(
        self,
        config: Optional[HttpClientConfig] = None,
        session: Any = None,
    ) -> None:
        super().__init__(config)
        self._session = session

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> HttpClientResponse:
        import requests

        session = self._session or requests
        headers = dict(self._config.default_headers)
        extra_headers = kwargs.pop("headers", None)
        if extra_headers:
            headers.update(extra_headers)

        timeout = kwargs.pop("timeout", self._config.timeout)

        try:
            start = datetime.utcnow()
            resp = session.request(
                method=method,
                url=url,
                headers=headers or None,
                timeout=timeout,
                **kwargs,
            )
            elapsed = (datetime.utcnow() - start).total_seconds()
        except requests.ConnectionError as e:
            raise HTTPConnectionError(
                f"Connection failed: {e}",
                component="http_client",
                url=url,
            ) from e
        except requests.Timeout as e:
            raise HTTPTimeoutError(
                f"Request timed out after {timeout}s",
                component="http_client",
                url=url,
            ) from e
        except requests.RequestException as e:
            raise HTTPClientError(
                f"HTTP request failed: {e}",
                component="http_client",
                url=url,
            ) from e

        response = HttpClientResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body=resp.text,
            elapsed=elapsed,
        )

        if not response.ok:
            raise HTTPStatusError(
                f"HTTP {resp.status_code} for {method.upper()} {url}",
                component="http_client",
                url=url,
                status_code=resp.status_code,
                response=response,
            )

        return response

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        return self._request("GET", url, params=params, headers=headers, **kwargs)

    def post(
        self,
        url: str,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        return self._request("POST", url, json=json, data=data, headers=headers, **kwargs)

    def put(
        self,
        url: str,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        return self._request("PUT", url, json=json, data=data, headers=headers, **kwargs)

    def patch(
        self,
        url: str,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        return self._request("PATCH", url, json=json, data=data, headers=headers, **kwargs)

    def delete(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        return self._request("DELETE", url, headers=headers, **kwargs)

    def head(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        return self._request("HEAD", url, headers=headers, **kwargs)

    def options(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> HttpClientResponse:
        return self._request("OPTIONS", url, headers=headers, **kwargs)


__all__ = [
    "HttpClientConfig",
    "HttpClientResponse",
    "HttpClient",
    "RequestsHttpClient",
]