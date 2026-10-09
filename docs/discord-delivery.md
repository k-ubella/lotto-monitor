# Discord 수동 전송 검증

점검일: 2026년 10월 9일, 한국시간.

## 구현

문구 생성은 `monitor/balance.py`, 전송은 `monitor/discord.py`로 분리했다. `notify-test`는 계정 조회 없이 테스트 목적과 실행 시각만 포함한 고정 메시지 한 건을 보낸다. `live --notify`는 실제 조회 결과를 전송한다. 성공 시 실제 잔액이 포함되며, 조회 실패는 금액 없는 상태 메시지로 표시한다. `--diagnostic`은 터미널 로그만 제한한다.

[Discord 공식 Webhook 문서](https://docs.discord.com/developers/resources/webhook#execute-webhook)에 따라 `wait=true`로 저장 확인을 요청하고, 응답 메시지 ID로 다시 조회해 본문을 대조한다. 모든 멘션은 `allowed_mentions.parse=[]`로 비활성화했다.

웹훅은 HTTPS Discord 호스트와 웹훅 경로만 허용한다. `wait` 외의 쿼리 옵션, 별도 호스트, 리다이렉트는 지원하지 않는다. 따라서 포럼·스레드 전송은 현재 지원하지 않는다. 연결·응답 제한 시간을 적용하고 자동 재시도는 하지 않는다. 웹훅은 환경 변수 또는 기존 비공개 저장소의 Secrets에서만 사용한다.

## 결과 코드

| 코드 | 의미 |
| --- | --- |
| `message_verified` | 전송 확인 응답과 메시지 재조회 내용이 모두 일치 |
| `webhook_missing` / `invalid_webhook` | 웹훅 설정 없음 또는 허용하지 않는 URL |
| `invalid_message` | 비어 있거나 2,000자를 넘는 메시지 |
| `webhook_unavailable` | Discord 401·403·404 응답 |
| `rate_limited` | 전송 요청에 Discord 429 응답 |
| `send_unconfirmed` | 전송 확인 응답을 검증하지 못함; 이미 전송됐을 수 있음 |
| `readback_unconfirmed` | 전송 응답 후 재조회 검증 실패; 이미 전송됐을 수 있음 |
| `dependencies_missing` | 선택적 전송 의존성 미설치 |

모든 실패는 종료 코드 1로 표시한다. 재조회 실패 시 메시지가 이미 존재할 수 있어 자동으로 다시 보내지 않는다. 로그에는 코드만 남기며 웹훅·응답 본문·메시지 ID를 출력하지 않는다.

## 검증 상태

모의 응답으로 전송·재조회 성공, 멘션 비활성화, 제한 시간, 리다이렉트 거부, 오류 HTTP 상태, 메시지 ID 누락, 재조회 불일치, 전송 예외, CLI 종료 코드와 명시적 전송 옵션을 검증했다.

기존 비공개 저장소의 `DISCORD_WEBHOOK_URL` Secret을 사용하는 수동 전용 `Monitor Discord Test`에서 테스트 메시지 한 건을 전송했다. 전송 확인 응답 후 메시지를 다시 조회해 내용을 대조했고, 결과는 다음과 같다.

```json
{"delivery": "message_verified"}
```

검증한 코드 커밋은 `aa67962`이며 [검증 실행](https://github.com/k-ubella/vibe-lotto/actions/runs/37903488963)은 비공개 저장소 접근 권한이 필요하다. 테스트 메시지에는 실제 계정·잔액을 포함하지 않았고, 웹훅은 공개 저장소로 복사하지 않았다. 총 44개 로컬 테스트가 통과했다. 실제 전송에 사용한 코드의 Python 3.10·3.12 CI도 성공했다.

실제 계정 잔액을 Discord에 보내는 통합 경로는 모의 응답으로 검증했으며, 이번 실전송에서는 실행하지 않았다. 예약·반복 전송과 장기간 운영은 검증하지 않았다. 기존 예약 작업 3개는 계속 `disabled_manually` 상태다.
