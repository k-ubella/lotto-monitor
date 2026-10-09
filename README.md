# lotto-monitor

모의 데이터로 잔액 결과를 표시하고, 알림 문구를 생성하며, 로컬 기록을 조회하는 Python 예제입니다. GitHub Actions 진단 사례와 코드 선별 기록도 포함합니다.

오프라인 예제와 로그인·잔액 조회·Discord 전송 어댑터, 로또6/45 자동번호 구매 기능을 포함합니다. 이 저장소의 `Buy Lotto (weekdays)` 워크플로가 월~금 오전 8시 55분 한국시간에 1게임씩 구매하며, `Balance Notification (Saturday)`가 매주 토요일 오전 9시 한국시간에 잔액을 알립니다. 기존 저장소의 Git 이력과 계정 파일은 가져오지 않았습니다.

## 실행

Python 3.9 이상에서 저장소 루트에서 실행합니다. 외부 패키지 설치나 환경 변수 설정은 필요하지 않습니다.

```bash
python3 -m unittest discover -s tests -v
python3 -m monitor demo tests/fixtures/balance-ok.json
python3 -m monitor demo tests/fixtures/balance-ok.json --db local/results.sqlite3
python3 -m monitor records local/results.sqlite3
```

첫 미리보기 결과:

```text
[lotto-monitor / fixture] 현재 잔액: 12,000원
관측 시각: 2026-10-09T17:00:00+09:00
```

위 금액과 시각은 테스트용 가상 값입니다. `--db`를 지정한 경우에만 정규화한 결과를 SQLite에 저장합니다. `records` 명령은 읽기 전용이며, 존재하지 않는 DB를 새로 만들지 않습니다. 같은 입력을 여러 번 저장하면 별도 관측 기록으로 추가됩니다. DB 파일은 Git에서 제외합니다.

```bash
python3 -m monitor demo tests/fixtures/balance-unavailable.json
python3 -m monitor demo tests/fixtures/balance-error.json
```

`ok`는 종료 코드 0, `unavailable`·`error`는 1, 입력·파일·DB 오류는 2를 반환합니다. 실패 결과는 0원으로 바꾸지 않습니다. `--db`로 실패 결과를 저장해도 명령은 종료 코드 1을 반환합니다. 알림 문구는 터미널에만 표시합니다.

## 실제 잔액 조회

```bash
python3 -m pip install -r requirements-live.txt
python3 -m monitor live --diagnostic
```

자격 증명은 실행 환경의 `LOTTO_USERNAME`, `LOTTO_PASSWORD`로만 전달합니다. 명령 인수나 소스 파일에 넣지 않습니다. 설정하지 않으면 네트워크 접속 없이 `credentials_missing`으로 종료합니다. `--diagnostic`은 금액·계정·쿠키·응답 본문 없이 단계와 고정 진단 코드만 출력합니다.

2026년 10월 9일 기존 비공개 저장소의 Secrets를 사용해 실제 로그인·잔액 조회, 고정 테스트 메시지 전송, 실제 잔액 메시지 전송·재조회를 수동으로 검증했습니다. 장기간 운영과 예약 실행은 아직 검증하지 않았습니다. 공개 저장소에는 자격 증명이나 실제 금액을 복사하지 않았습니다.

`--diagnostic`을 생략하면 실제 잔액이 터미널에 표시됩니다. `--db local/results.sqlite3`를 명시하면 정규화한 조회 결과를 로컬에 기록합니다. 공개 Actions 로그에는 진단 모드만 사용하세요. 사이트 접근 차단·로그인 실패·응답 형식 변경 시 중단하며, 로그인 자동 재시도는 하지 않습니다. 자세한 검증 상태는 [실서비스 진단 기록](docs/live-diagnostics.md)을 확인하세요.

## Discord 알림

환경 변수 `DISCORD_WEBHOOK_URL`에 웹훅을 설정한 환경에서 실행합니다. 웹훅은 명령 인수나 저장소 파일에 넣지 않습니다. `requirements-live.txt`의 선택적 의존성이 필요합니다.

```bash
# 계정 조회 없이 고정 테스트 메시지 한 건 전송
python3 -m monitor notify-test

# 실제 조회 결과를 Discord에 전송: 성공하면 실제 잔액을 포함
python3 -m monitor live --diagnostic --notify
```

`--notify`를 명시하지 않으면 `live`는 Discord에 전송하지 않습니다. `--diagnostic`은 터미널 로그를 숨기는 옵션이며, `--notify`로 보내는 메시지의 실제 잔액까지 숨기지는 않습니다. 조회 실패 시에는 금액 없이 미확인·실패 상태를 전송하고 종료 코드 1을 반환합니다.

전송 성공은 `message_verified`로 출력하며 메시지 본문·웹훅·메시지 ID를 로그에 남기지 않습니다. 전송이나 재조회 검증이 실패하면 종료 코드 1을 반환합니다. 시간 초과나 `readback_unconfirmed` 상황에서는 이미 메시지가 전송됐을 수 있으므로 채널을 확인한 후 수동으로 재실행하세요. [전송 검증 기록](docs/discord-delivery.md)에 동작과 실제 테스트 결과를 정리합니다.

이 저장소의 `Balance Notification (Saturday)`가 매주 토요일 오전 9시 한국시간에 잔액 알림을 실행합니다. 잔액이 다음 주 평일 구매액 5,000원보다 적으면 충전할 금액을 함께 알립니다. Actions의 `Run workflow`로 수동 실행도 가능합니다. 이전에 실행하던 `vibe-lotto`의 워크플로는 비활성화했습니다. [예약 운영 안내](docs/schedule.md)에 이력을 정리했습니다.

## 자동 구매

```bash
python3 -m pip install -r requirements-live.txt
python3 -m monitor buy --games 1 --dry-run --diagnostic   # 로그인·회차 확인만, 구매 요청 없음
python3 -m monitor buy --games 1 --diagnostic --notify    # 실제 구매 후 Discord 알림
```

`LOTTO_USERNAME`, `LOTTO_PASSWORD` 환경 변수로 로그인한 뒤 구매 서버 준비 → 회차 확인 → 구매 요청 1회를 보냅니다. 구매 요청은 재시도하지 않습니다. 응답이 끊기면 `unconfirmed`로 끝나며 이미 구매됐을 수 있으므로 구매 내역을 확인한 뒤 재실행하세요. 성공 시 번호와 잔액은 Discord 메시지에만 포함하고, `--diagnostic` 로그에는 단계·진단 코드·게임 수만 남깁니다. `--record 파일`을 주면 구매 요청을 보낸 실행의 회차·번호를 CSV에 추가합니다(잔액 제외). 워크플로는 이를 [`records/purchases.csv`](records/purchases.csv)에 커밋합니다. 2026년 10월 9일 실제 계정으로 점검 실행과 1게임 구매를 확인했습니다. 자세한 내용은 [자동 구매 운영](docs/purchase.md)을 확인하세요.

## 토요일 당첨 확인

```bash
python3 -m monitor check --round 1246
```

로그인 없이 공개 당첨번호를 조회해 `records/purchases.csv`의 해당 회차 번호와 대조합니다. `Check Lotto Winning (Saturday)` 워크플로가 토요일 21:30 KST에 실행해 결과를 Discord로 보내고 `records/draws.csv`, `records/winnings.csv`에 커밋합니다. 자세한 내용은 [토요일 당첨 확인](docs/winning.md)을 확인하세요.

## 통계

```bash
python3 -m monitor stats
```

구매·당첨 기록으로 [`records/STATS.md`](records/STATS.md)를 만듭니다. 구매액·당첨금·손익·회수율, 등수와 일치 개수 분포, 회차별·월별 표, 번호 빈도를 담으며 기록이 커밋될 때마다 자동으로 갱신됩니다. 잔액은 포함하지 않습니다. 자세한 내용은 [통계](docs/stats.md)를 확인하세요.

## 문서

- [블로그 게시용 글 초안](docs/blog.md): 두 저장소의 알림 출처를 실행 시각과 문구로 구분하고, API 접근 차단과 잔액 조회 오류를 진단한 과정
- [공개 프로젝트 구성안](docs/repository-plan.md): 선별 기준, 확인한 기능과 미검증 기능, 공개 전 확인 항목
- [기존 워크플로 중단 기록](docs/operations.md): 2026년 10월 9일 확인한 비활성화 상태
- [코드 선별 및 검증](docs/code-review.md): 검토한 원본, 이전 범위, 테스트 항목
- [Discord 전송 검증](docs/discord-delivery.md): 전송 확인·재조회·오류 처리
- [예약 운영 안내](docs/schedule.md): 토요일 오전 9시 알림과 자격 증명 사용 방식
- [자동 구매 운영](docs/purchase.md): 월~금 구매 워크플로, Secrets, 점검 실행과 중단 방법
- [토요일 당첨 확인](docs/winning.md): 당첨번호 대조, 등수 계산, 기록 파일
- [통계](docs/stats.md): `records/STATS.md` 구성과 계산 기준

## 현재 확인한 범위

이전 점검에서는 알림 출처와 일정, API 네트워크 차단, 기존 HTML 조회 오류, 예약 워크플로 비활성화를 확인했습니다. 이번에는 HTML 요소를 읽는 기존 코드를 대신해 JSON 잔액 응답을 검증하는 새 어댑터를 구현하고 실제 조회 성공을 확인했습니다. 과거 HTML 오류의 원인을 전부 규명한 것은 아닙니다.

모의 데이터로 금액 검증, 조회 실패 표시, 알림 출처·시각, 로컬 기록 저장·조회, 종료 코드와 인증 응답 처리를 테스트합니다. 실제 서비스 연동의 확인 결과와 한계는 실서비스 진단 기록에 별도로 남깁니다. 비밀번호, 토큰, 웹훅 주소, 개인 서버 주소나 계정 데이터는 커밋하지 않습니다.

라이선스는 아직 지정하지 않았습니다. 공개 저장소라는 이유만으로 재배포·수정 권한이 부여되는 것은 아닙니다.
