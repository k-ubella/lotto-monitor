import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from monitor.__main__ import main
from monitor.balance import BalanceResult
from monitor.discord import send_message, test_message, webhook_endpoint
from monitor.live import LiveOutcome


# Construct a synthetic endpoint; this is not an actual credential.
ENDPOINT = "https://discord.com/api/" + "webhooks/123/example-test-token"


def client_for(content="test"):
    return Mock(
        post=Mock(return_value=Mock(status_code=200, json=Mock(return_value={"id": "456"}))),
        get=Mock(return_value=Mock(status_code=200, json=Mock(return_value={"id": "456", "content": content}))),
    )


class DiscordTests(unittest.TestCase):
    def test_delivery_waits_and_reads_saved_message(self):
        client = client_for()
        self.assertEqual(send_message(ENDPOINT, "test", client).code, "message_verified")
        self.assertEqual(client.post.call_args.args[0], ENDPOINT + "?wait=true")
        self.assertEqual(client.post.call_args.kwargs["json"]["allowed_mentions"], {"parse": []})
        self.assertEqual(client.get.call_args.args[0], ENDPOINT + "/messages/456")
        for call in [client.post.call_args, client.get.call_args]:
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertEqual(call.kwargs["timeout"], (10, 20))

    def test_invalid_urls_do_not_connect(self):
        for url in ["http://discord.com/api/webhooks/1/test", "https://example.org/", "https://discord.com.evil.example/api/webhooks/1/test", ENDPOINT + "#fragment", ENDPOINT + "?thread_id=1", "https://user:pass@discord.com/api/webhooks/1/test"]:
            client = client_for()
            with self.subTest(url=url):
                self.assertEqual(send_message(url, "test", client).code, "invalid_webhook")
                client.post.assert_not_called()

    def test_existing_wait_option_is_replaced(self):
        self.assertEqual(webhook_endpoint(ENDPOINT + "?wait=false"), ENDPOINT)

    def test_missing_webhook_and_invalid_content_do_not_connect(self):
        client = client_for()
        self.assertEqual(send_message("", "test", client).code, "webhook_missing")
        for text in ["", "x" * 2001, None]:
            self.assertEqual(send_message(ENDPOINT, text, client).code, "invalid_message")
        client.post.assert_not_called()

    def test_http_failures_are_not_retried_or_followed(self):
        for status, code in [(429, "rate_limited"), (404, "webhook_unavailable"), (403, "webhook_unavailable"), (302, "send_unconfirmed"), (500, "send_unconfirmed"), (204, "send_unconfirmed")]:
            client = client_for()
            client.post.return_value.status_code = status
            with self.subTest(status=status):
                self.assertEqual(send_message(ENDPOINT, "test", client).code, code)
                self.assertEqual(client.post.call_count, 1)
                client.get.assert_not_called()

    def test_missing_message_id_is_not_confirmed(self):
        client = client_for()
        client.post.return_value.json.return_value = {"id": "not/an/id"}
        self.assertEqual(send_message(ENDPOINT, "test", client).code, "send_unconfirmed")
        client.get.assert_not_called()

    def test_readback_failure_is_distinct_and_does_not_resend(self):
        for change in [{"status_code": 404}, {"json.return_value": {"id": "456", "content": "different"}}, {"json.side_effect": ValueError("private response")}]:
            client = client_for()
            client.get.return_value.configure_mock(**change)
            self.assertEqual(send_message(ENDPOINT, "test", client).code, "readback_unconfirmed")
            self.assertEqual(client.post.call_count, 1)

    def test_transport_errors_do_not_leak_webhook(self):
        client = client_for()
        client.post.side_effect = RuntimeError(ENDPOINT)
        delivery = send_message(ENDPOINT, "test", client)
        self.assertEqual(delivery.code, "send_unconfirmed")
        self.assertNotIn("token", repr(delivery))

    def test_fixed_test_message_identifies_purpose(self):
        self.assertIn("수동 전송 테스트", test_message())
        self.assertIn("실제 계정·잔액 정보는 포함하지 않았습니다", test_message())

    def test_notify_test_cli_missing_secret_does_not_connect(self):
        with patch.dict("os.environ", {}, clear=True), patch("socket.socket", side_effect=AssertionError("Network forbidden")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["notify-test"]), 1)
        self.assertEqual(json.loads(output.getvalue()), {"delivery": "webhook_missing"})

    def test_live_notify_is_opt_in_and_failure_affects_exit_status(self):
        outcome = LiveOutcome(BalanceResult("2026-10-09T08:00:00Z", "ok", 12000, "dhlottery"), "balance", "balance_verified")
        with patch("monitor.live.read_account", return_value=outcome), patch("monitor.discord.send_message") as send, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["live", "--diagnostic"]), 0)
            send.assert_not_called()
            send.return_value = Mock(ok=False, code="send_unconfirmed")
            self.assertEqual(main(["live", "--diagnostic", "--notify"]), 1)
            self.assertIn("12,000원", send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
