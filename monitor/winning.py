"""Saturday draw check: public winning numbers against the committed purchase records. No login."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path

from .live import BalanceReader, ReadFailure, transport_code
from .balance import KST, footer_time as _footer_time


DRAW_API = "/lt645/selectPstLt645Info.do"
# 1245회 추첨일. 이후 매주 토요일 1회씩 증가한다.
BASE_ROUND, BASE_DRAW = 1245, date(2026, 10, 10)
DRAW_DONE = time(20, 45)  # 추첨 방송 이후
FIXED_PRIZES = {4: 50000, 5: 5000}
DRAW_FIELDS = ["round", "draw_date", "numbers", "bonus", "prize_1", "prize_2", "prize_3", "prize_4", "prize_5"]
WIN_FIELDS = ["round", "slot", "mode", "numbers", "matched", "rank", "prize"]


def latest_drawn_round(now: datetime) -> int:
    local = now.astimezone(KST)
    saturday = local.date() - timedelta(days=(local.weekday() - 5) % 7)
    if saturday == local.date() and local.time() < DRAW_DONE:
        saturday -= timedelta(days=7)
    return BASE_ROUND + (saturday - BASE_DRAW).days // 7


@dataclass(frozen=True)
class Draw:
    round: int
    draw_date: str
    numbers: tuple[int, ...]
    bonus: int
    prizes: dict


def parse_draw(payload: object, round_no: int) -> Draw | None:
    """None when the round is not published yet; ValueError when the shape is unexpected."""
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("list") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("unexpected_draw_shape")
    if not rows:
        return None
    row = next((r for r in rows if isinstance(r, dict) and str(r.get("ltEpsd")) == str(round_no)), None)
    if row is None:
        return None
    try:
        numbers = tuple(int(row[f"tm{i}WnNo"]) for i in range(1, 7))
        bonus = int(row["bnsWnNo"])
        ymd = str(row["ltRflYmd"])
        draw_date = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])).isoformat()
    except (KeyError, TypeError, ValueError):
        raise ValueError("unexpected_draw_shape") from None
    if len(set(numbers + (bonus,))) != 7 or not all(1 <= n <= 45 for n in numbers + (bonus,)):
        raise ValueError("unexpected_draw_shape")
    prizes = {}
    for rank in range(1, 6):
        try:
            prizes[rank] = int(str(row.get(f"rnk{rank}WnAmt")).replace(",", ""))
        except ValueError:
            prizes[rank] = FIXED_PRIZES.get(rank)
    return Draw(round_no, draw_date, numbers, bonus, prizes)


def rank_of(numbers: tuple[int, ...], draw: Draw) -> tuple[int, int]:
    matched = len(set(numbers) & set(draw.numbers))
    if matched == 6:
        return matched, 1
    if matched == 5:
        return matched, 2 if draw.bonus in numbers else 3
    return matched, {4: 4, 3: 5}.get(matched, 0)


@dataclass(frozen=True)
class Ticket:
    slot: str
    mode: str
    numbers: tuple[int, ...]
    matched: int = 0
    rank: int = 0
    prize: int | None = 0


@dataclass(frozen=True)
class CheckOutcome:
    observed_at: str
    status: str  # ok | already_recorded | pending | error
    code: str
    round: int
    draw: Draw | None = None
    tickets: tuple[Ticket, ...] = field(default=())

    @property
    def winnings(self) -> int:
        return sum(t.prize or 0 for t in self.tickets if t.rank)

    def diagnostic(self) -> str:
        return json.dumps({"status": self.status, "code": self.code, "round": self.round,
                           "tickets": len(self.tickets), "winning_tickets": sum(1 for t in self.tickets if t.rank)})


def purchased_tickets(records: Path, round_no: int) -> list[Ticket]:
    path = records / "purchases.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [Ticket(r["slot"], r["mode"], tuple(int(n) for n in r["numbers"].split()))
                for r in csv.DictReader(handle) if r["status"] == "ok" and r["round"] == str(round_no) and r["numbers"]]


def recorded_rounds(records: Path) -> set[str]:
    path = records / "draws.csv"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {r["round"] for r in csv.DictReader(handle)}


def _append(path: Path, fields: list[str], rows: list[dict]) -> None:
    new = not path.exists() or path.stat().st_size == 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def save_check(records: Path, outcome: CheckOutcome) -> None:
    if outcome.status != "ok":
        return
    d = outcome.draw
    _append(records / "draws.csv", DRAW_FIELDS, [{
        "round": d.round, "draw_date": d.draw_date, "numbers": " ".join(f"{n:02d}" for n in d.numbers),
        "bonus": f"{d.bonus:02d}", **{f"prize_{k}": "" if v is None else v for k, v in d.prizes.items()},
    }])
    _append(records / "winnings.csv", WIN_FIELDS, [{
        "round": d.round, "slot": t.slot, "mode": t.mode, "numbers": " ".join(f"{n:02d}" for n in t.numbers),
        "matched": t.matched, "rank": t.rank or "", "prize": t.prize if t.rank else 0,
    } for t in outcome.tickets])


def check(session, records: Path, round_no: int | None = None, now: datetime | None = None) -> CheckOutcome:
    now = now or datetime.now(timezone.utc)
    observed = now.astimezone(KST).isoformat(timespec="seconds")
    round_no = round_no or latest_drawn_round(now)
    if str(round_no) in recorded_rounds(records):
        return CheckOutcome(observed, "already_recorded", "already_recorded", round_no)
    reader = BalanceReader(session)
    try:
        response = reader._request("GET", f"{DRAW_API}?srchLtEpsd={round_no}", extra_headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.dhlottery.co.kr/lt645/result"})
        draw = parse_draw(reader._json(response), round_no)
    except ReadFailure as failure:
        return CheckOutcome(observed, "error", failure.code, round_no)
    except ValueError as error:
        return CheckOutcome(observed, "error", str(error), round_no)
    except Exception as error:
        return CheckOutcome(observed, "error", transport_code(error), round_no)
    if draw is None:
        return CheckOutcome(observed, "pending", "draw_not_published", round_no)
    tickets = []
    for t in purchased_tickets(records, round_no):
        matched, rank = rank_of(t.numbers, draw)
        tickets.append(Ticket(t.slot, t.mode, t.numbers, matched, rank, draw.prizes.get(rank) if rank else 0))
    return CheckOutcome(observed, "ok", "draw_checked", round_no, draw, tuple(tickets))


def format_check(outcome: CheckOutcome) -> str:
    footer = _footer_time(outcome.observed_at)
    if outcome.status == "pending":
        return f"⏳ **로또6/45 {outcome.round}회 당첨번호 미발표**\n다음 예약 실행에서 다시 확인합니다.\n{footer}"
    if outcome.status != "ok":
        return f"🚫 **로또6/45 {outcome.round}회 당첨 확인 실패**\n진단 코드 `{outcome.code}`\n{footer}"
    d = outcome.draw
    when = date.fromisoformat(d.draw_date)
    lines = [f"🎯 **로또6/45 {d.round}회 당첨 결과** · {d.draw_date} ({'월화수목금토일'[when.weekday()]})",
             f"🔢 당첨번호 `{' '.join(f'{n:02d}' for n in d.numbers)}` + 보너스 `{d.bonus:02d}`", ""]
    if not outcome.tickets:
        lines.append("이번 회차에 기록된 구매가 없습니다.")
    for t in outcome.tickets:
        nums = " ".join(f"**{n:02d}**" if n in d.numbers else f"{n:02d}" for n in t.numbers)
        result = f"🏆 **{t.rank}등**" + (f" {t.prize:,}원" if t.prize else "") if t.rank else f"낙첨 ({t.matched}개 일치)"
        lines.append(f"`{t.slot}` {nums} → {result}")
    if outcome.tickets:
        won = sum(1 for t in outcome.tickets if t.rank)
        lines += ["", f"💰 {len(outcome.tickets)}게임 중 {won}게임 당첨 · 당첨금 **{outcome.winnings:,}원**" if won else f"😢 {len(outcome.tickets)}게임 모두 낙첨"]
    lines.append(footer)
    return "\n".join(lines)


def check_from_environment(records: Path, round_no: int | None = None) -> CheckOutcome:
    try:
        import requests
    except ImportError:
        return CheckOutcome(datetime.now(KST).isoformat(timespec="seconds"), "error", "dependencies_missing", round_no or 0)
    with requests.Session() as session:
        return check(session, records, round_no)
