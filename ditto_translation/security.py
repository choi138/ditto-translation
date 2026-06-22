from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any


class SignatureError(ValueError):
    """Raised when a Ditto webhook signature is missing or invalid."""


def get_header(headers: Mapping[str, str], name: str) -> str | None:
    normalized = name.lower()
    for key, value in headers.items():
        if key.lower() == normalized:
            return value
    return None


def get_request_id(headers: Mapping[str, str]) -> str | None:
    return get_header(headers, "x-ditto-request-id")


def event_key_from_request(raw_body: bytes, headers: Mapping[str, str]) -> str:
    request_id = get_request_id(headers)
    if request_id:
        return f"request:{request_id}"
    return f"body:{hashlib.sha256(raw_body).hexdigest()}"


def verify_ditto_signature(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    signing_key: str,
    tolerance_seconds: int,
    now_seconds: float | None = None,
) -> None:
    request_id = get_header(headers, "x-ditto-request-id")
    timestamp = get_header(headers, "x-ditto-timestamp")
    signature = get_header(headers, "x-ditto-signature")
    if not request_id or not timestamp or not signature:
        raise SignatureError("Missing Ditto signature headers")

    timestamp_seconds = _parse_ditto_timestamp(timestamp)
    now = now_seconds if now_seconds is not None else time.time()
    if abs(now - timestamp_seconds) > tolerance_seconds:
        raise SignatureError("Ditto webhook timestamp is outside the accepted window")

    signature_data = request_id.encode("utf-8") + b"." + timestamp.encode("utf-8") + b"." + raw_body
    expected_signature = hmac.new(
        signing_key.encode("utf-8"),
        signature_data,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise SignatureError("Invalid Ditto webhook signature")


def _parse_ditto_timestamp(timestamp: str) -> float:
    try:
        value = float(timestamp)
    except ValueError as exc:
        raise SignatureError("Invalid Ditto webhook timestamp") from exc

    if value > 10_000_000_000:
        return value / 1000
    return value


def signed_headers(
    *,
    payload: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    signing_key: str,
    request_id: str,
    timestamp: str,
) -> dict[str, str]:
    if raw_body is None:
        if payload is None:
            raise ValueError("payload or raw_body is required")
        raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature_data = request_id.encode("utf-8") + b"." + timestamp.encode("utf-8") + b"." + raw_body
    signature = hmac.new(
        signing_key.encode("utf-8"),
        signature_data,
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-ditto-request-id": request_id,
        "x-ditto-timestamp": timestamp,
        "x-ditto-signature": signature,
    }
