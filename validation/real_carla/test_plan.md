# Real-CARLA Re-validation — Test Plan (Post-project Validation)

FakeCarlaScenario integration test(`tests/`)와 **별개로**, 수정된 bridge(validation 브랜치)를 **실제 CARLA 시뮬레이터와 기존 시나리오**로 재검증한다.

## 환경

| 항목 | 값 |
|---|---|
| CARLA | 0.9.13 패키지 (`~/carla-0.9.13`), `-RenderOffScreen -quality-level=Low`, **run마다 서버 새로 기동** |
| GPU / CPU / RAM | NVIDIA RTX 3060 8 GB / AMD Ryzen 5 5500GT / 15 GB |
| Scenario client | Python 3.7.17 + CARLA 0.9.13 egg (`PythonAPI/carla/dist`, PYTHONPATH로 지정, 설치 없음) |
| Bridge / 도구 | Python 3.10.12 |
| 시나리오 | 기존 `scenario/examples/two_platoon_truck_scenario.py` (Town06, 동기 모드 dt = 0.01) |
| 요청 경로 | 기존 `tools/openclaw_negotiation_harness.py` (A), 같은 bridge REST 계약 (B, C) |
| OpenClaw / Discord | 사용 안 함. agent 대신 harness가 같은 REST 호출을 수행 |

## 실행 환경 때문에 필요했던 변경 (1건)

CARLA 0.9.13에는 시나리오가 하드코딩한 `vehicle.carlamotors.european_hgv`가 없다. 그래서 Truckclaw_movable/copyable에 이미 있던 blueprint fallback을 같은 순서로 적용했다(`7285207`). 실제 사용된 차량은 **`vehicle.carlamotors.carlacola`** 이고, 차량 크기와 동역학이 european_hgv와 다르다.

## 측정 방법

`validation/real_carla/tools/run_real_carla.py`가 run마다 다음 순서로 진행한다.

1. CARLA 서버 기동
2. 시나리오 기동(bridge `/reload` 포함)
3. 워밍업 5 s
4. 요청 수행
5. `/snapshot`을 0.2 s 간격으로 polling하며 상태 전이 시각(wall clock) 기록
6. 최종 상태에 도달하면 8 s 후 CARLA에서 6대 차량의 물리 위치와 차선 조회(`phys_snapshot.py`, 읽기 전용)
7. bridge 논리 멤버십과 비교
8. bridge 로그의 "CARLA trigger sent"와 시나리오 로그의 "LC started" / "JOIN COMPLETE" 개수 집계

**물리 일치 판정**(이송 완료 시): truck1의 차선이 platoon B 3대의 차선과 같고 platoon A의 차선과 다르며, b2 뒤 0~40 m에 있어야 한다.

## 테스트

| ID | 시나리오 | 절차 | 반복 |
|---|---|---|---|
| RC-A | Normal Transfer | harness: request → accept → commit → 완료까지 대기 | 10 |
| RC-B | Duplicate commit | request → accept → **commit ×3**(같은 request_id, 0.3 s 간격) | 현재 bridge 5회 + **research-baseline bridge 3회**(비교) |
| RC-C | Failure / Recovery | trigger 경로를 fault proxy가 503으로 실패시킴 → 상태 확인 → 같은 차량 새 요청 → proxy 정상화 → accept/commit → 완료 | 현재 bridge 5회 + **research-baseline bridge 3회**(비교) |

fault proxy(`tools/fault_proxy.py`)는 bridge와 시나리오 trigger 수신부(:18802) 사이에만 있다. 시나리오와 bridge 코드는 바꾸지 않는다.

## 측정 항목

`raw_results.csv` 열:
- 최종 상태, 성공 여부
- request → commit, commit → 물리 시작(splitting 또는 merging 중 먼저 관측된 시각), commit → carla_complete, request → carla_complete (wall clock)
- commit 요청 수, CARLA trigger 전송 수, trigger 실패 로그 수, 물리 split 시작 수, join 수
- 논리 멤버십(A, B), 물리 일치 판정과 근거
- 회복 시 새 요청의 HTTP 상태

## 범위 밖

- OpenClaw LLM agent, Discord
- `european_hgv` 차량
- 다른 spawn 위치와 속도 조건
- 화면 렌더링(offscreen)
