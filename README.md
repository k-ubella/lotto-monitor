# lotto-monitor

모의 데이터로 잔액 결과를 표시하고, 알림 문구를 생성하며, 로컬 기록을 조회하는 Python 예제입니다. GitHub Actions 진단 사례와 코드 선별 기록도 포함합니다.

오프라인 예제와 명시적으로 실행하는 로그인·잔액 조회 어댑터를 포함합니다. Discord 전송·구매 기능은 없습니다. 자동 예약은 없으며, 공개 저장소의 GitHub Actions는 push·PR·수동 실행 시 모의 데이터 테스트만 수행합니다. 기존 저장소의 Git 이력과 계정 파일은 가져오지 않았습니다.

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

2026년 10월 9일 기존 비공개 저장소의 Secrets를 사용한 수동 진단에서 실제 로그인·잔액 조회가 성공했습니다. 공개 저장소에는 자격 증명을 복사하지 않았습니다. 장기간 운영과 알림 전달은 아직 검증하지 않았습니다.

`--diagnostic`을 생략하면 실제 잔액이 터미널에 표시됩니다. `--db local/results.sqlite3`를 명시하면 정규화한 조회 결과를 로컬에 기록합니다. 공개 Actions 로그에는 진단 모드만 사용하세요. 사이트 접근 차단·로그인 실패·응답 형식 변경 시 중단하며, 로그인 자동 재시도는 하지 않습니다. 자세한 검증 상태는 [실서비스 진단 기록](docs/live-diagnostics.md)을 확인하세요.

## 문서

- [블로그 게시용 글 초안](docs/blog.md): 두 저장소의 알림 출처를 실행 시각과 문구로 구분하고, API 접근 차단과 잔액 조회 오류를 진단한 과정
- [공개 프로젝트 구성안](docs/repository-plan.md): 선별 기준, 확인한 기능과 미검증 기능, 공개 전 확인 항목
- [기존 워크플로 중단 기록](docs/operations.md): 2026년 10월 9일 확인한 비활성화 상태
- [코드 선별 및 검증](docs/code-review.md): 검토한 원본, 이전 범위, 테스트 항목

## 현재 확인한 범위

알림 문구와 실행 시각 대조, GitHub API 네트워크 차단 원인, 잔액 전용 테스트의 실패, 기존 예약 워크플로 비활성화는 확인했습니다. 기존 잔액 조회 코드는 페이지 요소를 찾지 못해 실패했으며, 새 프로젝트에서 정상 작동한다고 소개하지 않습니다.

모의 데이터로 금액 검증, 조회 실패 표시, 알림 출처·시각, 로컬 기록 저장·조회, 종료 코드와 인증 응답 처리를 테스트합니다. 실제 서비스 연동의 확인 결과와 한계는 실서비스 진단 기록에 별도로 남깁니다. 비밀번호, 토큰, 웹훅 주소, 개인 서버 주소나 계정 데이터는 커밋하지 않습니다.

라이선스는 아직 지정하지 않았습니다. 공개 저장소라는 이유만으로 재배포·수정 권한이 부여되는 것은 아닙니다.
