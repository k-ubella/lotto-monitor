"""Validated balance results and notification text, independent of transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


def parse_balance(value: object) -> int:
    """Accept whole KRW amounts; never turn an unknown response into zero."""
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str):
        value = value.strip()
        if re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\s*원)?", value):
            return int(value.removesuffix("원").strip().replace(",", ""))
    raise ValueError("잔액은 0 이상의 정수 또는 원 단위 금액 문자열이어야 합니다.")


@dataclass(frozen=True)
class BalanceResult:
    observed_at: str
    status: str
    balance_krw: int | None
    source: str = "fixture"

    def __post_init__(self) -> None:
        if not isinstance(self.observed_at, str):
            raise ValueError("관측 시각은 ISO 8601 문자열이어야 합니다.")
        try:
            timestamp = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("관측 시각은 ISO 8601 형식이어야 합니다.") from None
        if timestamp.utcoffset() is None:
            raise ValueError("관측 시각에 시간대가 필요합니다.")
        if self.status not in ("ok", "unavailable", "error"):
            raise ValueError("지원하지 않는 조회 상태입니다.")
        if self.status == "ok":
            if type(self.balance_krw) is not int or self.balance_krw < 0:
                raise ValueError("성공 결과에는 0 이상의 정수 잔액이 필요합니다.")
        elif self.balance_krw is not None:
            raise ValueError("실패 또는 미확인 결과에는 잔액을 기록할 수 없습니다.")
        if not isinstance(self.source, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", self.source):
            raise ValueError("출처는 영문, 숫자, 밑줄, 하이픈 1~40자여야 합니다.")

    @classmethod
    def from_dict(cls, data: object) -> "BalanceResult":
        if not isinstance(data, dict):
            raise ValueError("입력은 JSON 객체여야 합니다.")
        allowed = {"observed_at", "status", "balance", "source"}
        if set(data) - allowed or not {"observed_at", "status"} <= set(data):
            raise ValueError("입력 필드가 올바르지 않습니다.")
        status = data["status"]
        balance = data.get("balance")
        if status == "ok":
            balance = parse_balance(balance)
        return cls(data["observed_at"], status, balance, data.get("source", "fixture"))


def format_notification(result: BalanceResult) -> str:
    label = {
        "ok": f"현재 잔액: {result.balance_krw:,}원" if result.status == "ok" else "",
        "unavailable": "잔액 확인 불가",
        "error": "잔액 조회 실패",
    }[result.status]
    return f"[lotto-monitor / {result.source}] {label}\n관측 시각: {result.observed_at}"
