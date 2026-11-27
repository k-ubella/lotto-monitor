import contextlib
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from monitor.__main__ import main
from monitor.balance import KST
from monitor.catchup import (CatchupOutcome, catchup, catchup_with_retry, format_catchup, plan_top_up,
                             round_tickets, saturday_window_open)
from monitor.purchase import BUY_URL, LottoPurchaser, append_records
from tests.test_live import response, sequence


PAGE = ('<input type="hidden" id="curRound" value="1252">'
        '<input value="2026-11-28" id="ROUND_DRAW_DATE"><input id="WAMT_PAY_TLMT_END_DT" value="2027-11-29">')
TICKETS = ["A|01|02|04|27|39|443", "B|11|23|25|27|28|452", "C|03|05|08|19|31|402",
           "D|09|14|24|30|40|413", "E|12|15|25|30|41|433"]
SATURDAY_10 = datetime(2026, 11, 28, 10, 15, tzinfo=KST)
SUNDAY_09 = datetime(2026, 11, 29, 9, 0, tzinfo=KST)
HEADER = ["purchased_at", "round", "status", "slot", "mode", "numbers"]


def success(games=1):
    return {"loginYn": "Y", "result": {"resultMsg": "SUCCESS", "buyRound": "1252",
                                       "arrGameChoiceNum": TICKETS[:games]}}


def session(amount, *after):
    # 로그인 → 잔액(로그인 검증) → 구매 준비 → 회차 페이지 → [구매 요청, 잔액 재조회]
    replies = sequence(amount) + [response({"ready_ip": "10.0.0.1"}), response(text=PAGE)] + list(after)
    return Mock(request=Mock(side_effect=replies), cookies=[])


def buyer(session_):
    return LottoPurchaser(session_, Mock(return_value={"inpUserId": "example"}))


def rows(round_no, cooked=0, rejected=0, unconfirmed=0):
    """Purchase-log rows for one round, in the shape the workflow commits."""
    return ([["2026-11-23T13:35:03+09:00", round_no, "ok", "A", "자동", "07 13 30 37 41 44"]] * cooked
            + [["2026-11-26T14:50:46+09:00", round_no, "rejected", "", "", ""]] * rejected
            + [["2026-11-27T14:43:49+09:00", round_no, "unconfirmed", "", "", ""]] * unconfirmed)


def write_records(folder, record_rows_):
    path = Path(folder) / "purchases.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(record_rows_)
    return path


def record_calls(session_):
    return [c.args[1] for c in session_.request.call_args_list]


class RoundCountTests(unittest.TestCase):
    def test_only_tickets_actually_bought_count_for_the_round(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_records(folder, rows("1252", cooked=4, rejected=1) + rows("1251", cooked=4))
            self.assertEqual(round_tickets(path, 1252), (4, 0))
            self.assertEqual(round_tickets(Path(folder), 1252), (4, 0))  # 폴더를 줘도 같다
            self.assertEqual(round_tickets(path, 1251), (4, 0))
            self.assertEqual(round_tickets(path, 1253), (0, 0))

    def test_unconfirmed_rows_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_records(folder, rows("1252", cooked=3, unconfirmed=1))
            self.assertEqual(round_tickets(path, 1252), (3, 1))

    def test_missing_log_is_an_empty_round(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(round_tickets(Path(folder) / "purchases.csv", 1252), (0, 0))


class PlanTests(unittest.TestCase):
    def test_missing_games_are_filled_by_the_deposit(self):
        self.assertEqual(plan_top_up(4, 0, 12000), (1, 1, "top_up"))
        self.assertEqual(plan_top_up(0, 0, 12000), (5, 5, "top_up"))
        self.assertEqual(plan_top_up(1, 0, 2500), (4, 2, "top_up"))
        self.assertEqual(plan_top_up(4, 0, 1500), (1, 1, "top_up"))

    def test_deposit_below_one_game_buys_nothing(self):
        self.assertEqual(plan_top_up(4, 0, 900), (1, 0, "deposit_short"))
        self.assertEqual(plan_top_up(2, 0, 0), (3, 0, "deposit_short"))

    def test_a_full_round_or_an_unconfirmed_row_buys_nothing(self):
        self.assertEqual(plan_top_up(5, 0, 12000), (0, 0, "round_complete"))
        self.assertEqual(plan_top_up(4, 1, 12000), (1, 0, "purchase_unconfirmed_in_round"))

    def test_only_saturday_before_the_cut_off_is_open(self):
        self.assertTrue(saturday_window_open(SATURDAY_10))
        self.assertTrue(saturday_window_open(datetime(2026, 11, 28, 19, 59, tzinfo=KST)))
        self.assertFalse(saturday_window_open(datetime(2026, 11, 28, 20, 0, tzinfo=KST)))
        self.assertFalse(saturday_window_open(SUNDAY_09))
        self.assertFalse(saturday_window_open(datetime(2026, 11, 27, 23, 59, tzinfo=KST)))
        # UTC로는 금요일이지만 서울은 이미 토요일인 경우도 토요일로 본다.
        self.assertTrue(saturday_window_open(datetime(2026, 11, 27, 23, 30, tzinfo=timezone.utc)))


class CatchupTests(unittest.TestCase):
    def run_top_up(self, amount, record_rows_, games_bought=1, dry_run=False, now=SATURDAY_10):
        with tempfile.TemporaryDirectory() as folder:
            path = write_records(folder, record_rows_)
            after = [response(success(games_bought)), response({"data": {"userMndp": {"totalAmt": amount - 1000 * games_bought}}})]
            session_ = session(amount, *after)
            outcome = catchup(buyer(session_), "example", "example", path, dry_run=dry_run, now=now)
            return outcome, session_, path

    def test_top_up_buys_exactly_the_missing_game(self):
        outcome, session_, _ = self.run_top_up(6000, rows("1252", cooked=4))
        self.assertEqual((outcome.status, outcome.code), ("ok", "purchase_verified"))
        self.assertEqual((outcome.round, outcome.purchased_in_round, outcome.missing, outcome.requested), (1252, 4, 1, 1))
        buys = [c for c in session_.request.call_args_list if c.args[1] == BUY_URL]
        self.assertEqual(len(buys), 1)
        data = buys[0].kwargs["data"]
        self.assertEqual((data["round"], data["nBuyAmount"], data["gameCnt"]), ("1252", "1000", "1"))
        self.assertEqual([g["alpabet"] for g in json.loads(data["param"])], ["A"])
        message = format_catchup(outcome)
        self.assertIn("1252회 · 토요일 보충 1게임 구매 완료** (1,000원)", message)
        self.assertIn("이번 회차 5/5게임", message)
        self.assertIn("남은 잔액 **5,000원**", message)
        self.assertNotIn("예치금 부족", message)

    def test_top_up_warns_after_buying_when_the_deposit_is_left_short(self):
        outcome, _, _ = self.run_top_up(4000, rows("1252", cooked=4))
        message = format_catchup(outcome)
        self.assertIn("남은 잔액 **3,000원**", message)
        self.assertIn("⚠️ **예치금 부족 — 충전 필요**", message)
        self.assertIn("**2,000원 이상 충전**", message)

    def test_top_up_buys_only_what_the_deposit_covers(self):
        outcome, session_, _ = self.run_top_up(2500, [], games_bought=2)
        self.assertEqual((outcome.status, outcome.missing, outcome.requested), ("ok", 5, 2))
        buys = [c for c in session_.request.call_args_list if c.args[1] == BUY_URL]
        self.assertEqual(len(buys), 1)
        self.assertEqual((buys[0].kwargs["data"]["nBuyAmount"], buys[0].kwargs["data"]["gameCnt"]), ("2000", "2"))
        self.assertIn("이번 회차 2/5게임", format_catchup(outcome))

    def test_top_up_warns_when_the_deposit_cannot_buy_a_game(self):
        outcome, session_, _ = self.run_top_up(900, rows("1252", cooked=4))
        self.assertEqual((outcome.status, outcome.code, outcome.ok), ("insufficient", "deposit_short", True))
        self.assertEqual((outcome.missing, outcome.requested), (1, 0))
        self.assertNotIn(BUY_URL, record_calls(session_))  # 구매 요청 없음
        message = format_catchup(outcome)
        self.assertIn("⚠️ **예치금 부족 — 충전 필요**", message)
        self.assertIn("이번 회차 1게임이 부족하지만 예치금이 **900원**", message)

    def test_a_full_round_ends_without_logging_in_or_buying(self):
        outcome, session_, _ = self.run_top_up(12000, rows("1252", cooked=5))
        self.assertEqual((outcome.status, outcome.code, outcome.ok), ("skipped", "round_complete", True))
        self.assertEqual((outcome.purchased_in_round, outcome.missing), (5, 0))
        self.assertNotIn(BUY_URL, record_calls(session_))
        self.assertIn("5게임 모두 구매 완료", format_catchup(outcome))

    def test_an_unconfirmed_purchase_in_the_round_blocks_the_top_up(self):
        outcome, session_, _ = self.run_top_up(12000, rows("1252", cooked=4, unconfirmed=1))
        self.assertEqual((outcome.status, outcome.code), ("skipped", "purchase_unconfirmed_in_round"))
        self.assertNotIn(BUY_URL, record_calls(session_))
        self.assertIn("구매 내역을 확인", format_catchup(outcome))

    def test_a_late_run_does_not_buy_for_the_next_round(self):
        session_ = Mock(request=Mock(side_effect=[]), cookies=[])
        with tempfile.TemporaryDirectory() as folder:
            path = write_records(folder, rows("1252", cooked=4))
            outcome = catchup(buyer(session_), "example", "example", path, now=SUNDAY_09)
        self.assertEqual((outcome.status, outcome.code, outcome.ok), ("skipped", "outside_saturday_window", True))
        self.assertEqual(session_.request.call_args_list, [])  # 로그인조차 하지 않는다
        self.assertIn("20:00 KST 마감", format_catchup(outcome))

    def test_dry_run_reports_the_plan_and_sends_no_purchase(self):
        outcome, session_, _ = self.run_top_up(5000, rows("1252", cooked=4), dry_run=True, now=SUNDAY_09)
        self.assertEqual((outcome.status, outcome.code, outcome.ok), ("dry_run", "purchase_ready", True))
        self.assertEqual((outcome.missing, outcome.requested), (1, 1))
        self.assertNotIn(BUY_URL, record_calls(session_))
        message = format_catchup(outcome)
        self.assertIn("이번 회차 구매 4/5게임 · 부족 1게임 · 예치금으로 1게임 가능", message)
        self.assertIn("실제 구매는 하지 않았습니다", message)
        self.assertNotIn("000", json.loads(outcome.diagnostic()).__str__())  # 진단에는 금액이 없다

    def test_a_rejected_top_up_reports_the_site_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_records(folder, rows("1252", cooked=4))
            session_ = session(5000, response({"result": {"resultMsg": "구매한도 초과"}}))
            outcome = catchup(buyer(session_), "example", "example", path, now=SATURDAY_10)
        self.assertEqual((outcome.status, outcome.code, outcome.ok), ("rejected", "purchase_rejected", False))
        self.assertIn("구매한도 초과", format_catchup(outcome))
        self.assertNotIn("구매한도", outcome.diagnostic())

    def test_bought_top_up_rows_are_recorded_without_balance(self):
        outcome, _, path = self.run_top_up(5000, rows("1252", cooked=4))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "rows.csv"
            self.assertEqual(append_records(target, outcome), 1)
            text = target.read_text(encoding="utf-8")
            committed = list(csv.DictReader(io.StringIO(text)))
            self.assertNotIn("4000", text)
        self.assertEqual((committed[0]["round"], committed[0]["status"], committed[0]["numbers"]),
                         ("1252", "ok", "01 02 04 27 39 44"))

    def test_skipped_and_insufficient_results_write_no_record(self):
        for cooked, amount in [(5, 12000), (4, 900)]:
            with self.subTest(cooked=cooked):
                outcome, _, _ = self.run_top_up(amount, rows("1252", cooked=cooked))
                with tempfile.TemporaryDirectory() as folder:
                    target = Path(folder) / "rows.csv"
                    self.assertEqual(append_records(target, outcome), 0)
                    self.assertFalse(target.exists())


class CatchupRetryTests(unittest.TestCase):
    def test_pre_purchase_failure_is_retried_once_then_succeeds(self):
        failed = CatchupOutcome("2026-11-28T10:15:00+09:00", "error", "login_page", "connect_timeout")
        good = CatchupOutcome("2026-11-28T10:17:00+09:00", "ok", "purchase", "purchase_verified", 1252, 4, 1, 1)
        results, notes = [failed, good], []

        def attempt():
            return results.pop(0)

        result = catchup_with_retry(Mock(), attempt=attempt, sleep=lambda wait: None, clock=lambda: 0.0,
                                    on_retry=lambda *note: notes.append(note))
        self.assertEqual((result.status, len(notes), results), ("ok", 1, []))

    def test_a_result_after_the_purchase_request_is_never_retried(self):
        for status, stage in [("rejected", "purchase"), ("unconfirmed", "purchase"), ("insufficient", "game_page"),
                              ("skipped", "game_page"), ("ok", "purchase")]:
            with self.subTest(status=status):
                calls = []

                def attempt():
                    calls.append(status)
                    return CatchupOutcome("2026-11-28T10:15:00+09:00", status, stage, "code")

                result = catchup_with_retry(Mock(), attempt=attempt, sleep=lambda wait: self.fail("재시도 대기 금지"),
                                            clock=lambda: 0.0)
                self.assertEqual((result.status, len(calls)), (status, 1))


class CatchupCliTests(unittest.TestCase):
    def test_cli_exit_code_and_one_final_line(self):
        skipped = CatchupOutcome("2026-11-28T10:15:00+09:00", "skipped", "game_page", "round_complete", 1252, 5, 0, 0, balance_krw=12000)
        rejected = CatchupOutcome("2026-11-28T10:15:00+09:00", "rejected", "purchase", "purchase_rejected", 1252, 4, 1, 1)
        for outcome, code in [(skipped, 0), (rejected, 1)]:
            with self.subTest(code=code), patch("monitor.catchup.catchup_with_retry", Mock(return_value=outcome)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["catchup", "--diagnostic"]), code)
            lines = [json.loads(line) for line in output.getvalue().strip().splitlines()]
            self.assertEqual(lines[-1]["code"], outcome.code)
            self.assertEqual((lines[-1]["round"], lines[-1]["purchased_in_round"]), (1252, outcome.purchased_in_round))

    def test_cli_passes_records_dry_run_and_record_through(self):
        outcome = CatchupOutcome("2026-11-28T10:15:00+09:00", "dry_run", "game_page", "purchase_ready", 1252, 4, 1, 1, balance_krw=5000)
        fake = Mock(return_value=outcome)
        with tempfile.TemporaryDirectory() as folder, patch("monitor.catchup.catchup_with_retry", fake), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["catchup", "--records", folder, "--dry-run", "--record", str(Path(folder) / "rows.csv")]), 0)
        records, dry_run = fake.call_args.args
        self.assertEqual((records, dry_run), (Path(folder), True))


if __name__ == "__main__":
    unittest.main()
