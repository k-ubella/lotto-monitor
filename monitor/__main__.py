"""Offline fixture import, local record display and explicit live commands."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from .balance import BalanceResult, format_notification
from .records import append_result, read_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="모의 JSON 결과와 로컬 기록을 확인합니다.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="모의 JSON으로 알림 문구 미리보기")
    demo.add_argument("fixture", type=Path)
    demo.add_argument("--db", type=Path, help="지정하면 정규화한 결과를 로컬 DB에 기록")
    records = commands.add_parser("records", help="로컬 기록 읽기 전용 조회")
    records.add_argument("db", type=Path)
    live = commands.add_parser("live", help="명시적으로 로그인해 잔액만 조회")
    live.add_argument("--diagnostic", action="store_true", help="금액 없이 단계·진단 코드만 출력")
    live.add_argument("--db", type=Path, help="지정하면 조회 결과를 로컬 DB에 기록")
    live.add_argument("--notify", action="store_true", help="조회 결과를 Discord로 전송 (성공 시 실제 잔액 포함)")
    buy = commands.add_parser("buy", help="로또6/45 자동번호 구매 (실행당 구매 요청 1회, 재시도 없음)")
    buy.add_argument("--games", type=int, default=1, choices=range(1, 6), help="구매할 게임 수 1~5 (기본 1)")
    buy.add_argument("--dry-run", action="store_true", help="로그인·회차 확인까지만 하고 구매 요청은 보내지 않음")
    buy.add_argument("--diagnostic", action="store_true", help="번호·잔액 없이 단계·진단 코드만 출력")
    buy.add_argument("--notify", action="store_true", help="결과를 Discord로 전송 (성공 시 번호·잔액 포함)")
    buy.add_argument("--record", type=Path, help="구매 요청을 보낸 경우 회차·번호를 CSV에 추가 (잔액 제외)")
    draw = commands.add_parser("check", help="공개 당첨번호와 records/purchases.csv를 대조 (로그인 없음)")
    draw.add_argument("--round", type=int, help="확인할 회차 (기본: 가장 최근 추첨 회차)")
    draw.add_argument("--records", type=Path, default=Path("records"), help="구매 기록 폴더 (기본 records)")
    draw.add_argument("--save", action="store_true", help="당첨번호와 게임별 결과를 records/에 추가")
    draw.add_argument("--diagnostic", action="store_true", help="번호 없이 상태·진단 코드만 출력")
    draw.add_argument("--notify", action="store_true", help="결과를 Discord로 전송 (이미 기록된 회차는 전송 안 함)")
    commands.add_parser("notify-test", help="실제 계정·금액 없는 고정 Discord 테스트 메시지 전송")
    args = parser.parse_args(argv)
    try:
        if args.command == "notify-test":
            from .discord import send_message, test_message
            delivery = send_message(os.environ.get("DISCORD_WEBHOOK_URL", ""), test_message())
            print(json.dumps({"delivery": delivery.code}))
            return 0 if delivery.ok else 1
        if args.command == "buy":
            from .purchase import append_records, buy_from_environment, format_purchase
            outcome = buy_from_environment(args.games, args.dry_run)
            if args.record is not None:
                append_records(args.record, outcome)
            print(outcome.diagnostic() if args.diagnostic else format_purchase(outcome))
            if args.notify:
                from .discord import send_message
                delivery = send_message(os.environ.get("DISCORD_WEBHOOK_URL", ""), format_purchase(outcome))
                print(json.dumps({"delivery": delivery.code}))
                if not delivery.ok:
                    return 1
            return 0 if outcome.ok else 1
        if args.command == "check":
            from .winning import check_from_environment, format_check, save_check
            outcome = check_from_environment(args.records, args.round)
            if args.save:
                save_check(args.records, outcome)
            print(outcome.diagnostic() if args.diagnostic else format_check(outcome))
            if args.notify and outcome.status != "already_recorded":
                from .discord import send_message
                delivery = send_message(os.environ.get("DISCORD_WEBHOOK_URL", ""), format_check(outcome))
                print(json.dumps({"delivery": delivery.code}))
                if not delivery.ok:
                    return 1
            return 1 if outcome.status == "error" else 0
        if args.command == "live":
            from .live import read_account
            outcome = read_account()
            if args.db is not None:
                append_result(args.db, outcome.result)
            print(outcome.diagnostic() if args.diagnostic else format_notification(outcome.result))
            if args.notify:
                from .discord import send_message
                delivery = send_message(os.environ.get("DISCORD_WEBHOOK_URL", ""), format_notification(outcome.result))
                print(json.dumps({"delivery": delivery.code}))
                if not delivery.ok:
                    return 1
            return 0 if outcome.result.status == "ok" else 1
        if args.command == "records":
            for result in read_results(args.db):
                print(format_notification(result))
            return 0
        result = BalanceResult.from_dict(json.loads(args.fixture.read_text(encoding="utf-8")))
        if args.db is not None:
            append_result(args.db, result)
        print(format_notification(result))
        return 0 if result.status == "ok" else 1
    except (OSError, ValueError, TypeError, sqlite3.Error):
        # Do not echo raw input, database errors, or account response content.
        print("입력 또는 로컬 기록 처리에 실패했습니다. 파일과 형식을 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
