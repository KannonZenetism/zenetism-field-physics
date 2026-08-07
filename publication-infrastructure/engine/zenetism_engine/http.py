"""Small read-only HTTP transport; no mutation methods are implemented."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import RetrievalError


@dataclass(frozen=True)
class HttpResponse:
    body: bytes
    url: str
    headers: Mapping[str, str]


class ReadOnlyHttpClient:
    """GET-only public transport with bounded retries for transient failures."""

    def __init__(self, *, timeout: float = 30.0, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> HttpResponse:
        request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return HttpResponse(
                        body=response.read(),
                        url=response.geturl(),
                        headers=dict(response.headers.items()),
                    )
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(0.25 * (attempt + 1))
        raise RetrievalError(f"GET failed for {url}: {last_error}") from last_error

    def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> tuple[dict[str, Any], HttpResponse]:
        response = self.get(url, headers=headers)
        try:
            value = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RetrievalError(f"GET returned invalid JSON for {url}") from exc
        if not isinstance(value, dict):
            raise RetrievalError(f"GET returned a non-object JSON value for {url}")
        return value, response
