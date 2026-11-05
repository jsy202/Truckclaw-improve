# 자소서용 검증: 수정 전 20회 / 수정 후 20회

## 검증 배경

사용자가 직접 수행한 사전 테스트 20회 중 AI 에이전트의 중복 호출이 1회
발생했다. 이를 계기로 동일 요청이 반복 전달됐을 때 차량 제어가 안전하게
동작하는지 확인하는 이번 검증을 진행했다.

사전 관찰은 실제 에이전트 호출에 대한 기록이며, 아래 표는 동일 HTTP 요청을
두 번씩 전달한 CARLA 반복 검증 결과다. 두 실행의 분모와 결과는 별도로 집계한다.

## 최종 결과

| 항목 | 수정 전 | 수정 후 |
|---|---:|---:|
| 유효 물리 실행 | 20회 | 20회 |
| 충돌 발생 회차 | **20/20회** | **0/20회** |
| 충돌 없는 회차 | 0/20회 | **20/20회** |
| 회차별 동일 요청 전달 | 2회 | 2회 |
| 회차별 제어 시작 | 2회 | 1회 |
| 중복 요청 이후 제동 | 해제 | 유지 |
| 최종 속도 | 충돌 후 기록 참조 | 전체 0.0 m/s |

최초 40회 시도에는 수정 전 3회차의 CARLA 시작 오류 1건이 포함됐다.
렌더링 스레드가 준비 중 시간 초과로 종료되어 차량 실험을 시작하지 못했다.
이 회차를 충돌 없음으로 세지 않았고, 원본 로그를 보존한 상태에서 별도 재실행했다.
재실행에서도 충돌이 발생했다. **총 실제 시도 41회 = 유효 실행 40회 + 환경 오류 1회**다.

## 회차별 충돌 센서 이벤트

| 회차 | 수정 전 | 수정 후 |
|---|---:|---:|
| 01 | 1 | 0 |
| 02 | 1 | 0 |
| 03 | 1 (별도 재실행) | 0 |
| 04 | 1 | 0 |
| 05 | 1 | 0 |
| 06 | 1 | 0 |
| 07 | 1 | 0 |
| 08 | 1 | 0 |
| 09 | 1 | 0 |
| 10 | 1 | 0 |
| 11 | 1 | 0 |
| 12 | 1 | 0 |
| 13 | 1 | 0 |
| 14 | 1 | 0 |
| 15 | 1 | 0 |
| 16 | 1 | 0 |
| 17 | 1 | 0 |
| 18 | 1 | 0 |
| 19 | 1 | 0 |
| 20 | 1 | 0 |

## 조건과 판정

- CARLA 0.9.13, Town06, 동일 트럭 두 대, 고정 시간 간격 0.05초.
- 매 회차 새 서버를 시작하고 화면 창 없이 `-RenderOffScreen`으로 실행.
- 별도 제어 모델에서 최초 요청 → 안전 정지 → 같은 요청 재전달 순서로 검증.
- 수정 전: 재요청으로 제동 상태가 초기화되어 앞 트럭과 충돌하는지 검사.
- 수정 후: 재요청 후 600 tick(시뮬레이션 30초) 동안 가속 0·제동 1을 유지하는지 검사.
- 충돌 센서의 상대 actor와 frame으로 실제 트럭 충돌 및 재요청 이후 발생 여부를 확인.
- 시작 오류, 정지 실패, 사전 충돌은 정상 완료 결과와 구분.

동일 조건을 반복한 결과이며, 다양한 도로·속도·LLM 입력 전체의 안전성을
의미하지는 않는다. 적용한 중복 요청 방지의 보장 범위는 현재 제어기 프로세스 내다.

## 근거 파일

출력 폴더: [`evidence_20runs_20261106/`](evidence_20runs_20261106/)

- [`manifest.json`](evidence_20runs_20261106/manifest.json): 배경과 실행 조건.
- [`runs.jsonl`](evidence_20runs_20261106/runs.jsonl): 최초 40회 시도의 원본 집계.
- [`summary.json`](evidence_20runs_20261106/summary.json): 최초 집계(환경 오류 포함).
- [`reruns.json`](evidence_20runs_20261106/reruns.json): 별도 재실행 결과.
- [`verified_summary.json`](evidence_20runs_20261106/verified_summary.json): 원래 오류를 보존한 최종 20+20 집계.
- 각 회차의 `result.json`, `telemetry.json`, `before_duplicate.png`, `final.png`.
- 충돌한 회차의 `collision.png`.
- [`pytest_final.txt`](evidence_20runs_20261106/pytest_final.txt): 전체 회귀 테스트 출력.

예시: [수정 전 충돌](evidence_20runs_20261106/vulnerable/run020/vulnerable/collision.png),
[수정 후 정지 유지](evidence_20runs_20261106/fixed/run020/fixed/final.png),
[3회차 환경 오류 로그](evidence_20runs_20261106/vulnerable/run003/runner.log),
[3회차 재실행 충돌](evidence_20runs_20261106/reruns/vulnerable/run003/vulnerable/collision.png).

## 회귀 검증 실행

```bash
DUPLICATE_COMMIT_EVIDENCE=experiments/duplicate_commit/evidence DUPLICATE_COMMIT_BATCH_EVIDENCE=experiments/duplicate_commit/evidence_20runs_20261106 python3 -m pytest -q
```

반복 검증 전용 pytest가 최종 집계의 모든 40회차 JSON과 제어 기록을 다시 읽는다.
각 조건의 회차가 정확히 1~20인지, 모든 요청이 실제 두 번 전달됐는지, 충돌이
재요청 이후인지, 수정 후 600 tick 전체에서 제동이 유지됐는지 검사한다.

최종 전체 테스트 결과: **46 passed in 13.39s**. 사용한 CARLA 프로세스는 모두 종료했다.
