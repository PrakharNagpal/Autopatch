"""Devin API wrapper with retry, idempotency, and structured logging."""

import logging
import time
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEVIN_API_BASE = "https://api.devin.ai/v1"


class SessionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    STOPPED = "stopped"


class Session(BaseModel):
    session_id: str
    status: SessionStatus
    url: str | None = None
    acu_consumed: float = 0.0
    pr_url: str | None = None
    structured_output: dict[str, Any] | None = None


class DevinClient:
    def __init__(self, api_key: str, max_retries: int = 3) -> None:
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._max_retries = max_retries

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{DEVIN_API_BASE}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            t0 = time.monotonic()
            try:
                resp = httpx.request(method, url, headers=self._headers, timeout=30, **kwargs)
                latency = round((time.monotonic() - t0) * 1000)
                logger.info(
                    "devin_api method=%s path=%s status=%d latency_ms=%d",
                    method, path, resp.status_code, latency,
                )
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    "devin_api error attempt=%d/%d path=%s error=%s retrying_in=%ds",
                    attempt + 1, self._max_retries, path, exc, wait,
                )
                if attempt < self._max_retries - 1:
                    time.sleep(wait)
        raise RuntimeError(f"Devin API failed after {self._max_retries} attempts") from last_exc

    def create_session(self, prompt: str, idempotency_key: str) -> Session:
        data = self._request(
            "POST", "/sessions",
            json={"prompt": prompt, "idempotency_key": idempotency_key},
        )
        return self._parse_session(data)

    def get_session(self, session_id: str) -> Session:
        data = self._request("GET", f"/sessions/{session_id}")
        return self._parse_session(data)

    def send_message(self, session_id: str, message: str) -> None:
        self._request(
            "POST", f"/sessions/{session_id}/message",
            json={"message": message},
        )
        logger.info("devin_message_sent session_id=%s", session_id)

    def cancel_session(self, session_id: str) -> None:
        self._request("DELETE", f"/sessions/{session_id}")
        logger.info("devin_session_cancelled session_id=%s", session_id)

    def list_sessions(self, status: str | None = None) -> list[Session]:
        params = {"status": status} if status else {}
        data = self._request("GET", "/sessions", params=params)
        return [self._parse_session(s) for s in data.get("sessions", [])]

    @staticmethod
    def _parse_session(data: dict[str, Any]) -> Session:
        return Session(
            session_id=data["session_id"],
            status=SessionStatus(data.get("status", "queued")),
            url=data.get("url"),
            acu_consumed=float(data.get("acu_consumed", 0)),
            pr_url=data.get("structured_output", {}).get("pr_url") if data.get("structured_output") else None,
        )
