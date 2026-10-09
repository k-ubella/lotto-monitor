import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from monitor.__main__ import main
from monitor.balance import BalanceResult, format_notification, parse_balance
from monitor.records import append_result, read_results


FIXTURES = Path(__file__).parent / "fixtures"


class BalanceTests(unittest.TestCase):
    def test_valid_amounts_including_zero(self):
        for value, expected in [(0, 0), (12000, 12000), ("0원", 0), ("12,000 원", 12000), (" 12000 ", 12000)]:
            with self.subTest(value=value):
                self.assertEqual(parse_balance(value), expected)

    def test_invalid_amounts_are_never_coerced_to_zero(self):
        for value in [None, True, -1, 1.5, "", "확인불가", "오류 500", "-1원", "1.5원", "12,34원", "<html>0</html>"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_balance(value)

    def test_failure_has_no_balance(self):
        for status in ["unavailable", "error"]:
            result = BalanceResult("2026-10-09T17:00:00+09:00", status, None)
            self.assertNotIn("0원", format_notification(result))
            with self.assertRaises(ValueError):
                BalanceResult(result.observed_at, status, 0)

    def test_missing_balance_is_not_a_success(self):
        with self.assertRaises(ValueError):
            BalanceResult.from_dict({"observed_at": "2026-10-09T08:00:00Z", "status": "ok"})

    def test_timezone_required(self):
        for timestamp in ["2026-10-09T08:00:00", "invalid"]:
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                BalanceResult(timestamp, "ok", 0)

    def test_rejects_unknown_fields_and_unsafe_source(self):
        data = json.loads((FIXTURES / "balance-ok.json").read_text())
        for update in [{"password": "example"}, {"source": "@everyone"}, {"status": "unknown"}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                BalanceResult.from_dict(data | update)

    def test_notification_identifies_source_and_observed_time(self):
        result = BalanceResult.from_dict(json.loads((FIXTURES / "balance-ok.json").read_text()))
        text = format_notification(result)
        self.assertIn("lotto-monitor / fixture", text)
        self.assertIn("12,000원", text)
        self.assertIn("2026-10-09T17:00:00+09:00", text)


class RecordAndCliTests(unittest.TestCase):
    def test_success_zero_and_failure_survive_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "records.sqlite3"
            expected = [BalanceResult("2026-10-09T08:00:00Z", status, amount) for status, amount in [("ok", 12000), ("ok", 0), ("error", None)]]
            for result in expected:
                append_result(path, result)
            before = path.read_bytes()
            self.assertEqual(read_results(path), expected)
            self.assertEqual(path.read_bytes(), before)

    def test_read_missing_database_does_not_create_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.sqlite3"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["records", str(path)]), 2)
            self.assertFalse(path.exists())

    def test_demo_exit_status_and_no_network(self):
        with patch("socket.socket", side_effect=AssertionError("Network access forbidden")):
            for name, expected in [("ok", 0), ("unavailable", 1), ("error", 1)]:
                with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["demo", str(FIXTURES / f"balance-{name}.json")]), expected)

    def test_cli_records_failed_result_but_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory) / "results.sqlite3"
            self.assertEqual(main(["demo", str(FIXTURES / "balance-error.json"), "--db", str(path)]), 1)
            self.assertEqual(read_results(path)[0].status, "error")

    def test_invalid_json_does_not_write_database_or_echo_content(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "invalid.json"
            fixture.write_text("sensitive-example-invalid-json")
            db = Path(directory) / "results.sqlite3"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["demo", str(fixture), "--db", str(db)]), 2)
            self.assertFalse(db.exists())
            self.assertNotIn("sensitive-example", stderr.getvalue())

    def test_python_module_propagates_failure_exit_code(self):
        result = subprocess.run([sys.executable, "-m", "monitor", "demo", str(FIXTURES / "balance-error.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("잔액 조회 실패", result.stdout)


if __name__ == "__main__":
    unittest.main()
