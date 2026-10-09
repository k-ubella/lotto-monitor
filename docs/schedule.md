# 잔액 알림 예약 운영

> 2026년 10월 9일 실행 위치 변경: 이 저장소의 `.github/workflows/balance.yml`(`Balance Notification (Saturday)`)로 옮겼다. 매주 토 09:00 KST(`0 0 * * 6` UTC)에 이 저장소의 `LOTTO_USERNAME`, `LOTTO_PASSWORD`, `DISCORD_WEBHOOK_URL` Secrets로 실행한다. Discord 메시지는 예치금과 다음 주 평일 구매액(5,000원) 충족 여부를 표시하고, 부족하면 충전할 금액을 알린다. 중복 알림을 막기 위해 `vibe-lotto`의 `Monitor Live Balance Notification`은 비활성화했다. 아래는 변경 전 기록이다.

설정일: 2026년 10월 9일, 한국시간.

## 일정과 실행 위치

- 일정: 매주 토요일 오전 9시, `Asia/Seoul`.
- 첫 예정 시각: 2026년 10월 10일 오전 9시, 한국시간.
- 실행 저장소: 기존 비공개 `k-ubella/vibe-lotto`.
- 워크플로: `.github/workflows/monitor-live-notification.yml`, `Monitor Live Balance Notification`.
- 실행 코드: 공개 `lotto-monitor`의 검증한 전체 커밋 `95afe978d6e28588827d9c77122eb7d173bf9599`로 고정.

```yaml
on:
  workflow_dispatch:
  schedule:
    - cron: "0 9 * * 6"
      timezone: "Asia/Seoul"
```

GitHub에서 워크플로가 `active`이며 설정한 예약이 기본 브랜치에 저장된 것을 확인했다. 설정 후 아직 예약 시각이 도래하지 않아 첫 예약 실행은 미검증 상태다. 동일 코드는 실제 계정으로 잔액 조회·Discord 전송·메시지 재조회까지 수동 검증했다.

[GitHub 공식 예약 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)에 따르면 혼잡 시 예약 작업이 지연되거나 누락될 수 있다. 오전 9시 정각 도착을 보장하는 방식은 아니다. 예약 작업은 기본 브랜치의 워크플로로 실행한다.

## 자격 증명

기존 비공개 저장소의 `USERNAME`, `PASSWORD`, `DISCORD_WEBHOOK_URL` Secrets를 실행 중인 프로그램의 환경 변수에 전달한다. Secret 값은 GitHub API에서 조회하지 않았고 공개 저장소나 로컬 자격 증명 파일로 복사하지 않았다. 아이디·비밀번호는 프로그램이 로그인 요청을 처리하는 동안 사용하며, 웹훅은 Discord 전송·재조회에 사용한다.

실제 금액은 Discord 메시지에 포함된다. 로그에는 조회 상태·단계·고정 진단 코드와 전송 결과 코드만 출력한다. 계정 정보·실제 금액·웹훅·쿠키·원본 응답은 출력하지 않는다.

## 수동 실행과 중단

비공개 저장소의 Actions에서 `Monitor Live Balance Notification`을 선택해 `Run workflow`로 수동 실행할 수 있다. 수동 실행도 실제 잔액 메시지 한 건을 전송한다.

중단하려면 해당 워크플로를 GitHub에서 Disable workflow로 비활성화한다. 동일 워크플로의 실행은 `concurrency`로 직렬화하며, 추가 수동 요청은 대기 후 실행될 수 있다. 전송 자체를 자동 재시도하지 않으며, 실패 시 채널과 실행 결과를 확인한 뒤 재실행한다.

기존 구매·잔액 예약 워크플로 3개는 계속 `disabled_manually` 상태다. 새 예약은 잔액 조회와 Discord 알림만 수행한다.
