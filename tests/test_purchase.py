import contextlib
from datetime import datetime, timezone
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock as Mock, patch

from monitor.__main__ import main
from monitor.purchase import BUY_URL, GAME_PAGE, READY_URL, LottoPurchaser, format_purchase, input_values, next_draw_dates, parse_game
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
        self.assertIn("1245회 2게임 구매 완료", message)
        self.assertIn("A [자동] 01 02 04 27 39 44", message)
        self.assertIn("3,000원", message)
        self.assertNotIn("44", outcome.diagnostic())

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
        self.assertEqual(json.loads(outcome.diagnostic()), {"status": "dry_run", "stage": "game_page", "code": "purchase_ready", "requested": 1, "purchased": 0, "round_source": "api", "dates_source": "computed"})

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


if __name__ == "__main__":
    unittest.main()
