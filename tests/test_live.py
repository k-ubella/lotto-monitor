import contextlib
import io
import importlib.util
import json
import unittest
from unittest.mock import Mock, patch

from monitor.__main__ import main
from monitor.live import BalanceReader, ORIGIN, ReadFailure, encrypt_credentials, extract_balance


def response(payload=None, text="{}", status=200, headers=None):
    return Mock(status_code=status, headers=headers or {}, text=text, json=Mock(return_value=payload))


def session_responses(*responses):
    return Mock(request=Mock(side_effect=responses))


def sequence(amount=12000):
    return [response(text="<html>login</html>"), response({"data": None}),
            response({"data": {"rsaModulus": "abc", "publicExponent": "10001"}}),
            response(text="<html>submitted</html>"), response({"data": {"userMndp": {"totalAmt": amount}}})]


class LiveTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("Crypto"), "optional live dependencies not installed")
    def test_rsa_payload_round_trip(self):
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_v1_5
        key = RSA.generate(1024)
        encrypted = encrypt_credentials("example", "example-password", format(key.n, "x"), format(key.e, "x"))
        decrypt = PKCS1_v1_5.new(key)
        self.assertEqual(decrypt.decrypt(bytes.fromhex(encrypted["userId"]), b"invalid"), b"example")
        self.assertEqual(decrypt.decrypt(bytes.fromhex(encrypted["userPswdEncn"]), b"invalid"), b"example-password")

    def test_supported_balance_shapes_and_true_zero(self):
        for data in [{"totalAmt": 0}, {"data": {"totalAmt": "12,000"}}, {"data": {"userMndp": {"totalAmt": 12000}}}]:
            with self.subTest(data=data):
                self.assertIn(extract_balance(data), [0, 12000])

    def test_missing_or_invalid_amount_never_becomes_zero(self):
        for data in [{}, {"data": None}, {"data": []}, {"userMndp": None}, {"totalAmt": "오류 500"}, {"totalAmt": True}]:
            with self.subTest(data=data), self.assertRaises(ReadFailure):
                extract_balance(data)

    def test_verified_balance_and_allowed_request_methods(self):
        for amount in [0, 12000]:
            session = session_responses(*sequence(amount))
            encrypt = Mock(return_value={"userId": "encrypted", "userPswdEncn": "encrypted", "inpUserId": "example"})
            result = BalanceReader(session, encrypt).read("example", "example-password")
            self.assertEqual(result.result.balance_krw, amount)
            self.assertEqual(result.code, "balance_verified")
            for call in session.request.call_args_list:
                self.assertTrue(call.args[1].startswith(ORIGIN + "/"))
                self.assertEqual(call.kwargs["timeout"], (10, 20))
                self.assertFalse(call.kwargs["allow_redirects"])
                if call.args[0] == "POST":
                    self.assertEqual(call.args[1], ORIGIN + "/login/securityLoginCheck.do")

    def test_login_post_success_does_not_prove_authenticated(self):
        replies = sequence()
        replies[-1] = response(text="<html>login required</html>")
        outcome = BalanceReader(session_responses(*replies), Mock(return_value={})).read("example", "example")
        self.assertEqual(outcome.result.status, "unavailable")
        self.assertEqual(outcome.stage, "balance")
        self.assertEqual(outcome.code, "html_instead_of_json")
        self.assertIsNone(outcome.result.balance_krw)

    def test_public_zero_response_is_not_proof_of_login(self):
        session = session_responses(response(), response({"totalAmt": 0}))
        outcome = BalanceReader(session).read("example", "example")
        self.assertEqual(outcome.code, "authentication_unverified")
        self.assertEqual(session.request.call_count, 2)

    def test_denied_and_rate_limited_requests_stop_without_retries(self):
        for status, code in [(403, "access_denied"), (429, "rate_limited"), (503, "http_error")]:
            session = session_responses(response(status=status))
            outcome = BalanceReader(session).read("example", "example")
            self.assertEqual(outcome.code, code)
            self.assertEqual(session.request.call_count, 1)

    def test_cross_origin_redirect_is_rejected(self):
        session = session_responses(response(status=302, headers={"Location": "https://example.org/"}))
        outcome = BalanceReader(session).read("example", "example")
        self.assertEqual(outcome.code, "unexpected_redirect")
        self.assertEqual(session.request.call_count, 1)

    def test_post_redirect_never_replays_credentials(self):
        replies = sequence()
        replies[3] = response(status=302, headers={"Location": "/main"})
        replies.insert(4, response())
        session = session_responses(*replies)
        outcome = BalanceReader(session, Mock(return_value={"inpUserId": "example"})).read("example", "example")
        self.assertEqual(outcome.code, "balance_verified")
        redirected = session.request.call_args_list[4]
        self.assertEqual(redirected.args[0], "GET")
        self.assertNotIn("data", redirected.kwargs)

    def test_307_login_redirect_is_not_followed(self):
        replies = sequence()
        replies[3] = response(status=307, headers={"Location": "/other"})
        session = session_responses(*replies)
        outcome = BalanceReader(session, Mock(return_value={})).read("example", "example")
        self.assertEqual(outcome.code, "credential_redirect")
        self.assertEqual(session.request.call_count, 4)

    def test_diagnostic_has_no_balance_credentials_or_remote_error(self):
        session = session_responses(RuntimeError("private-response-and-password"))
        outcome = BalanceReader(session).read("example", "example")
        self.assertEqual(json.loads(outcome.diagnostic()), {"status": "error", "stage": "login_page", "code": "transport_or_crypto_error"})
        successful = BalanceReader(session_responses(*sequence()), Mock(return_value={})).read("example", "example")
        self.assertNotIn("12000", successful.diagnostic())

    def test_bad_rsa_key_is_rejected_before_login_post(self):
        replies = sequence()
        replies[2] = response({"data": {}})
        session = session_responses(*replies)
        outcome = BalanceReader(session).read("example", "example")
        self.assertEqual(outcome.code, "rsa_key_missing")
        self.assertEqual(session.request.call_count, 3)

    def test_missing_balance_after_login_is_not_success(self):
        replies = sequence()
        replies[-1] = response({"data": {}})
        outcome = BalanceReader(session_responses(*replies), Mock(return_value={})).read("example", "example")
        self.assertEqual(outcome.code, "balance_missing")
        self.assertIsNone(outcome.result.balance_krw)

    def test_invalid_json_is_a_sanitized_failure(self):
        replies = sequence()
        replies[-1] = response()
        replies[-1].json.side_effect = ValueError("private response")
        outcome = BalanceReader(session_responses(*replies), Mock(return_value={})).read("example", "example")
        self.assertEqual(outcome.code, "invalid_json")
        self.assertNotIn("private", outcome.diagnostic())

    def test_missing_credentials_cli_does_not_connect(self):
        with patch.dict("os.environ", {}, clear=True), patch("socket.socket", side_effect=AssertionError("Network forbidden")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["live", "--diagnostic"]), 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "credentials_missing")


if __name__ == "__main__":
    unittest.main()
