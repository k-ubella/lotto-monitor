import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from monitor.purchase import KST
from monitor.winning import check, format_check, latest_drawn_round, parse_draw, rank_of, save_check
from tests.test_live import response


ROW = {"ltEpsd": 1246, "ltRflYmd": "20261017", "tm1WnNo": 3, "tm2WnNo": 11, "tm3WnNo": 15, "tm4WnNo": 29,
       "tm5WnNo": 35, "tm6WnNo": 44, "bnsWnNo": 7, "rnk1WnAmt": 2000000000, "rnk2WnAmt": 50000000,
       "rnk3WnAmt": 1500000, "rnk4WnAmt": 50000, "rnk5WnAmt": 5000}
PURCHASES = """purchased_at,round,status,slot,mode,numbers
2026-10-12T08:55:00+09:00,1246,ok,A,자동,03 11 15 29 35 07
2026-10-13T08:55:00+09:00,1246,ok,A,자동,01 02 04 29 35 45
2026-10-14T08:55:00+09:00,1246,rejected,,,
2026-10-05T08:55:00+09:00,1245,ok,A,자동,03 11 15 29 35 44
"""
SAT_NIGHT = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)  # 22:00 KST


def records_with(text=PURCHASES):
    folder = tempfile.TemporaryDirectory()
    (Path(folder.name) / "purchases.csv").write_text(text, encoding="utf-8")
    return folder


class WinningTests(unittest.TestCase):
    def test_latest_round_switches_after_saturday_draw(self):
        kst = lambda day, hour: datetime(2026, 10, day, hour, 0, tzinfo=KST)
        self.assertEqual(latest_drawn_round(kst(10, 20)), 1244)
        self.assertEqual(latest_drawn_round(kst(10, 21)), 1245)
        self.assertEqual(latest_drawn_round(kst(11, 9)), 1245)
        self.assertEqual(latest_drawn_round(kst(17, 22)), 1246)

    def test_ranks_including_bonus_second_prize(self):
        draw = parse_draw({"data": {"list": [ROW]}}, 1246)
        self.assertEqual(rank_of((3, 11, 15, 29, 35, 44), draw), (6, 1))
        self.assertEqual(rank_of((3, 11, 15, 29, 35, 7), draw), (5, 2))
        self.assertEqual(rank_of((3, 11, 15, 29, 35, 1), draw), (5, 3))
        self.assertEqual(rank_of((3, 11, 15, 29, 1, 2), draw), (4, 4))
        self.assertEqual(rank_of((3, 11, 15, 1, 2, 4), draw), (3, 5))
        self.assertEqual(rank_of((3, 11, 1, 2, 4, 5), draw), (2, 0))

    def test_unpublished_and_malformed_draws(self):
        self.assertIsNone(parse_draw({"data": {"list": []}}, 1246))
        self.assertIsNone(parse_draw({"data": {"list": [{**ROW, "ltEpsd": 1245}]}}, 1246))
        for bad in [{}, {"data": None}, {"data": {"list": [{**ROW, "tm6WnNo": 3}]}}, {"data": {"list": [{**ROW, "ltRflYmd": "x"}]}}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_draw(bad, 1246)

    def test_check_scores_only_that_rounds_successful_purchases(self):
        with records_with() as folder:
            session = Mock(request=Mock(return_value=response({"data": {"list": [ROW]}})))
            outcome = check(session, Path(folder), now=SAT_NIGHT)
            self.assertEqual((outcome.status, outcome.round), ("ok", 1246))
            self.assertEqual([(t.rank, t.prize) for t in outcome.tickets], [(2, 50000000), (0, 0)])
            self.assertEqual(outcome.winnings, 50000000)
            call = session.request.call_args
            self.assertEqual(call.args[1], "https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do?srchLtEpsd=1246")
            message = format_check(outcome)
            self.assertIn("당첨번호 `03 11 15 29 35 44` + 보너스 `07`", message)
            self.assertIn("`A` **03** **11** **15** **29** **35** 07 → 🏆 **2등** 50,000,000원", message)
            self.assertIn("2게임 중 1게임 당첨", message)
            self.assertNotIn("03", outcome.diagnostic())

    def test_saved_round_is_not_checked_or_announced_twice(self):
        with records_with() as folder:
            first = check(Mock(request=Mock(return_value=response({"data": {"list": [ROW]}}))), Path(folder), now=SAT_NIGHT)
            save_check(Path(folder), first)
            draws = list(csv.DictReader((Path(folder) / "draws.csv").open(encoding="utf-8")))
            wins = list(csv.DictReader((Path(folder) / "winnings.csv").open(encoding="utf-8")))
            self.assertEqual((draws[0]["numbers"], draws[0]["bonus"], draws[0]["prize_5"]), ("03 11 15 29 35 44", "07", "5000"))
            self.assertEqual([(w["rank"], w["prize"]) for w in wins], [("2", "50000000"), ("", "0")])
            session = Mock()
            again = check(session, Path(folder), now=SAT_NIGHT)
            self.assertEqual(again.status, "already_recorded")
            session.request.assert_not_called()

    def test_no_purchases_still_records_draw(self):
        with records_with("purchased_at,round,status,slot,mode,numbers\n") as folder:
            outcome = check(Mock(request=Mock(return_value=response({"data": {"list": [ROW]}}))), Path(folder), now=SAT_NIGHT)
            self.assertIn("기록된 구매가 없습니다", format_check(outcome))
            save_check(Path(folder), outcome)
            self.assertTrue((Path(folder) / "draws.csv").exists())

    def test_pending_and_errors_save_nothing(self):
        with records_with() as folder:
            pending = check(Mock(request=Mock(return_value=response({"data": {"list": []}}))), Path(folder), now=SAT_NIGHT)
            failed = check(Mock(request=Mock(return_value=response(status=503))), Path(folder), now=SAT_NIGHT)
            self.assertEqual((pending.status, failed.status, failed.code), ("pending", "error", "http_error"))
            self.assertIn("미발표", format_check(pending))
            for outcome in (pending, failed):
                save_check(Path(folder), outcome)
            self.assertFalse((Path(folder) / "draws.csv").exists())
            self.assertEqual(json.loads(failed.diagnostic())["code"], "http_error")


if __name__ == "__main__":
    unittest.main()
