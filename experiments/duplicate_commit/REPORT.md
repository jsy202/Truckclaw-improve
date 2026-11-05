# 자소서용 검증 결과

## 목적과 범위

동일 이송 요청의 반복 전달이 차량 안전 정지를 해제하는 상황을 별도 제어 모델에
구성했다. 결함을 주입한 모델과 수정 모델을 실제 CARLA 0.9.13 Town06에서 실행했다.
LLM 대신 HTTP 클라이언트가 같은 `transfer-001` 요청을 두 번 전달한다.
기존 전체 군집 이송 시나리오의 자연 발생 장애를 측정한 결과와는 구분한다.

## 문제

첫 요청 이후 차량이 안전 감지 입력으로 정지했다. 동일 요청이 다시 들어오자
실험용 제어기가 초기 가속 상태로 돌아가 앞에 정차한 트럭과 충돌했다.

## 문제 원인과 로그 분석

`commit()`이 매 호출마다 실행 횟수를 증가시키고 `braking=False`로 초기화했다.
수정 전에는 두 번째 요청에서도 `started=true`, `starts=2`, `braking=false`가
기록된다. 충돌 센서가 상대 트럭의 actor ID와 충격량을 기록하므로, 단순히
트리거가 두 번 전달됐다는 사실과 실제 물리 충돌을 구별할 수 있다.

## pytest 재현

수정 전 테스트 결과는 `2 failed, 2 passed`다.

- 제동 유지 검사: 기대 `(throttle=0, brake=1)`, 실제 `(throttle=1, brake=0)`.
- 동시 동일 요청 32회 검사: 기대 시작 1회, 실제 시작 32회.

원본 실패 출력은 `evidence/pytest_before.txt`에 보존했다.

## 수정과 판단 이유

같은 요청 ID를 이미 시작했다면 기존 제어 상태를 반환하고 재시작하지 않는다.
확인과 등록은 하나의 잠금 안에서 수행한다. 따라서 동시에 도착한 중복 요청도
제동 상태를 초기화하지 못한다. 서로 다른 ID는 독립된 요청으로 처리한다.

단순 시간 제한은 늦게 도착한 재요청을 놓칠 수 있어 요청 ID를 기준으로 삼았다.
에이전트에게 반복 호출하지 말라고 지시하는 방법은 입력 빈도를 줄일 수 있지만
서버와 차량 제어의 안전성을 보장하지 못하므로 실행 경계에서 막았다.

## 물리 회귀 검증

| 측정값 | 수정 전 | 수정 후 |
|---|---:|---:|
| 같은 ID의 HTTP 요청 | 2회 | 2회 |
| 제어 시작 | 2회 | 1회 |
| 트럭 간 충돌 센서 이벤트 | 1건 | 0건 |
| 재요청 이후 제동 | 해제 | 유지 |

두 조건은 각각 새 CARLA 서버에서 시작하며 동일 트럭·위치·요청 타이밍·안전 정지
입력을 사용한다. 재요청 전 충돌이나 정지 실패가 있으면 실험을 실패 처리한다.
수정 후에는 30초의 시뮬레이션 시간 동안 제동 유지와 충돌 부재를 확인한다.

`tests/integration/test_duplicate_commit_physical_evidence.py`가 저장된 충돌 기록과
제어 명령을 검사한다. 전체 pytest 결과는 `evidence/pytest_after.txt`에 저장한다.
최종 실행은 **42개 전체 통과**였다.

최종 물리 실행에서 재요청은 frame 167, 충돌은 frame 253에 발생했다.
고정 시간 간격 0.05초 기준 재요청 후 **4.30초**다. 수정 후 최종 속도는
**0.0 m/s**, 두 트럭 중심 간 거리는 **25.29 m**였다. 이 거리는 차체 사이의
빈 공간이 아니라 actor 중심 간 거리다.

## 캡처와 재실행

`evidence_view.html`을 열면 전후 이미지와 JSON 증거 링크를 볼 수 있다.
`-RenderOffScreen`으로 창 없이 렌더링하며 RGB 센서가 이미지를 저장한다.

- 수정 전: `evidence/vulnerable/before_duplicate.png`, `collision.png`, `final.png`.
- 수정 후: `evidence/fixed/before_duplicate.png`, `final.png`.
- 요청과 충돌: 각 조건의 `result.json`.
- tick별 속도·거리·가속·제동: 각 조건의 `telemetry.json`.

```bash
PYTHONPATH=/home/jsy202/carla-0.9.13/PythonAPI/carla/dist/carla-0.9.13-py3.7-linux-x86_64.egg python3.7 experiments/duplicate_commit/run_carla.py --output experiments/duplicate_commit/evidence
DUPLICATE_COMMIT_EVIDENCE=experiments/duplicate_commit/evidence python3 -m pytest -q
```

## 면접 설명 예시

동일한 차량 이송 요청이 반복 전달되는 상황을 검증 시나리오로 설계했습니다.
안전 정지 후 같은 요청이 다시 들어오면 제어가 초기화되는 결함을 구성하고,
pytest로 제동 해제와 중복 시작을 재현했습니다. 실제 CARLA에서도 앞 차량과의
충돌을 센서와 이미지로 확인했습니다. 같은 요청 ID에 대해서는 기존 제어 상태를
유지하도록 수정한 뒤, 같은 요청 두 번에 실행 한 번과 충돌 0건을 확인했습니다.

## 적용 한계

실험 제어기의 요청 기록은 프로세스 메모리에만 있다. 프로세스 재시작을 넘는 중복
방지와 기존 전체 군집 이송 코드 적용은 이 실험에 포함하지 않았다. 충돌 0건은
본 조건의 관측 시간 내 결과이며 모든 주행 조건의 안전성 보장을 뜻하지 않는다.
