"""Execution adapter for the local automation platform HTTP API."""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AutomationExecutor(Protocol):
    """Interface used by the diagnosis workflow service."""

    def execute(
        self,
        request_payload: Mapping[str, Any],
        timeout: Optional[int] = None,
    ) -> Any:
        ...


class HttpAutomationExecutor:
    """POST flat Step requests to a configurable local automation endpoint."""

    def __init__(
        self,
        endpoint: str,
        token: Optional[str] = None,
        timeout: int = 60,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})

    def execute(
        self,
        request_payload: Mapping[str, Any],
        timeout: Optional[int] = None,
    ) -> Any:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = Request(
            self.endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout or self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Automation platform returned HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Automation platform request failed: {exc}"
            ) from exc

        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Automation platform returned invalid JSON"
            ) from exc
