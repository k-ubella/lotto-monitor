# 토요일 보충 구매

평일 자동 구매가 한 게임이라도 빠지면(구매 거절, 실행 실패, 예치금 부족) 그 회차는 인터넷 구매 한도인
5게임을 채우지 못한 채 토요일 20:00 KST 판매 마감을 맞습니다. 토요일 보충 구매는 그 빈자리만 채웁니다.

```bash
python3 -m monitor catchup --records records --dry-run --diagnostic   # 계획만 확인
python3 -m monitor catchup --records records --diagnostic --notify --record "$RUNNER_TEMP/purchase/rows.csv"
```

## 계산

1. 로그인하면서 잔액을 읽고(로그인이 곧 잔액 검증), 구매 페이지/회차 API에서 **판매 중인 회차**를 읽습니다.
2. [`records/purchases.csv`](../records/purchases.csv)에서 그 회차의 `ok` 행 수를 셉니다. `rejected` 행은 아무것도 사지 않았으므로 세지 않습니다.
3. `missing = max(0, 5 - 구매한 게임 수)`.
4. `missing == 0`이면 구매 요청 없이 끝냅니다(`round_complete`).
5. `buy_count = min(missing, 잔액 // 1,000원)`. 잔액이 1,000원 미만이면 구매 요청 없이 충전 알림만 보냅니다(`deposit_short`).
6. 그 외에는 `buy_count`게임을 **구매 요청 1회**로 보냅니다. 구매 요청 뒤의 결과는 재시도하지 않습니다(평일 구매와 같은 원칙).

## 안전 장치

| 상황 | 동작 | 진단 코드 |
| --- | --- | --- |
| 이미 5게임 | 아무것도 사지 않고 정상 종료(종료 코드 0) | `round_complete` |
| 잔액 1,000원 미만 | 구매 요청 없음, 충전 필요 알림(종료 코드 0) | `deposit_short` |
| 이번 회차에 결과 미확인 구매가 있음 | 같은 회차를 더 사지 않고 구매 내역 확인 안내 | `purchase_unconfirmed_in_round` |
| 토요일 20:00 KST 이후이거나 토요일이 아님 | 로그인도 하지 않고 생략(종료 코드 0) | `outside_saturday_window` |
| 잔액 부족으로 일부만 가능 | `missing`보다 적게, 잔액이 허락하는 만큼만 구매 | — |

`outside_saturday_window`가 있는 이유: 예약 실행이 5~6시간 지연되면 토요일 마감 뒤나 일요일에 실행될 수 있습니다.
그때 보충하면 이미 **다음 회차**에 5게임을 사게 되어, 다음 주 월요일의 1게임이 회차 한도를 넘겨 거절됩니다.
그래서 실제 구매는 서울 시각 토요일 20:00 이전에만 합니다. `--dry-run`은 요일과 무관하게 계획만 계산합니다.

## 알림

성공하면 그 회차의 누적 게임 수와 남은 잔액을, 잔액이 5,000원 미만이면 `⚠️ **예치금 부족 — 충전 필요**`와
충전할 금액을 함께 보냅니다. 평일 구매 알림과 주간 잔액 알림도 같은 5,000원 기준으로 경고합니다.

```text
🛟 **로또6/45 1252회 · 토요일 보충 1게임 구매 완료** (1,000원)
A  자동  09  14  24  30  40  41      ← 코드 블록
이번 회차 5/5게임
💰 남은 잔액 **3,000원**
⚠️ **예치금 부족 — 충전 필요**
잔액이 5,000원보다 적습니다. **2,000원 이상 충전**하세요.
🕗 2026-11-28 (토) 10:15 KST · lotto-monitor
```

위 번호·잔액은 예시 값이다.

## 예약 워크플로 파일

이 파일은 `.github/workflows/buy-catchup.yml`로 저장소에 추가해야 예약이 켜진다. Pickle GitHub 앱에는
`workflows` 권한이 없어 이 저장소의 코드 작업에서 함께 푸시할 수 없으므로, 저장소 소유자가 GitHub 웹에서
[`.github/workflows/buy-catchup.yml` 새 파일 만들기](https://github.com/k-ubella/lotto-monitor/new/main?filename=.github/workflows/buy-catchup.yml)로
아래 내용을 붙여 넣고 `main`에 커밋한다(또는 Pickle 앱에 `workflows` 권한을 주고 다음 작업에서 푸시한다).

```yaml
name: Top Up Lotto (Saturday)

on:
  schedule:
    # 토 10:15 KST = 토 01:15 UTC. GitHub 혼잡 시 5~6시간 지연될 수 있어, 실제 구매는
    # 실행 시점의 서울 시각이 토요일 20:00 마감 전인지 코드가 다시 확인한다.
    - cron: '15 1 * * 6'
  workflow_dispatch:
    inputs:
      dry_run:
        description: '점검만 하고 실제 구매는 하지 않음'
        type: boolean
        default: true

permissions:
  contents: read

concurrency:
  group: lotto-records
  cancel-in-progress: false

jobs:
  top_up:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements-live.txt
      - name: Fill the round's missing games within the deposit
        env:
          LOTTO_USERNAME: ${{ secrets.LOTTO_USERNAME }}
          LOTTO_PASSWORD: ${{ secrets.LOTTO_PASSWORD }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          DRY_RUN: ${{ github.event_name == 'workflow_dispatch' && inputs.dry_run }}
        # 공개 저장소 로그에는 진단 코드·건수만 남기고 번호·잔액은 Discord로만 보낸다.
        run: |
          args=(catchup --records records --diagnostic --notify --record "$RUNNER_TEMP/purchase/rows.csv")
          if [ "$DRY_RUN" = "true" ]; then args+=(--dry-run); fi
          python -m monitor "${args[@]}"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: catchup-rows
          path: ${{ runner.temp }}/purchase/rows.csv
          if-no-files-found: ignore
          retention-days: 7

  # 쓰기 권한은 계정 Secrets가 없는 별도 job에서만 사용한다.
  record:
    needs: top_up
    if: always() && needs.top_up.result != 'cancelled'
    runs-on: ubuntu-latest
    timeout-minutes: 3
    permissions:
      contents: write
    steps:
      - id: rows
        uses: actions/download-artifact@v4
        continue-on-error: true
        with:
          name: catchup-rows
          path: ${{ runner.temp }}/purchase
      - uses: actions/checkout@v4
        if: steps.rows.outcome == 'success'
        with:
          ref: main
      - name: Commit top-up record and stats (no balance)
        if: steps.rows.outcome == 'success'
        run: |
          rows="$RUNNER_TEMP/purchase/rows.csv"
          mkdir -p records
          if [ -s records/purchases.csv ]; then tail -n +2 "$rows" >> records/purchases.csv; else cp "$rows" records/purchases.csv; fi
          python3 -m monitor stats --records records
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add records/
          git commit -m "Record lotto top-up $(TZ=Asia/Seoul date +%F) [skip ci]"
          for attempt in 1 2 3; do
            git push && exit 0
            git pull --rebase
          done
          exit 1
```

`permissions: contents: read`인 `top_up` job은 계정 Secrets로만 네트워크를 쓰고, 기록 커밋은 Secrets가 없는
`record` job이 `contents: write`로 수행한다. 평일 구매 워크플로와 같은 구조다.

## 검증 상태

모의 응답으로 회차별 게임 수 계산, 잔액 범위 내 구매 수, 5게임 완료·잔액 부족·결과 미확인·마감 후 생략,
구매 요청 1회, 구매 전 실패만 재시도, 기록·진단 출력에 잔액 미포함을 테스트한다
(`tests/test_catchup.py`). 실제 계정으로는 아직 실행하지 않았고, 실제 구매 테스트는 하지 않는다.
