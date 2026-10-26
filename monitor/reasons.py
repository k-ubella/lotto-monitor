"""Plain-language cause and next step for each diagnostic code, shown in Discord failure alerts."""

from __future__ import annotations

SITE_FORMAT = "사이트 응답 형식이 예상과 다릅니다. 사이트 개편 가능성이 있어 코드 확인이 필요합니다."
NETWORK = "사이트에 연결하지 못했거나 응답이 늦었습니다. 일시적인 경우가 많아 다음 실행에서 다시 확인합니다."

REASONS = {
    "credentials_missing": "GitHub Secrets에 `LOTTO_USERNAME`/`LOTTO_PASSWORD`가 없습니다. 저장소 Settings → Secrets에 등록하세요.",
    "dependencies_missing": "실행에 필요한 패키지가 설치되지 않았습니다. 워크플로 설치 단계를 확인하세요.",
    "password_change_notice": "동행복권이 '비밀번호 변경안내' 화면을 띄웠는데 '다음에 변경' 버튼을 자동으로 찾지 못했습니다. 사이트에 직접 로그인해 '다음에 변경'을 누르거나 비밀번호를 바꾸세요. 비밀번호를 바꿨다면 GitHub Secret `LOTTO_PASSWORD`도 함께 바꿔야 합니다. 실행 로그의 `notice` 항목으로 자동 처리를 고칠 수 있습니다.",
    "password_notice_defer_failed": "'비밀번호 변경안내'에서 '다음에 변경'을 자동으로 눌렀지만 로그인이 완료되지 않았습니다. 사이트에 직접 로그인해 처리하세요. 실행 로그의 `notice` 항목으로 자동 처리를 고칠 수 있습니다.",
    "wrong_credentials": "아이디 또는 비밀번호가 맞지 않습니다. 사이트 비밀번호와 GitHub Secret `LOTTO_PASSWORD`가 같은지 확인하세요. 실패가 반복되면 계정이 잠길 수 있습니다.",
    "account_locked": "로그인 실패 누적 등으로 계정이 잠겼습니다. 사이트에서 잠금을 해제한 뒤 다시 실행하세요.",
    "dormant_account": "휴면 계정으로 전환됐습니다. 사이트에서 휴면 해제 후 다시 실행하세요.",
    "login_rejected": "사이트가 로그인을 거절했습니다. 아래 사이트 안내를 확인하세요.",
    "authentication_unverified": "로그인 전인데도 잔액이 조회되는 비정상 응답이라 진행을 멈췄습니다.",
    "rate_limited": "요청이 너무 잦아 사이트가 일시적으로 막았습니다. 잠시 후 다시 실행하세요.",
    "html_instead_of_json": "사이트가 데이터 대신 웹페이지를 돌려줬습니다. 점검 중이거나 로그인이 풀렸을 수 있습니다.",
    "http_error": "사이트가 서버 오류로 응답했습니다. 점검 또는 일시 장애일 수 있습니다.",
    "ready_ip_missing": "구매 서버가 접속 정보를 주지 않았습니다. 판매 시간이 아니거나(평일·일 06~24시, 토 20시 마감) 구매 서버 점검일 수 있습니다.",
    "round_missing": "판매 중인 회차를 확인하지 못했습니다. " + SITE_FORMAT,
    "purchase_rejected": "사이트가 구매를 거절했습니다(잔액 부족, 주간 한도 초과, 판매 시간 외 등). 아래 사유를 확인하세요.",
    "unexpected_purchase_response": "구매 요청 후 결과를 해석하지 못했습니다. 이미 구매됐을 수 있으니 구매 내역을 확인하세요.",
    "unreadable_tickets": "구매는 성공으로 응답했지만 번호를 읽지 못했습니다. 구매 내역에서 번호를 확인하세요.",
    "draw_not_published": "당첨번호가 아직 발표되지 않았습니다. 다음 예약 실행에서 다시 확인합니다.",
    "unexpected_draw_shape": "당첨번호 응답 형식이 예상과 다릅니다. " + SITE_FORMAT,
    "invalid_game_count": "게임 수는 1~5만 가능합니다.",
    "unexpected_redirect": "사이트가 동행복권 밖의 주소로 이동시켜 안전을 위해 멈췄습니다.",
    "credential_redirect": "로그인 정보를 다른 주소로 다시 보내라는 응답이라 안전을 위해 멈췄습니다.",
    "invalid_redirect": "사이트의 페이지 이동 응답이 비정상입니다.",
    "redirect_limit": "페이지 이동이 너무 많이 반복돼 멈췄습니다. 로그인 후 안내 화면이 반복되는지 확인하세요.",
    "transport_or_crypto_error": "분류되지 않은 오류입니다. Actions 실행 로그를 확인하세요.",
}
for _code in ["invalid_json", "unexpected_json_shape", "balance_missing", "invalid_balance", "rsa_key_missing", "invalid_rsa_key"]:
    REASONS[_code] = SITE_FORMAT
for _code in ["connect_timeout", "read_timeout", "tls_error", "connection_error", "request_timeout"]:
    REASONS[_code] = NETWORK


def explain(code: str, stage: str = "") -> str:
    if code == "access_denied":
        if stage == "balance":
            # Login POST went through but the session was not accepted.
            return ("로그인 요청은 보냈지만 사이트가 로그인 상태로 인정하지 않았습니다. "
                    "사이트에 직접 로그인해 '비밀번호 변경안내' 같은 안내 화면이 뜨는지 확인하세요.")
        return "사이트가 접근을 거부했습니다(403). GitHub 서버 IP를 막았거나 일시적인 차단일 수 있습니다."
    return REASONS.get(code, "알 수 없는 진단 코드입니다. Actions 실행 로그를 확인하세요.")
