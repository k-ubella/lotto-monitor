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
