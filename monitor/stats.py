"""Statistics over the committed records: spend, winnings, ranks and number frequency."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from pathlib import Path

GAME_PRICE = 1000
# Ticket prices for the exported history; other e-lotteries have no price in the export.
PRICES = {"로또6/45": 1000, "연금복권720+": 1000, "연금복권520": 1000}
LOTTO_RANKS = {5000: "5등", 50000: "4등"}


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _numbers(text: str) -> list[int]:
    return [int(n) for n in text.split()]


def _won(row: dict) -> bool:
    return bool(row["rank"])


def build_stats(records: Path) -> dict:
    tickets = [r for r in _rows(records / "purchases.csv") if r["status"] == "ok" and r["numbers"]]
    wins = _rows(records / "winnings.csv")
    draws = {r["round"]: r for r in _rows(records / "draws.csv")}
    checked = {r["round"] for r in wins} | set(draws)

    by_round = defaultdict(lambda: {"games": 0, "checked": False, "won": 0, "prize": 0, "draw_date": ""})
    for t in tickets:
        by_round[t["round"]]["games"] += 1
    for w in wins:
        entry = by_round[w["round"]]
        entry["won"] += _won(w)
        entry["prize"] += int(w["prize"] or 0)
    for round_no, entry in by_round.items():
        entry["checked"] = round_no in checked
        entry["draw_date"] = draws.get(round_no, {}).get("draw_date", "")

    months = defaultdict(lambda: {"games": 0, "prize": 0})
    for t in tickets:
        months[t["purchased_at"][:7]]["games"] += 1
    for round_no, entry in by_round.items():
        if entry["draw_date"]:
            months[entry["draw_date"][:7]]["prize"] += entry["prize"]

    spent = len(tickets) * GAME_PRICE
    checked_spent = sum(e["games"] for e in by_round.values() if e["checked"]) * GAME_PRICE
    prize = sum(int(w["prize"] or 0) for w in wins)
    # Past games whose numbers the site still shows (records/history_numbers.csv), before automatic buying.
    past = _rows(records / "history_numbers.csv")
    mine = Counter(n for t in tickets + past for n in _numbers(t["numbers"]))
    drawn = Counter(n for d in draws.values() for n in _numbers(d["numbers"]))
    return {
        "games": len(tickets),
        "spent": spent,
        "checked_games": len(wins),
        "pending_games": sum(e["games"] for e in by_round.values() if not e["checked"]),
        "won_games": sum(_won(w) for w in wins),
        "prize": prize,
        "checked_spent": checked_spent,
        # Games not drawn yet are not losses; profit counts checked games only.
        "net": prize - checked_spent,
        "return_rate": prize / checked_spent * 100 if checked_spent else 0.0,
        "ranks": Counter(int(w["rank"]) for w in wins if _won(w)),
        "matched": Counter(int(w["matched"]) for w in wins),
        "modes": Counter(t["mode"] for t in tickets + past),
        "past_games": len(past),
        "rounds": dict(sorted(by_round.items(), key=lambda item: int(item[0]), reverse=True)),
        "months": dict(sorted(months.items(), reverse=True)),
        "my_numbers": mine,
        "never_picked": [n for n in range(1, 46) if not mine[n]],
        "drawn_numbers": drawn,
        "draws": len(draws),
        "history": build_history(records),
    }


def build_history(records: Path) -> dict | None:
    """Past purchases exported from dhlottery (records/history.csv): no ticket or order numbers."""
    rows = _rows(records / "history.csv")
    if not rows:
        return None
    kinds = defaultdict(lambda: {"purchases": 0, "tickets": 0, "spent": 0, "won": 0, "prize": 0})
    years = defaultdict(lambda: {"games": 0, "prize": 0, "won": 0})
    ranks = Counter()
    for r in rows:
        tickets, prize = int(r["tickets"]), int(r["prize"] or 0)
        k = kinds[r["lottery"]]
        k["purchases"] += 1
        k["tickets"] += tickets
        k["spent"] = None if k["spent"] is None or r["lottery"] not in PRICES else k["spent"] + tickets * PRICES[r["lottery"]]
        k["won"] += r["result"] == "당첨"
        k["prize"] += prize
        if r["lottery"] == "로또6/45":
            y = years[r["purchased_on"][:4]]
            y["games"] += tickets
            y["prize"] += prize
            y["won"] += r["result"] == "당첨"
            if prize:
                ranks[LOTTO_RANKS.get(prize, f"{prize:,}원")] += 1
    dates = sorted(r["purchased_on"] for r in rows)
    lotto_dates = sorted(r["purchased_on"] for r in rows if r["lottery"] == "로또6/45") or dates
    lotto = kinds.get("로또6/45", {"tickets": 0, "spent": 0, "prize": 0, "won": 0})
    numbered = _rows(records / "history_numbers.csv")
    numbered_dates = sorted(r["purchased_on"] for r in numbered)
    return {"numbered": {"games": len(numbered), "first": numbered_dates[0] if numbered else "", "last": numbered_dates[-1] if numbered else "",
                         "ranks": Counter(f"{r['rank']}등" for r in numbered if r["rank"]), "prize": sum(int(r["prize"] or 0) for r in numbered)},
            "first": dates[0], "last": dates[-1], "lotto_first": lotto_dates[0], "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1]["tickets"])),
            "years": dict(sorted(years.items())), "lotto": lotto, "lotto_ranks": ranks}


def _rate(prize: int, spent: int) -> str:
    return f"{prize / spent * 100:.1f}%" if spent else "-"


def format_history_markdown(history: dict, stats: dict) -> list[str]:
    h, lotto = history, history["lotto"]
    games, spent = lotto["tickets"] + stats["checked_games"], lotto["spent"] + stats["checked_spent"]
    prize = lotto["prize"] + stats["prize"]
    lines = [
        "## 전체 기간 로또6/45 (과거 이력 + 자동구매)",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 기간 | {h['lotto_first']} ~ 현재 |",
        f"| 구매 | {games:,}게임 · {spent:,}원 |",
        f"| 당첨금 | {prize:,}원 |",
        f"| 손익 | {prize - spent:+,}원 |",
        f"| 회수율 | {_rate(prize, spent)} |",
        "",
        f"과거 이력은 동행복권 구매내역 내보내기({h['first']} ~ {h['last']}), 이후는 자동구매 기록이다. "
        "두 기록 사이에 다른 방법으로 산 표는 포함되지 않는다. 추첨 전 게임은 제외했다.",
        "",
        "## 과거 이력 (동행복권 구매내역)",
        "",
        "| 복권 | 구매 건수 | 매수 | 구매액 | 당첨 건수 | 당첨금 | 회수율 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, k in h["kinds"].items():
        spent_text = f"{k['spent']:,}원" if k["spent"] is not None else "가격 정보 없음"
        lines.append(f"| {name} | {k['purchases']} | {k['tickets']} | {spent_text} | {k['won']} | {k['prize']:,}원 | {_rate(k['prize'], k['spent'] or 0)} |")
    lines += ["", "### 로또6/45 연도별", "", "| 연도 | 게임 | 구매액 | 당첨 건수 | 당첨금 | 손익 |", "| --- | --- | --- | --- | --- | --- |"]
    for year, y in h["years"].items():
        lines.append(f"| {year} | {y['games']:,} | {y['games'] * GAME_PRICE:,}원 | {y['won']} | {y['prize']:,}원 | {y['prize'] - y['games'] * GAME_PRICE:+,}원 |")
    lines += ["", "로또6/45 당첨: " + (", ".join(f"{k} {v}회" for k, v in sorted(h["lotto_ranks"].items())) or "없음"),
              "", "구매내역의 당첨 건수는 구매 건(최대 5게임) 단위이며, 당첨금은 세금 공제 전이다. 표 번호와 주문번호는 공개하지 않는다.", ""]
    n = h["numbered"]
    if n["games"]:
        lines += ["### 과거 번호 (records/history_numbers.csv)", "",
                  f"동행복권 티켓 조회로 번호를 확인한 {n['games']:,}게임({n['first']} ~ {n['last']})이다. "
                  f"과거 로또 {lotto['tickets']:,}게임 중 나머지는 사이트가 오래된 티켓 조회를 막아('유효하지 않은 티켓') 번호가 없다.", "",
                  f"- 당첨: " + (", ".join(f"{k} {v}게임" for k, v in sorted(n["ranks"].items())) or "없음") + f" · {n['prize']:,}원", ""]
    return lines
    return lines


def _top(counter: Counter, count: int = 10) -> str:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:count]
    return ", ".join(f"{n:02d}({c})" for n, c in items) or "-"


def format_stats_markdown(stats: dict) -> str:
    """Markdown for records/STATS.md. Amounts are purchases and prizes only; no account balance."""
    s = stats
    lines = [
        "# 로또6/45 구매·당첨 통계",
        "",
        "`records/`의 CSV로 자동 생성한다. 직접 수정하지 않는다. 계정 잔액은 포함하지 않는다.",
        "",
        "## 요약",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| 구매 | {s['games']:,}게임 · {s['spent']:,}원 |",
        f"| 당첨 확인 | {s['checked_games']:,}게임 (추첨 전 {s['pending_games']:,}게임) |",
        f"| 당첨 | {s['won_games']:,}게임 · {s['prize']:,}원 |",
        f"| 손익 (확인된 {s['checked_spent']:,}원 기준) | {s['net']:+,}원 |",
        f"| 회수율 | {s['return_rate']:.1f}% |",
        "",
        "당첨금은 회차별 1인당 당첨금 기준이며 세금 공제 전이다.",
        "",
        "## 등수별 당첨",
        "",
        "| 1등 | 2등 | 3등 | 4등 | 5등 |",
        "| --- | --- | --- | --- | --- |",
        "| " + " | ".join(str(s["ranks"].get(r, 0)) for r in range(1, 6)) + " |",
        "",
        "## 일치 개수 분포",
        "",
        "| " + " | ".join(f"{m}개" for m in range(7)) + " |",
        "| " + " | ".join("---" for _ in range(7)) + " |",
        "| " + " | ".join(str(s["matched"].get(m, 0)) for m in range(7)) + " |",
        "",
        "## 회차별",
        "",
        "| 회차 | 추첨일 | 게임 | 구매액 | 당첨 | 당첨금 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for round_no, e in s["rounds"].items():
        result = f"{e['won']}게임" if e["checked"] else "추첨 전"
        prize = f"{e['prize']:,}원" if e["checked"] else "-"
        lines.append(f"| {round_no} | {e['draw_date'] or '-'} | {e['games']} | {e['games'] * GAME_PRICE:,}원 | {result} | {prize} |")
    lines += ["", "## 월별", "", "| 월 | 구매 | 구매액 | 당첨금 |", "| --- | --- | --- | --- |"]
    for month, e in s["months"].items():
        lines.append(f"| {month} | {e['games']}게임 | {e['games'] * GAME_PRICE:,}원 | {e['prize']:,}원 |")
    lines += [
        "",
        "## 번호",
        "",
        f"- 내가 많이 받은 번호 (자동구매 {s['games']:,}게임 + 과거 {s['past_games']:,}게임): {_top(s['my_numbers'])}",
        f"- 한 번도 받지 않은 번호 ({len(s['never_picked'])}개): " + (" ".join(f"{n:02d}" for n in s["never_picked"]) or "-"),
        f"- 확인한 {s['draws']}개 회차의 당첨번호 빈도: {_top(s['drawn_numbers'])}",
        f"- 구매 방식: " + (", ".join(f"{m} {c}" for m, c in s["modes"].most_common()) or "-"),
        "",
        "자동번호는 무작위이므로 번호 빈도는 기록용이며 당첨 확률과 관계없다.",
        "",
    ]
    if stats.get("history"):
        index = lines.index("## 등수별 당첨")
        lines[index:index] = format_history_markdown(stats["history"], stats)
    return "\n".join(lines)


def format_stats_summary(stats: dict) -> str:
    """One-line cumulative summary appended to the Saturday Discord message."""
    s = stats
    return f"📊 누적 {s['checked_games']:,}게임 확인 · 구매 {s['checked_spent']:,}원 · 당첨 {s['prize']:,}원 · 손익 {s['net']:+,}원 (회수율 {s['return_rate']:.1f}%)"


def write_stats(records: Path, output: Path | None = None) -> dict:
    stats = build_stats(records)
    (output or records / "STATS.md").write_text(format_stats_markdown(stats), encoding="utf-8")
    return stats
