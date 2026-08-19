"""Small HTTP helper with retries. Stdlib only."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("pipeline.http")

DEFAULT_UA = (
    "DailyMarketDataset/1.0 "
    "(+https://github.com/Tartar371/auto-dataset-generator; public-data aggregator)"
)


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def fetch_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    retries: int = 3,
    backoff: float = 1.5,
    method: str = "GET",
    data: bytes | None = None,
) -> bytes:
    hdrs = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = HttpError(f"HTTP {exc.code} for {url}: {exc.reason}", status=exc.code)
            body = b""
            try:
                body = exc.read()[:300]
            except Exception:
                pass
            log.warning("attempt %s/%s failed: %s %s", attempt, retries, last_exc, body)
            if exc.code in {400, 401, 403, 404, 422}:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = HttpError(f"network error for {url}: {exc}")
            log.warning("attempt %s/%s failed: %s", attempt, retries, last_exc)
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise last_exc or HttpError(f"failed to fetch {url}")


def fetch_json(url: str, **kwargs: Any) -> Any:
    raw = fetch_bytes(url, **kwargs)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HttpError(f"invalid JSON from {url}: {exc}") from exc


def fetch_text(url: str, **kwargs: Any) -> str:
    return fetch_bytes(url, **kwargs).decode("utf-8", errors="replace")


def post_json(url: str, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return fetch_bytes(url, method="POST", data=body, headers=headers, retries=2)


def send_json(url: str, payload: dict[str, Any], method: str = "POST") -> Any:
    raw = fetch_bytes(
        url,
        method=method,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        retries=2,
    )
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HttpError(f"invalid JSON from {url}: {exc}") from exc


def post_form(url: str, fields: dict[str, str], extra_headers: dict[str, str] | None = None) -> bytes:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if extra_headers:
        headers.update(extra_headers)
    return fetch_bytes(url, method="POST", data=body, headers=headers, retries=2)


def post_form_json(url: str, fields: dict[str, str], method: str = "POST") -> Any:
    raw = fetch_bytes(
        url,
        method=method,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        retries=2,
    )
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HttpError(f"invalid JSON from {url}: {exc}") from exc


def put_raw(url: str, data: bytes, timeout: int = 120) -> dict[str, str]:
    """PUT bytes with no extra headers (required for S3 presigned URLs)."""
    req = urllib.request.Request(url, data=data, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {str(k).lower(): str(v) for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()[:300]
        except Exception:
            pass
        raise HttpError(f"HTTP {exc.code} PUT {url}: {exc.reason} {body}", status=exc.code) from exc
