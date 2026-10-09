# 자동 구매 운영

설정일: 2026년 10월 9일, 한국시간.

## 이전 배경

| 원본 | 구매 방식 | 확인한 상태 |
| --- | --- | --- |
| `lotoManager/.github/workflows/action.yml` | 월~금 08:55 KST, 1게임 | 옛 로그인 주소를 사용해 최근 실행마다 `로또 구매 실패: 알 수 없는 오류`. 스크립트가 예외를 삼켜 워크플로는 성공으로 표시됐다. |
| `vibe-lotto/.github/workflows/buy_lotto.yml` | 토 08:55 KST, `COUNT`게임 | RSA 로그인 후 `ol.dhlottery.co.kr` 구매 요청. 2026년 10월 3일 실행에서 구매 성공(이후 DB 저장만 실패). |

두 워크플로 모두 `disabled_manually` 상태로 유지한다. 중복 구매를 막기 위해 다시 활성화하지 않는다.

이 저장소는 `vibe-lotto`의 구매 요청 형식(준비 서버 → 회차·날짜 → `execBuy.do`)을 이미 실제 검증한 `monitor/live.py` 로그인 위에 다시 구성했다. 일정은 `lotoManager`의 월~금 1게임을 따른다. 온라인 로또는 주당 5,000원 한도가 있어 월~금 1게임씩이면 한도를 채운다.

## 워크플로

- 파일: `.github/workflows/buy-lotto.yml`, `Buy Lotto (weekdays)`.
- 예약: `cron: '55 23 * * 0-4'` (UTC) = 월~금 08:55 KST. GitHub 혼잡 시 몇 시간 지연될 수 있다.
- 수동 실행: Actions → `Buy Lotto (weekdays)` → `Run workflow`. 게임 수 1~5를 고를 수 있고, `dry_run`이 기본으로 켜져 있어 실제 구매 없이 로그인·회차 확인만 한다. 실제 수동 구매는 `dry_run`을 끈다.
- 동시 실행은 `concurrency`로 직렬화한다. 구매 요청은 실행당 1회이며 재시도하지 않는다.

## 필요한 Secrets

이 저장소의 Settings → Secrets and variables → Actions에 등록한다. 값은 저장소 파일이나 로그에 넣지 않는다.

| 이름 | 내용 |
| --- | --- |
| `LOTTO_USERNAME` | 동행복권 아이디 |
| `LOTTO_PASSWORD` | 동행복권 비밀번호 |
| `DISCORD_WEBHOOK_URL` | 결과를 받을 Discord 웹훅 |

Secrets가 없으면 네트워크 접속 없이 `credentials_missing`으로 실패하며 구매하지 않는다.

## 결과와 종료 코드

| 상태 | 의미 | 종료 코드 |
| --- | --- | --- |
| `ok` | 구매 성공, 번호와 잔액을 Discord로 전송 | 0 |
| `dry_run` | 구매 직전까지 확인, 구매 요청 없음 | 0 |
| `rejected` | 사이트가 구매를 거절(한도 초과, 잔액 부족 등). 사유를 Discord로 전송 | 1 |
| `unconfirmed` | 구매 요청 후 응답을 확인하지 못함. 이미 구매됐을 수 있음 | 1 |
| `unavailable`·`error` | 구매 요청 전에 중단 | 1 |

공개 저장소의 Actions 로그는 누구나 볼 수 있으므로 `--diagnostic` 출력(상태·단계·진단 코드·게임 수·회차/날짜 출처)만 남긴다. 번호·잔액·사이트 메시지는 Discord에만 보낸다.

`dates_source`가 `computed`이면 구매 페이지에서 추첨일·지급기한을 찾지 못해 다가오는 토요일과 그 366일 뒤로 계산했다는 뜻이다(기존 `vibe-lotto`와 같은 대체값).

## 검증 상태

모의 응답으로 구매 요청 형식, 요청 1회 보장, 점검 실행, 거절·응답 유실 처리, 로그 비노출을 테스트했다. 실제 계정 구매와 예약 실행은 아직 검증하지 않았다. Secrets 등록 후 `dry_run` 수동 실행으로 먼저 확인한다.

## 중단

Actions에서 `Buy Lotto (weekdays)`를 Disable workflow로 비활성화한다.
