"""Opt-in account balance reader. Output contains fixed diagnostic codes only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from typing import Callable
from urllib.parse import urljoin, urlsplit

from .balance import BalanceResult, parse_balance


ORIGIN = "https://www.dhlottery.co.kr"
BALANCE_PATH = "/mypage/selectUserMndp.do"


class ReadFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def extract_balance(payload: object) -> int:
    if not isinstance(payload, dict):
        raise ReadFailure("unexpected_json_shape")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ReadFailure("balance_missing")
    data = data.get("userMndp", data)
    if not isinstance(data, dict) or "totalAmt" not in data:
        raise ReadFailure("balance_missing")
    try:
        return parse_balance(data["totalAmt"])
    except ValueError:
        raise ReadFailure("invalid_balance") from None


def encrypt_credentials(username: str, password: str, modulus: str, exponent: str) -> dict:
    from Crypto.Cipher import PKCS1_v1_5
    from Crypto.PublicKey import RSA

    try:
        cipher = PKCS1_v1_5.new(RSA.construct((int(modulus, 16), int(exponent, 16))))
        return {
            "userId": cipher.encrypt(username.encode("utf-8")).hex(),
            "userPswdEncn": cipher.encrypt(password.encode("utf-8")).hex(),
            "inpUserId": username,
        }
    except (ValueError, TypeError):
        raise ReadFailure("invalid_rsa_key") from None


@dataclass(frozen=True)
class LiveOutcome:
    result: BalanceResult
    stage: str
    code: str

    def diagnostic(self) -> str:
        # Neither amount, username, cookies nor remote error content is serialized.
        return json.dumps({"status": self.result.status, "stage": self.stage, "code": self.code})


class BalanceReader:
    def __init__(self, session, encrypt: Callable = encrypt_credentials):
        self.session = session
        self.encrypt = encrypt
        self.stage = "start"

    def _request(self, method: str, path: str, **kwargs):
        url = urljoin(ORIGIN, path)
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/html;q=0.8",
            "Referer": ORIGIN + "/login",
            "Origin": ORIGIN,
        }
        if path == BALANCE_PATH:
            headers.update({
                "X-Requested-With": "XMLHttpRequest",
                "requestMenuUri": "/mypage/home",
                "AJAX": "true",
                "Referer": ORIGIN + "/mypage/home",
            })
        for _ in range(4):
            parsed = urlsplit(url)
            if (parsed.scheme, parsed.netloc) != ("https", "www.dhlottery.co.kr"):
                raise ReadFailure("unexpected_redirect")
            response = self.session.request(
                method, url, headers=headers, timeout=(10, 20), allow_redirects=False, **kwargs
            )
            if response.status_code in (301, 302, 303, 307, 308):
                target = response.headers.get("Location")
                if not target:
                    raise ReadFailure("invalid_redirect")
                url = urljoin(url, target)
                # Never replay credentials to a redirected URL, even on the same origin.
                if method == "POST":
                    if response.status_code in (307, 308):
                        raise ReadFailure("credential_redirect")
                    method, kwargs = "GET", {}
                continue
            if response.status_code in (401, 403):
                raise ReadFailure("access_denied")
            if response.status_code == 429:
                raise ReadFailure("rate_limited")
            if response.status_code != 200:
                raise ReadFailure("http_error")
            return response
        raise ReadFailure("redirect_limit")

    @staticmethod
    def _json(response):
        if response.text.lstrip().startswith("<"):
            raise ReadFailure("html_instead_of_json")
        try:
            return response.json()
        except ValueError:
            raise ReadFailure("invalid_json") from None

    def read(self, username: str, password: str) -> LiveOutcome:
        now = datetime.now(timezone.utc).isoformat()
        try:
            if not username or not password:
                raise ReadFailure("credentials_missing")
            self.stage = "login_page"
            self._request("GET", "/login")
            self.stage = "unauthenticated_baseline"
            response = self._request("GET", BALANCE_PATH)
            try:
                extract_balance(self._json(response))
            except ReadFailure:
                pass  # Login is needed; a cookie by itself is never proof of authentication.
            else:
                raise ReadFailure("authentication_unverified")
            self.stage = "rsa_key"
            payload = self._json(self._request("GET", "/login/selectRsaModulus.do"))
            key = payload.get("data", payload) if isinstance(payload, dict) else None
            if not isinstance(key, dict) or not all(isinstance(key.get(k), str) and key[k] for k in ("rsaModulus", "publicExponent")):
                raise ReadFailure("rsa_key_missing")
            data = self.encrypt(username, password, key["rsaModulus"], key["publicExponent"])
            self.stage = "login_submit"
            self._request("POST", "/login/securityLoginCheck.do", data=data)
            self.stage = "balance"
            amount = extract_balance(self._json(self._request("GET", BALANCE_PATH)))
            return LiveOutcome(BalanceResult(now, "ok", amount, "dhlottery"), self.stage, "balance_verified")
        except ReadFailure as failure:
            unavailable = failure.code in {"credentials_missing", "access_denied", "rate_limited", "authentication_unverified", "html_instead_of_json", "balance_missing"}
            result = BalanceResult(now, "unavailable" if unavailable else "error", None, "dhlottery")
            return LiveOutcome(result, self.stage, failure.code)
        except Exception as error:
            # Session/crypto exceptions may include request bodies, URLs or identifiers.
            code = "transport_or_crypto_error"
            try:
                from requests import exceptions
            except ImportError:
                pass
            else:
                for error_type, diagnostic_code in [
                    (exceptions.ConnectTimeout, "connect_timeout"),
                    (exceptions.ReadTimeout, "read_timeout"),
                    (exceptions.SSLError, "tls_error"),
                    (exceptions.ConnectionError, "connection_error"),
                    (exceptions.Timeout, "request_timeout"),
                ]:
                    if isinstance(error, error_type):
                        code = diagnostic_code
                        break
            return LiveOutcome(BalanceResult(now, "error", None, "dhlottery"), self.stage, code)


def read_account() -> LiveOutcome:
    username, password = os.environ.get("LOTTO_USERNAME", ""), os.environ.get("LOTTO_PASSWORD", "")
    if not username or not password:
        return BalanceReader(None).read(username, password)
    try:
        import requests
        import Crypto.Cipher.PKCS1_v1_5
        with requests.Session() as session:
            return BalanceReader(session).read(username, password)
    except ImportError:
        return LiveOutcome(
            BalanceResult(datetime.now(timezone.utc).isoformat(), "error", None, "dhlottery"),
            "dependencies", "dependencies_missing",
        )
