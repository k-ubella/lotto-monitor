"""Explicit Discord delivery with fixed diagnostics and no automatic retries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit


@dataclass(frozen=True)
class Delivery:
    ok: bool
    code: str


def webhook_endpoint(value: str) -> str:
    try:
        url = urlsplit(value)
        query = parse_qs(url.query, keep_blank_values=True)
        valid = (
            url.scheme == "https" and url.netloc in {"discord.com", "discordapp.com"}
            and not url.fragment and set(query) <= {"wait"}
            and re.fullmatch(r"/api(?:/v[0-9]+)?/webhooks/[0-9]+/[A-Za-z0-9._-]+/?", url.path)
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("invalid_webhook")
    return urlunsplit(("https", url.netloc, url.path.rstrip("/"), "", ""))


def test_message() -> str:
    timestamp = datetime.now(timezone.utc).isoformat()
    return (
        "[lotto-monitor / 수동 전송 테스트]\n"
        "Discord 연결 확인용 테스트 메시지입니다.\n"
        "실제 계정·잔액 정보는 포함하지 않았습니다.\n"
        f"실행 시각: {timestamp}"
    )


def _deliver(session, endpoint: str, content: str) -> Delivery:
    phase = "send"
    try:
        response = session.post(
            endpoint + "?wait=true",
            json={"content": content, "allowed_mentions": {"parse": []}},
            timeout=(10, 20), allow_redirects=False,
        )
        if response.status_code == 429:
            return Delivery(False, "rate_limited")
        if response.status_code in (401, 403, 404):
            return Delivery(False, "webhook_unavailable")
        if response.status_code != 200:
            return Delivery(False, "send_unconfirmed")
        payload = response.json()
        message_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(message_id, str) or not re.fullmatch(r"[0-9]+", message_id):
            return Delivery(False, "send_unconfirmed")
        phase = "readback"
        saved = session.get(
            endpoint + "/messages/" + message_id,
            timeout=(10, 20), allow_redirects=False,
        )
        if saved.status_code != 200:
            return Delivery(False, "readback_unconfirmed")
        data = saved.json()
        if not isinstance(data, dict) or data.get("id") != message_id or data.get("content") != content:
            return Delivery(False, "readback_unconfirmed")
        return Delivery(True, "message_verified")
    except Exception:
        # Exception text and response bodies may contain a webhook token or message.
        return Delivery(False, "readback_unconfirmed" if phase == "readback" else "send_unconfirmed")


def send_message(webhook_url: str, content: str, session=None) -> Delivery:
    if not webhook_url:
        return Delivery(False, "webhook_missing")
    try:
        endpoint = webhook_endpoint(webhook_url)
    except ValueError:
        return Delivery(False, "invalid_webhook")
    if not isinstance(content, str) or not 1 <= len(content) <= 2000:
        return Delivery(False, "invalid_message")
    if session is not None:
        return _deliver(session, endpoint, content)
    try:
        import requests
        with requests.Session() as client:
            return _deliver(client, endpoint, content)
    except ImportError:
        return Delivery(False, "dependencies_missing")
