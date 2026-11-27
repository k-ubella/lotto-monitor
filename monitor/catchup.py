"""Saturday top-up purchase: fill this round's 5-game limit with whatever the deposit allows.

Weekday runs buy one game each. When one of them fails (a rejected purchase, a missing run),
Saturday is the last day the round can still be filled before the 20:00 KST sales cut-off.
The top-up never buys more than the weekly limit minus what the committed purchase log
already shows for the round, never more than the deposit covers, and sends at most one
purchase request per try like `purchase.py`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .balance import GAME_PRICE_KRW, KST, SHORTAGE_HEADLINE, WEEKLY_GAME_LIMIT, footer_time, shortage_lines
from .purchase import (DEFAULT_ATTEMPTS, DEFAULT_RETRY_DELAY, RETRY_BUDGET_SECONDS, UNAVAILABLE_CODES,
                       LottoPurchaser, format_purchased_games, transport_code, with_retry)
from .reasons import explain
from .live import ReadFailure, encrypt_credentials

SALES_CLOSE_HOUR = 20  # 동행복권 인터넷 판매는 토요일 20:00 KST에 마감한다.
RECORD_NAME = "purchases.csv"


@dataclass(frozen=True)
class CatchupOutcome:
    observed_at: str
    status: str  # ok | dry_run | skipped | insufficient | rejected | unconfirmed | unavailable | error
    stage: str
    code: str
    round: int | None = None
    purchased_in_round: int = 0
    missing: int = 0
    requested: int = 0
    games: tuple = field(default=())
    balance_krw: int | None = None
    remote_message: str | None = None
    sources: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        # Nothing to top up, or no deposit to buy with, is a normal ending — not a failure.
        return self.status in ("ok", "dry_run", "skipped", "insufficient")

    def diagnostic(self) -> str:
        # Counts and codes only: no numbers, balance, account or site message.
        return json.dumps({"status": self.status, "stage": self.stage, "code": self.code,
                           "round": self.round, "purchased_in_round": self.purchased_in_round,
                           "missing": self.missing, "requested": self.requested,
                           "purchased": len(self.games), **self.sources})


def saturday_window_open(now: datetime) -> bool:
    """True only on Saturday before the sales cut-off, when a top-up still belongs to this round."""
    local = now.astimezone(KST)
    return local.weekday() == 5 and local.hour < SALES_CLOSE_HOUR


def record_path(records) -> Path:
    path = Path(records)
    return path / RECORD_NAME if path.is_dir() else path


def round_tickets(records, round_no: int) -> tuple[int, int]:
    """(tickets bought, unconfirmed purchase rows) recorded for the round.

    Only rows the workflow committed count; a rejected row bought nothing, and an
    unconfirmed row may or may not have bought something.
    """
    path = record_path(records)
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError:
        return 0, 0
    same = [r for r in rows if (r.get("round") or "").strip() == str(round_no)]
    bought = sum(1 for r in same if (r.get("status") or "").strip() == "ok")
    unconfirmed = sum(1 for r in same if (r.get("status") or "").strip() == "unconfirmed")
    return bought, unconfirmed


def plan_top_up(bought: int, unconfirmed: int, balance_krw: int) -> tuple[int, int, str]:
    """(missing games, games to buy now, code) for one round.

    `code` is `round_complete`, `purchase_unconfirmed_in_round`, `top_up` or `deposit_short`.
    """
    missing = max(0, WEEKLY_GAME_LIMIT - bought)
    if missing == 0:
        return missing, 0, "round_complete"
    if unconfirmed:
        return missing, 0, "purchase_unconfirmed_in_round"
    buy_count = min(missing, balance_krw // GAME_PRICE_KRW)
    return (missing, buy_count, "top_up" if buy_count else "deposit_short")


def format_catchup(outcome: CatchupOutcome) -> str:
    """Discord markdown for the Saturday top-up, in the same voice as the weekday purchase."""
    round_label = f"{outcome.round}회" if outcome.round else "회차 미확인"
    if outcome.status == "ok":
        total = outcome.purchased_in_round + len(outcome.games)
        lines = [f"🛟 **로또6/45 {round_label} · 토요일 보충 {len(outcome.games)}게임 구매 완료** ({len(outcome.games) * GAME_PRICE_KRW:,}원)"]
        lines += format_purchased_games(outcome.games)
        lines.append(f"이번 회차 {total}/{WEEKLY_GAME_LIMIT}게임")
        lines.append(f"💰 남은 잔액 **{outcome.balance_krw:,}원**" if outcome.balance_krw is not None else "💰 남은 잔액 확인 불가")
        lines += shortage_lines(outcome.balance_krw)
    elif outcome.status == "dry_run":
        lines = [f"🧪 **점검 실행 · {round_label} 토요일 보충 계획**",
                 f"이번 회차 구매 {outcome.purchased_in_round}/{WEEKLY_GAME_LIMIT}게임 · 부족 {outcome.missing}게임 · 예치금으로 {outcome.requested}게임 가능",
                 "실제 구매는 하지 않았습니다."]
    elif outcome.status == "skipped" and outcome.code == "round_complete":
        lines = [f"✅ **{round_label} {WEEKLY_GAME_LIMIT}게임 모두 구매 완료** — 토요일 보충 없음"]
        if outcome.balance_krw is not None:
            lines.append(f"💰 남은 잔액 **{outcome.balance_krw:,}원**")
        lines += shortage_lines(outcome.balance_krw)
    elif outcome.status == "skipped" and outcome.code == "purchase_unconfirmed_in_round":
        lines = [f"⚠️ **토요일 보충 생략 · {round_label}**",
                 "이번 회차에 구매 결과 미확인 기록이 있어 같은 회차를 더 사지 않았습니다.",
                 "동행복권 구매 내역을 확인하고, 필요하면 사이트에서 직접 구매하세요."]
    elif outcome.status == "skipped":
        lines = [f"⏸️ **토요일 보충 생략 · {round_label}**",
                 "토요일 판매 시간(20:00 KST 마감)이 아니어서 구매하지 않았습니다.",
                 "늦게 실행되면 이미 다음 회차로 넘어가 회차 한도를 넘길 수 있어, 이번 회차는 그대로 둡니다."]
    elif outcome.status == "insufficient":
        lines = [SHORTAGE_HEADLINE,
                 f"이번 회차 {outcome.missing}게임이 부족하지만 예치금이 **{outcome.balance_krw:,}원**이라 1게임도 구매할 수 없습니다." if outcome.balance_krw is not None
                 else f"이번 회차 {outcome.missing}게임이 부족하지만 잔액을 확인하지 못했습니다.",
                 "충전한 뒤 사이트에서 직접 구매하거나 워크플로를 다시 실행하세요."]
    elif outcome.status == "unconfirmed":
        lines = [f"⚠️ **보충 구매 결과 미확인 · {round_label}**", "구매가 처리됐을 수 있습니다. 재실행 전에 동행복권 구매 내역을 확인하세요.",
                 "원인: " + explain(outcome.code, outcome.stage), f"진단 코드 `{outcome.code}`"]
    elif outcome.status == "rejected":
        lines = [f"❌ **보충 구매 거절 · {round_label}**", "원인: " + explain(outcome.code, outcome.stage)]
        if outcome.remote_message:
            lines.append("사유: " + outcome.remote_message.replace("`", "'"))
        lines.append(f"진단 코드 `{outcome.code}`")
    else:
        lines = ["🚫 **보충 구매 실패** (구매 요청 전 중단)", "원인: " + explain(outcome.code, outcome.stage),
                 f"단계 `{outcome.stage}` · 진단 코드 `{outcome.code}`"]
        if outcome.remote_message:
            lines.append("사이트 안내: " + outcome.remote_message.replace("`", "'"))
    lines.append(footer_time(outcome.observed_at))
    return "\n".join(lines)


def catchup(purchaser: LottoPurchaser, username: str, password: str, records, dry_run: bool = False,
            now: datetime | None = None) -> CatchupOutcome:
    """Top up this round once: read the deposit and the log, then send at most one request."""
    now = now or datetime.now(timezone.utc)
    observed = now.astimezone(KST).isoformat(timespec="seconds")
    done = lambda status, code, **kw: CatchupOutcome(observed, status, purchaser.stage, code, **kw)
    # A run that lands after Saturday's cut-off belongs to the next round: buying there would
    # fill the following week and make Monday's single game exceed the round limit.
    if not dry_run and not saturday_window_open(now):
        return done("skipped", "outside_saturday_window")
    try:
        plan = purchaser.prepare(username, password)
    except ReadFailure as failure:
        status = "unavailable" if failure.code in UNAVAILABLE_CODES else "error"
        return done(status, failure.code, remote_message=purchaser.reason, sources=purchaser.detail)
    except Exception as error:
        return done("error", transport_code(error))
    bought, unconfirmed = round_tickets(records, plan.round)
    missing, buy_count, code = plan_top_up(bought, unconfirmed, plan.balance_krw)
    counts = {"round": plan.round, "purchased_in_round": bought, "missing": missing,
              "requested": buy_count, "balance_krw": plan.balance_krw, "sources": dict(purchaser.detail)}
    if code != "top_up":
        return done("skipped" if code != "deposit_short" else "insufficient", code, **counts)
    if dry_run:
        return done("dry_run", "purchase_ready", **counts)
    result = purchaser.submit(plan, buy_count, observed)
    return CatchupOutcome(result.observed_at, result.status, result.stage, result.code,
                          round=result.round or plan.round, purchased_in_round=bought, missing=missing,
                          requested=buy_count, games=result.games, balance_krw=result.balance_krw,
                          remote_message=result.remote_message, sources=result.sources)


def catchup_from_environment(records, dry_run: bool = False) -> CatchupOutcome:
    username, password = os.environ.get("LOTTO_USERNAME", ""), os.environ.get("LOTTO_PASSWORD", "")
    if not username or not password:
        return catchup(LottoPurchaser(None), username, password, records, dry_run)
    try:
        import requests
        import Crypto.Cipher.PKCS1_v1_5
    except ImportError:
        return CatchupOutcome(datetime.now(KST).isoformat(timespec="seconds"), "error", "dependencies", "dependencies_missing")
    with requests.Session() as session:
        return catchup(LottoPurchaser(session, encrypt_credentials), username, password, records, dry_run)


def catchup_with_retry(records, dry_run: bool = False, *, attempts: int = DEFAULT_ATTEMPTS,
                       delay: float = DEFAULT_RETRY_DELAY, budget: float = RETRY_BUDGET_SECONDS,
                       attempt=None, sleep=None, clock=None, on_retry=None) -> CatchupOutcome:
    """Like `buy_with_retry`: only failures before the purchase request are tried again."""
    run = attempt or (lambda: catchup_from_environment(records, dry_run))
    return with_retry(run, attempts=attempts, delay=delay, budget=budget, sleep=sleep, clock=clock, on_retry=on_retry)


__all__ = ["CatchupOutcome", "catchup", "catchup_from_environment", "catchup_with_retry", "format_catchup",
           "plan_top_up", "round_tickets", "saturday_window_open"]
