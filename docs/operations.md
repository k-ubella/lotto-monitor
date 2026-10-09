# 기존 워크플로 중단 기록

확인일: 2026년 10월 9일, 한국시간.

| 저장소 | 경로 | GitHub 상태 |
| --- | --- | --- |
| k-ubella/lotoManager | .github/workflows/action.yml | disabled_manually |
| k-ubella/vibe-lotto | .github/workflows/buy_lotto.yml | disabled_manually |
| k-ubella/vibe-lotto | .github/workflows/check_winning.yml | disabled_manually |

두 저장소의 `in_progress`와 `queued` 실행 조회는 모두 빈 목록이었다. 완료된 실행 이력과 워크플로 파일은 보존했다.

`lotoManager/.github/workflows/balance-check.yml`은 수동 전용이며 active 상태다. 자동 예약은 없다. 다른 서버·서비스의 스케줄러는 이번 점검 대상이 아니므로 중단됐다고 주장하지 않는다.

이 기록은 확인 당시 상태이며, 사용자가 나중에 워크플로를 활성화하거나 설정을 바꾸면 현재 상태가 달라질 수 있다.

## 같은 날 추가한 수동 조회 진단

`vibe-lotto/.github/workflows/monitor-balance-diagnostic.yml`을 추가했다. `workflow_dispatch`만 허용하며 예약 실행은 없다. 검토한 `lotto-monitor`의 전체 커밋 SHA를 고정해 체크아웃하고, 기존 비공개 Secrets로 로그인·잔액 조회를 실행한다. 단계·고정 진단 코드만 출력하며 금액·계정·원본 응답은 출력하지 않는다. Discord·개인 서버·구매 작업은 호출하지 않는다.

수동 진단에서 실제 잔액 조회 성공을 확인한 뒤에도 기존 예약 워크플로 3개는 `disabled_manually` 상태로 유지했다. 상세 결과는 [실서비스 진단 기록](live-diagnostics.md)에 정리했다.

## 같은 날 추가한 수동 Discord 테스트

`vibe-lotto/.github/workflows/monitor-discord-test.yml`을 추가했다. 예약 없이 `workflow_dispatch`로만 실행하며, 기존 비공개 웹훅 Secret과 검토한 공개 코드의 전체 SHA를 사용한다. 실제 계정 조회 없이 고정 테스트 메시지 한 건을 전송하고 재조회해 내용 일치를 확인했다. 실제 금액·웹훅·메시지 ID는 로그에 출력하지 않는다. 기존 예약 작업 3개의 비활성화 상태를 다시 확인했다. 상세 결과는 [전송 검증 기록](discord-delivery.md)에 정리했다.
