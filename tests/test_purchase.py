import contextlib
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock as Mock, patch

from monitor.__main__ import main
from monitor.purchase import (BUY_URL, DEFAULT_RETRY_DELAY, RETRY_BUDGET_SECONDS, GAME_PAGE, READY_URL, LottoPurchaser,
                              PurchaseOutcome, append_records, buy_with_retry, format_purchase, record_rows, retryable,
                              input_values, next_draw_dates, parse_game)
from tests.test_live import response, sequence


PAGE = '<input type="hidden" id="curRound" value="1245"><input value="2026-10-10" id="ROUND_DRAW_DATE"><input id="WAMT_PAY_TLMT_END_DT" value="2027-10-11">'
SUCCESS = {"loginYn": "Y", "result": {"resultMsg": "SUCCESS", "buyRound": "1245", "arrGameChoiceNum": ["A|01|02|04|27|39|443", "B|11|23|25|27|28|452"]}}


def purchase_session(*after_login):
    replies = sequence() + [response({"ready_ip": "10.0.0.1"}), response(text=PAGE)] + list(after_login)
    return Mock(request=Mock(side_effect=replies), cookies=[])


def buyer(session):
    return LottoPurchaser(session, Mock(return_value={"inpUserId": "example"}))


class PurchaseTests(unittest.TestCase):
    def test_game_strings_keep_slot_mode_and_numbers(self):
        self.assertEqual(parse_game("A|01|02|04|27|39|443").numbers, (1, 2, 4, 27, 39, 44))
        self.assertEqual(parse_game("B|11|23|25|27|28|452").mode, "반자동")
        for bad in ["A|01|02|03", "F|01|02|03|04|05|063", "A|01|01|02|03|04|053", "A|01|02|03|04|05|463", None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_game(bad)

    def test_page_inputs_any_attribute_order(self):
        self.assertEqual(input_values(PAGE), {"curRound": "1245", "ROUND_DRAW_DATE": "2026-10-10", "WAMT_PAY_TLMT_END_DT": "2027-10-11"})

    def test_fallback_dates_use_coming_saturday_in_seoul(self):
        # Friday 23:30 UTC is already Saturday in Seoul.
        self.assertEqual(next_draw_dates(datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc)), ("2026-10-10", "2027-10-11"))
        self.assertEqual(next_draw_dates(datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc))[0], "2026-10-17")

    def test_successful_purchase_sends_one_buy_request(self):
        session = purchase_session(response(SUCCESS), response({"data": {"userMndp": {"totalAmt": 3000}}}))
        outcome = buyer(session).buy("example", "example", 2)
        self.assertEqual((outcome.status, outcome.code, outcome.round, outcome.balance_krw), ("ok", "purchase_verified", 1245, 3000))
        buys = [c for c in session.request.call_args_list if c.args[1] == BUY_URL]
        self.assertEqual(len(buys), 1)
        data = buys[0].kwargs["data"]
        self.assertEqual((data["round"], data["direct"], data["nBuyAmount"], data["gameCnt"]), ("1245", "10.0.0.1", "2000", "2"))
        self.assertEqual([g["alpabet"] for g in json.loads(data["param"])], ["A", "B"])
        self.assertEqual(data["ROUND_DRAW_DATE"], "2026-10-10")
        message = format_purchase(outcome)
        self.assertIn("로또6/45 1245회 · 2게임 구매 완료** (2,000원)", message)
        self.assertIn("```\nA  자동  01  02  04  27  39  44\nB  반자동  11  23  25  27  28  45\n```", message)
        self.assertIn("남은 잔액 **3,000원**", message)
        self.assertRegex(message, r"🕗 \d{4}-\d{2}-\d{2} \([월화수목금토일]\) \d{2}:\d{2} KST")
        self.assertLessEqual(len(message), 2000)
        self.assertNotIn("44", outcome.diagnostic())

    def test_records_keep_numbers_but_never_balance(self):
        outcome = buyer(purchase_session(response(SUCCESS), response({"data": {"userMndp": {"totalAmt": 3000}}}))).buy("example", "example", 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "records" / "purchases.csv"
            self.assertEqual(append_records(path, outcome), 2)
            append_records(path, outcome)
            rows = list(csv.DictReader(path.open(encoding="utf-8")))
            self.assertEqual(len(rows), 4)
            self.assertEqual((rows[0]["round"], rows[0]["slot"], rows[0]["numbers"], rows[0]["status"]), ("1245", "A", "01 02 04 27 39 44", "ok"))
            self.assertNotIn("3000", path.read_text(encoding="utf-8"))

    def test_records_skip_runs_without_purchase_request(self):
        dry = buyer(purchase_session()).buy("example", "example", 1, dry_run=True)
        rejected = buyer(purchase_session(response({"result": {"resultMsg": "구매한도 초과"}}))).buy("example", "example", 1)
        self.assertEqual(record_rows(dry), [])
        self.assertEqual([(r["status"], r["numbers"]) for r in record_rows(rejected)], [("rejected", "")])
        self.assertNotIn("구매한도", str(record_rows(rejected)))

    def test_dry_run_never_posts_purchase(self):
        session = purchase_session()
        outcome = buyer(session).buy("example", "example", 1, dry_run=True)
        self.assertEqual((outcome.status, outcome.code), ("dry_run", "purchase_ready"))
        self.assertNotIn(BUY_URL, [c.args[1] for c in session.request.call_args_list])
        self.assertEqual(json.loads(outcome.diagnostic())["dates_source"], "page")

    def test_rejected_purchase_reports_site_reason(self):
        session = purchase_session(response({"result": {"resultMsg": "구매한도 초과", "resultCode": "-1"}}))
        outcome = buyer(session).buy("example", "example", 1)
        self.assertEqual((outcome.status, outcome.code), ("rejected", "purchase_rejected"))
        self.assertIn("구매한도 초과", format_purchase(outcome))
        self.assertIn("원인: 사이트가 구매를 거절했습니다", format_purchase(outcome))
        self.assertNotIn("구매한도", outcome.diagnostic())

    def test_lost_purchase_response_is_unconfirmed_and_not_retried(self):
        session = purchase_session(RuntimeError("timeout"))
        outcome = buyer(session).buy("example", "example", 1)
        self.assertEqual(outcome.status, "unconfirmed")
        self.assertIn("구매 내역을 확인", format_purchase(outcome))
        self.assertEqual(sum(c.args[1] == BUY_URL for c in session.request.call_args_list), 1)

    def test_failed_login_stops_before_game_server(self):
        replies = sequence()
        replies[-1] = response(text="<html>login required</html>")
        session = Mock(request=Mock(side_effect=replies), cookies=[])
        outcome = buyer(session).buy("example", "example", 1)
        self.assertEqual((outcome.status, outcome.stage), ("unavailable", "balance"))
        self.assertFalse({READY_URL, GAME_PAGE, BUY_URL} & {c.args[1] for c in session.request.call_args_list})

    def test_missing_ready_ip_stops_before_purchase(self):
        replies = sequence() + [response({})]
        outcome = buyer(Mock(request=Mock(side_effect=replies), cookies=[])).buy("example", "example", 1)
        self.assertEqual((outcome.status, outcome.code), ("error", "ready_ip_missing"))

    def test_missing_page_round_uses_round_api(self):
        replies = sequence() + [response({"ready_ip": "x"}), response(text="<html></html>"), response({"data": {"result": {"ltEpsd": 1246}}})]
        outcome = buyer(Mock(request=Mock(side_effect=replies), cookies=[])).buy("example", "example", 1, dry_run=True)
        self.assertEqual(outcome.round, 1246)
        self.assertEqual(json.loads(outcome.diagnostic()), {"status": "dry_run", "stage": "game_page", "code": "purchase_ready", "requested": 1, "purchased": 0, "login_redirects": [], "login_final": "/login/securityLoginCheck.do", "round_source": "api", "dates_source": "computed"})

    def test_login_cookie_is_shared_with_game_server(self):
        cookies = [SimpleNamespace(name="JSESSIONID", value="v", domain="www.dhlottery.co.kr"),
                   SimpleNamespace(name="WMONID", value="w", domain=".dhlottery.co.kr")]
        jar = Mock(__iter__=lambda self: iter(cookies))
        session = Mock(request=Mock(side_effect=sequence() + [response({"ready_ip": "x"}), response(text=PAGE)]), cookies=jar)
        buyer(session).buy("example", "example", 1, dry_run=True)
        jar.set.assert_called_once_with("JSESSIONID", "v", domain=".dhlottery.co.kr", path="/")

    def test_cli_without_credentials_does_not_connect(self):
        with patch.dict("os.environ", {}, clear=True), patch("socket.socket", side_effect=AssertionError("Network forbidden")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["buy", "--diagnostic"]), 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "credentials_missing")


def outcome(status, code, stage="login_page"):
    return PurchaseOutcome("2026-11-17T08:55:00+09:00", status, stage, code, 1)


def retry_run(results, **kwargs):
    """Run buy_with_retry with a scripted sequence of outcomes and no real waiting."""
    calls, sleeps, notes = [], [], []

    def attempt(games, dry_run=False):
        calls.append((games, dry_run))
        return results[len(calls) - 1]

    outcome_ = buy_with_retry(1, attempt=attempt, sleep=sleeps.append, clock=lambda: 0.0,
                              on_retry=lambda *note: notes.append(note), **kwargs)
    return outcome_, calls, sleeps, notes


class RetryTests(unittest.TestCase):
    def test_pre_purchase_failure_is_retried_then_succeeds(self):
        result, calls, sleeps, notes = retry_run([outcome("error", "connect_timeout"), outcome("ok", "purchase_verified", "purchase")])
        self.assertEqual(result.status, "ok")
        self.assertEqual(calls, [(1, False), (1, False)])
        self.assertEqual(sleeps, [DEFAULT_RETRY_DELAY])
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0][0], notes[0][1].code, notes[0][2]), (1, "connect_timeout", DEFAULT_RETRY_DELAY))

    def test_retries_stop_after_three_tries_and_return_the_last_failure(self):
        result, calls, sleeps, notes = retry_run([outcome("error", "connect_timeout")] * 3)
        self.assertEqual((result.status, result.code), ("error", "connect_timeout"))
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [DEFAULT_RETRY_DELAY] * 2)
        self.assertEqual(len(notes), 2)

    def test_unconfirmed_result_is_never_retried(self):
        result, calls, sleeps, notes = retry_run([outcome("unconfirmed", "read_timeout", "purchase"), outcome("ok", "purchase_verified", "purchase")])
        self.assertEqual((result.status, calls, sleeps, notes), ("unconfirmed", [(1, False)], [], []))

    def test_rejected_purchase_is_never_retried(self):
        result, calls, sleeps, notes = retry_run([outcome("rejected", "purchase_rejected", "purchase")])
        self.assertEqual((result.status, calls, sleeps), ("rejected", [(1, False)], []))

    def test_success_and_dry_run_are_not_retried(self):
        for status, stage in [("ok", "purchase"), ("dry_run", "game_page")]:
            with self.subTest(status=status):
                _, calls, sleeps, _ = retry_run([outcome(status, "purchase_verified", stage)])
                self.assertEqual((calls, sleeps), ([(1, False)], []))

    def test_credentials_and_configuration_failures_are_not_retried(self):
        for code in ["wrong_credentials", "account_locked", "dormant_account", "login_rejected",
                     "password_change_notice", "password_notice_defer_failed", "authentication_unverified",
                     "credentials_missing", "dependencies_missing", "invalid_game_count"]:
            with self.subTest(code=code):
                result, calls, sleeps, _ = retry_run([outcome("unavailable", code), outcome("ok", "purchase_verified", "purchase")])
                self.assertEqual((result.code, calls, sleeps), (code, [(1, False)], []))

    def test_error_after_purchase_stage_is_never_retried(self):
        result, calls, sleeps, _ = retry_run([outcome("error", "transport_or_crypto_error", "purchase")])
        self.assertEqual((result.status, calls, sleeps), ("error", [(1, False)], []))

    def test_retryable_judgement_covers_every_status(self):
        self.assertTrue(retryable(outcome("error", "connect_timeout", "login_page")))
        self.assertTrue(retryable(outcome("unavailable", "access_denied", "balance")))
        for status in ("ok", "dry_run", "rejected", "unconfirmed"):
            with self.subTest(status=status):
                self.assertFalse(retryable(outcome(status, "x", "purchase")))

    def test_slow_failure_stops_before_exceeding_the_workflow_budget(self):
        elapsed = [0.0]

        def attempt(games, dry_run=False):
            elapsed[0] += RETRY_BUDGET_SECONDS  # 시도 하나가 예산을 다 쓴 상황
            return outcome("error", "read_timeout")

        result = buy_with_retry(1, attempt=attempt, sleep=lambda wait: self.fail("재시도 대기를 하면 안 됩니다"), clock=lambda: elapsed[0])
        self.assertEqual((result.status, result.code), ("error", "read_timeout"))

    def test_retry_sends_only_the_successful_attempt_to_the_buy_url(self):
        failing = Mock(request=Mock(side_effect=RuntimeError("timeout")), cookies=[])
        good = Mock(request=Mock(side_effect=sequence() + [response({"ready_ip": "10.0.0.1"}), response(text=PAGE), response(SUCCESS)]), cookies=[])
        sessions = [failing, good]

        def attempt(games, dry_run=False):
            return buyer(sessions.pop(0)).buy("example", "example", games, dry_run)

        result = buy_with_retry(1, attempt=attempt, sleep=lambda wait: None, clock=lambda: 0.0)
        self.assertEqual((result.status, result.code), ("ok", "purchase_verified"))
        self.assertEqual(sum(c.args[1] == BUY_URL for c in failing.request.call_args_list), 0)
        self.assertEqual(sum(c.args[1] == BUY_URL for c in good.request.call_args_list), 1)

    def test_unconfirmed_purchase_ends_the_whole_run_without_another_session(self):
        session = purchase_session(RuntimeError("timeout"))
        sessions = [session]

        def attempt(games, dry_run=False):
            return buyer(sessions.pop(0)).buy("example", "example", games, dry_run)

        result = buy_with_retry(1, attempt=attempt, sleep=lambda wait: None, clock=lambda: 0.0)
        self.assertEqual(result.status, "unconfirmed")
        self.assertEqual(sessions, [])
        self.assertEqual(sum(c.args[1] == BUY_URL for c in session.request.call_args_list), 1)

    def test_retry_timing_stays_within_the_workflow_budget(self):
        elapsed = [0.0]
        waits = []

        def attempt(games, dry_run=False):
            elapsed[0] += 8  # 시도 하나에 8초 걸리는 상황
            return outcome("error", "connect_timeout")

        def pause(wait):
            waits.append(wait)
            elapsed[0] += wait

        result = buy_with_retry(1, attempt=attempt, sleep=pause, clock=lambda: elapsed[0])
        self.assertEqual(result.status, "error")
        self.assertEqual(waits, [DEFAULT_RETRY_DELAY, DEFAULT_RETRY_DELAY])
        self.assertLessEqual(elapsed[0], RETRY_BUDGET_SECONDS)

    def test_cli_logs_retries_as_diagnostics_and_keeps_one_final_line(self):
        ready = outcome("dry_run", "purchase_ready", "game_page")
        calls = []

        def fake_buy(games, dry_run=False, on_retry=None):
            calls.append((games, dry_run))
            on_retry(1, outcome("error", "connect_timeout"), DEFAULT_RETRY_DELAY)
            return ready

        with patch("monitor.purchase.buy_with_retry", fake_buy), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["buy", "--diagnostic"]), 0)
        lines = [json.loads(line) for line in output.getvalue().strip().splitlines()]
        self.assertEqual(lines[0], {"retry": 1, "status": "error", "stage": "login_page", "code": "connect_timeout", "retry_in_seconds": 60})
        self.assertEqual(lines[-1]["code"], "purchase_ready")
        self.assertEqual(calls, [(1, False)])


if __name__ == "__main__":
    unittest.main()
