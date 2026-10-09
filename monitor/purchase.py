"""Opt-in Lotto 6/45 automatic purchase. One purchase request per run, never retried."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
import re

from .live import BalanceReader, ReadFailure, encrypt_credentials, transport_code


GAME_ORIGIN = "https://ol.dhlottery.co.kr"
ORIGIN_MAIN = "https://www.dhlottery.co.kr/main"
GAME_PAGE = GAME_ORIGIN + "/olotto/game/game645.do"
READY_URL = GAME_ORIGIN + "/olotto/game/egovUserReadySocket.json"
BUY_URL = GAME_ORIGIN + "/olotto/game/execBuy.do"
ROUND_API = "/lt645/selectThsLt645Info.do"
SLOTS = "ABCDE"
KST = timezone(timedelta(hours=9))
MODES = {"1": "수동", "2": "반자동", "3": "자동"}
GAME_HEADERS = {"Origin": GAME_ORIGIN, "Referer": GAME_PAGE}
XHR_HEADERS = {**GAME_HEADERS, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"}


@dataclass(frozen=True)
class Game:
    slot: str
    mode: str
    numbers: tuple[int, ...]


def parse_game(value: object) -> Game:
    """Parse "A|01|02|04|27|39|443": the last field carries the mode code after the number."""
    if not isinstance(value, str):
        raise ValueError("invalid_game")
    parts = value.split("|")
    if len(parts) != 7 or parts[0] not in SLOTS or len(parts[-1]) < 2:
        raise ValueError("invalid_game")
    try:
        numbers = tuple(int(n) for n in parts[1:-1] + [parts[-1][:-1]])
    except ValueError:
        raise ValueError("invalid_game") from None
    if len(set(numbers)) != 6 or not all(1 <= n <= 45 for n in numbers):
        raise ValueError("invalid_game")
    return Game(parts[0], MODES.get(parts[-1][-1], "자동"), numbers)


def input_values(html: str) -> dict:
    values = {}
    for tag in re.findall(r"<input\b[^>]*>", html, flags=re.IGNORECASE):
        attrs = dict((k.lower(), v) for k, v in re.findall(r"""([\w-]+)\s*=\s*["']([^"']*)["']""", tag))
        if "id" in attrs and "value" in attrs:
            values[attrs["id"]] = attrs["value"].strip()
    return values


def next_draw_dates(now: datetime) -> tuple[str, str]:
    # Same fallback the previous purchase script used when the game page omits the dates.
    today = now.astimezone(KST).date()
    draw = today + timedelta(days=(5 - today.weekday()) % 7)
    return draw.isoformat(), (draw + timedelta(days=366)).isoformat()


@dataclass(frozen=True)
class PurchaseOutcome:
    observed_at: str
    status: str  # ok | dry_run | rejected | unconfirmed | unavailable | error
    stage: str
    code: str
    requested: int
    round: int | None = None
    games: tuple[Game, ...] = field(default=())
    balance_krw: int | None = None
    remote_message: str | None = None
    sources: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "dry_run")

    def diagnostic(self) -> str:
        # Numbers, balance, account and remote text stay out of (public) Actions logs.
        return json.dumps({"status": self.status, "stage": self.stage, "code": self.code,
                           "requested": self.requested, "purchased": len(self.games), **self.sources})


def _footer(outcome: PurchaseOutcome) -> str:
    when = datetime.fromisoformat(outcome.observed_at).astimezone(KST)
    return f"🕗 {when:%Y-%m-%d} ({'월화수목금토일'[when.weekday()]}) {when:%H:%M} KST · lotto-monitor"


def format_purchase(outcome: PurchaseOutcome) -> str:
    """Discord markdown; numbers are aligned in a code block so they read like a ticket."""
    round_label = f"{outcome.round}회" if outcome.round else "회차 미확인"
    if outcome.status == "ok":
        lines = [f"🎟️ **로또6/45 {round_label} · {len(outcome.games)}게임 구매 완료** ({len(outcome.games) * 1000:,}원)", "```"]
        lines += [f"{g.slot}  {g.mode}  " + "  ".join(f"{n:02d}" for n in g.numbers) for g in outcome.games]
        lines.append("```")
        lines.append(f"💰 남은 잔액 **{outcome.balance_krw:,}원**" if outcome.balance_krw is not None else "💰 남은 잔액 확인 불가")
    elif outcome.status == "dry_run":
        lines = [f"🧪 **점검 실행 · {round_label} 구매 준비 확인**", "실제 구매는 하지 않았습니다."]
    elif outcome.status == "unconfirmed":
        lines = [f"⚠️ **구매 결과 미확인 · {round_label}**", "구매가 처리됐을 수 있습니다. 재실행 전에 동행복권 구매 내역을 확인하세요.", f"진단 코드 `{outcome.code}`"]
    elif outcome.status == "rejected":
        lines = [f"❌ **구매 거절 · {round_label}**"]
        if outcome.remote_message:
            lines.append("사유: " + outcome.remote_message.replace("`", "'"))
        lines.append(f"진단 코드 `{outcome.code}`")
    else:
        lines = ["🚫 **구매 실패** (구매 요청 전 중단)", f"단계 `{outcome.stage}` · 진단 코드 `{outcome.code}`"]
    lines.append(_footer(outcome))
    return "\n".join(lines)


RECORD_FIELDS = ["purchased_at", "round", "status", "slot", "mode", "numbers"]


def record_rows(outcome: PurchaseOutcome) -> list[dict]:
    """Rows for the public purchase log: no balance, account or site message."""
    if outcome.status not in ("ok", "rejected", "unconfirmed"):
        return []  # No purchase request was sent.
    base = {"purchased_at": outcome.observed_at, "round": outcome.round or "", "status": outcome.status}
    if not outcome.games:
        return [{**base, "slot": "", "mode": "", "numbers": ""}]
    return [{**base, "slot": g.slot, "mode": g.mode, "numbers": " ".join(f"{n:02d}" for n in g.numbers)} for g in outcome.games]


def append_records(path, outcome: PurchaseOutcome) -> int:
    import csv
    from pathlib import Path
    rows = record_rows(outcome)
    if not rows:
        return 0
    path = Path(path)
    new = not path.exists() or path.stat().st_size == 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECORD_FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


class LottoPurchaser(BalanceReader):
    def _share_session_cookies(self) -> None:
        # The login cookie is issued for www; the game server on ol needs the same session.
        jar = self.session.cookies
        for cookie in list(jar):
            if cookie.name in ("JSESSIONID", "WMONID") and not cookie.domain.startswith("."):
                jar.set(cookie.name, cookie.value, domain=".dhlottery.co.kr", path="/")

    def _current_round(self, page: dict) -> tuple[int, str]:
        if page.get("curRound", "").isdigit():
            return int(page["curRound"]), "page"
        payload = self._json(self._request("GET", ROUND_API, extra_headers={"X-Requested-With": "XMLHttpRequest"}))
        data = payload.get("data") if isinstance(payload, dict) else None
        result = data.get("result") if isinstance(data, dict) else None
        value = result.get("ltEpsd") if isinstance(result, dict) else None
        if not str(value or "").isdigit():
            raise ReadFailure("round_missing")
        return int(value), "api"

    def buy(self, username: str, password: str, games: int, dry_run: bool = False) -> PurchaseOutcome:
        now = datetime.now(timezone.utc)
        observed = now.astimezone(KST).isoformat(timespec="seconds")
        failed = lambda status, code, **kw: PurchaseOutcome(observed, status, self.stage, code, games, **kw)
        if not 1 <= games <= 5:
            return failed("error", "invalid_game_count")
        try:
            self.login(username, password)
            self._share_session_cookies()
            self.stage = "ready_socket"
            ready = self._json(self._request("POST", READY_URL, extra_headers=XHR_HEADERS))
            direct = ready.get("ready_ip") if isinstance(ready, dict) else None
            if not isinstance(direct, str) or not direct:
                raise ReadFailure("ready_ip_missing")
            self.stage = "game_page"
            page = input_values(self._request("GET", GAME_PAGE, extra_headers={"Referer": ORIGIN_MAIN}).text)
            round_no, round_source = self._current_round(page)
            draw_date, limit_date = page.get("ROUND_DRAW_DATE"), page.get("WAMT_PAY_TLMT_END_DT")
            dates_source = "page"
            if not draw_date or not limit_date:
                draw_date, limit_date = next_draw_dates(now)
                dates_source = "computed"
            sources = {"round_source": round_source, "dates_source": dates_source}
        except ReadFailure as failure:
            unavailable = failure.code in {"credentials_missing", "access_denied", "rate_limited", "authentication_unverified", "html_instead_of_json", "balance_missing"}
            return failed("unavailable" if unavailable else "error", failure.code)
        except Exception as error:
            return failed("error", transport_code(error))
        if dry_run:
            return PurchaseOutcome(observed, "dry_run", self.stage, "purchase_ready", games, round_no, sources=sources)

        self.stage = "purchase"
        data = {
            "round": str(round_no),
            "direct": direct,
            "nBuyAmount": str(1000 * games),
            "param": json.dumps([{"genType": "0", "arrGameChoiceNum": None, "alpabet": s} for s in SLOTS[:games]]),
            "ROUND_DRAW_DATE": draw_date,
            "WAMT_PAY_TLMT_END_DT": limit_date,
            "gameCnt": str(games),
            "saleMdaDcd": "10",
        }
        try:
            # Never retried: a lost response may still mean the ticket was bought.
            response = self._request("POST", BUY_URL, data=data, extra_headers={**XHR_HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
            if getattr(response, "encoding", None) == "ISO-8859-1":
                response.encoding = "euc-kr"
            body = self._json(response)
        except ReadFailure as failure:
            return failed("unconfirmed", failure.code, round=round_no, sources=sources)
        except Exception as error:
            return failed("unconfirmed", transport_code(error), round=round_no, sources=sources)
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            return failed("unconfirmed", "unexpected_purchase_response", round=round_no, sources=sources)
        if str(result.get("resultMsg", "")).upper() != "SUCCESS":
            message = str(result.get("resultMsg") or "")[:200] or None
            return failed("rejected", "purchase_rejected", round=round_no, remote_message=message, sources=sources)
        try:
            bought = tuple(parse_game(v) for v in result.get("arrGameChoiceNum") or [])
            bought_round = int(result.get("buyRound") or round_no)
        except (ValueError, TypeError):
            return failed("unconfirmed", "unreadable_tickets", round=round_no, sources=sources)
        if not bought:
            return failed("unconfirmed", "unreadable_tickets", round=round_no, sources=sources)
        try:
            balance = self.read_balance()
        except Exception:
            balance = None  # The purchase itself succeeded; the balance is informational.
        return PurchaseOutcome(observed, "ok", "purchase", "purchase_verified", games, bought_round, bought, balance, sources=sources)



def buy_from_environment(games: int, dry_run: bool = False) -> PurchaseOutcome:
    username, password = os.environ.get("LOTTO_USERNAME", ""), os.environ.get("LOTTO_PASSWORD", "")
    if not username or not password:
        return LottoPurchaser(None).buy(username, password, games, dry_run)
    try:
        import requests
        import Crypto.Cipher.PKCS1_v1_5
    except ImportError:
        observed = datetime.now(KST).isoformat(timespec="seconds")
        return PurchaseOutcome(observed, "error", "dependencies", "dependencies_missing", games)
    with requests.Session() as session:
        return LottoPurchaser(session, encrypt_credentials).buy(username, password, games, dry_run)
