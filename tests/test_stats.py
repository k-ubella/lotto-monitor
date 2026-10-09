import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monitor.__main__ import main
from monitor.balance import BalanceResult, format_balance_alert
from monitor.stats import build_stats, format_stats_markdown, format_stats_summary, write_stats


PURCHASES = """purchased_at,round,status,slot,mode,numbers
2026-10-05T08:55:00+09:00,1245,ok,A,자동,03 11 15 29 35 07
2026-10-06T08:55:00+09:00,1245,ok,A,자동,01 02 04 29 35 45
2026-10-07T08:55:00+09:00,1245,rejected,,,
2026-10-12T08:55:00+09:00,1246,ok,A,자동,01 02 03 04 05 06
"""
DRAWS = "round,draw_date,numbers,bonus,prize_1,prize_2,prize_3,prize_4,prize_5\n1245,2026-10-10,03 11 15 29 35 44,07,1,2,3,50000,5000\n"
WINNINGS = "round,slot,mode,numbers,matched,rank,prize\n1245,A,자동,03 11 15 29 35 07,5,2,50000000\n1245,A,자동,01 02 04 29 35 45,2,,0\n"


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.records = Path(self.folder.name)
        for name, text in [("purchases.csv", PURCHASES), ("draws.csv", DRAWS), ("winnings.csv", WINNINGS)]:
            (self.records / name).write_text(text, encoding="utf-8")

    def tearDown(self):
        self.folder.cleanup()

    def test_totals_count_only_successful_and_checked_games(self):
        s = build_stats(self.records)
        self.assertEqual((s["games"], s["spent"], s["checked_games"], s["pending_games"]), (3, 3000, 2, 1))
        self.assertEqual((s["checked_spent"], s["prize"], s["net"], s["won_games"]), (2000, 50000000, 49998000, 1))
        self.assertEqual(s["ranks"][2], 1)
        self.assertEqual(s["matched"][2], 1)
        self.assertEqual(s["my_numbers"][35], 2)
        self.assertNotIn(35, s["never_picked"])

    def test_markdown_and_summary(self):
        text = format_stats_markdown(build_stats(self.records))
        self.assertIn("| 1246 | - | 1 | 1,000원 | 추첨 전 | - |", text)
        self.assertIn("| 1245 | 2026-10-10 | 2 | 2,000원 | 1게임 | 50,000,000원 |", text)
        self.assertIn("| 0 | 1 | 0 | 0 | 0 |", text)
        self.assertIn("손익 +49,998,000원", format_stats_summary(build_stats(self.records)))

    def test_empty_records(self):
        with tempfile.TemporaryDirectory() as empty:
            s = write_stats(Path(empty))
            self.assertEqual((s["games"], s["return_rate"]), (0, 0.0))
            self.assertTrue((Path(empty) / "STATS.md").exists())

    def test_cli_writes_stats_file(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["stats", "--records", str(self.records)]), 0)
        self.assertIn("📊", output.getvalue())
        self.assertTrue((self.records / "STATS.md").exists())


class BalanceAlertTests(unittest.TestCase):
    def test_enough_balance_and_top_up_warning(self):
        ok = format_balance_alert(BalanceResult("2026-10-10T00:00:00+00:00", "ok", 12000, "dhlottery"))
        self.assertIn("**동행복권 예치금 12,000원**", ok)
        self.assertIn("✅", ok)
        self.assertIn("2026-10-10 (토) 09:00 KST", ok)
        low = format_balance_alert(BalanceResult("2026-10-10T00:00:00Z", "ok", 0, "dhlottery"))
        self.assertIn("**5,000원 이상 충전**", low)

    def test_failure_never_shows_amount(self):
        text = format_balance_alert(BalanceResult("2026-10-10T00:00:00Z", "error", None, "dhlottery"), "balance", "invalid_json")
        self.assertIn("잔액 조회 실패", text)
        self.assertIn("`invalid_json`", text)
        self.assertNotIn("0원", text)


if __name__ == "__main__":
    unittest.main()
