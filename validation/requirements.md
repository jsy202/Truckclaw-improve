# Requirements — Truckclaw-improve (Post-project Validation)

> 이 문서는 연구 종료 후 수행한 검증 작업의 산출물이다.
> 연구 당시 작성된 요구사항 문서는 존재하지 않으며, 아래 요구사항은 **현재 코드·README에서 근거를 찾아 역으로 정리**한 것이다.

## 출처 구분

| 구분 | 의미 |
|---|---|
| **Existing** | 연구 당시 README/코드에 이미 명시된 동작 또는 의도 |
| **Derived** | 명시되진 않았지만 기존 설계(상태 머신, API 구조)로부터 논리적으로 도출되는 요구사항 |
| **Proposed** | 이번 검증에서 새로 제안. 구현/검증되지 않았으면 그렇게 표시 |

## 증거 등급

| 등급 | 의미 |
|---|---|
| A | 실제 실행(자동화 테스트)으로 확인 |
| B | 코드 정적 분석으로만 확인 |
| C | 제안 / 미검증 |

## Transfer (bridge)

| ID | 요구사항 | 출처 | 근거 | 검증 상태 |
|---|---|---|---|---|
| REQ-TR-001 | Transfer는 존재하는 두 platoon 사이에서, `from_platoon_id`의 멤버인 `vehicle_id`에 대해서만 생성되어야 한다. | Derived | 시나리오가 `from` platoon 안에서 차량 인덱스를 찾음(`two_platoon_truck_scenario.py` `try_start`) | A |
| REQ-TR-002 | 잘못된 입력·알 수 없는 ID는 명시적 HTTP 4xx + JSON `error`로 응답해야 하며, 응답 없이 연결이 끊겨서는 안 된다. | Derived | 다른 엔드포인트는 이미 `_err(404)`/`_err(400)` 사용 | A |
| REQ-TR-003 | Transfer 상태는 `pending → accepted → committed → splitting → merging → carla_complete` 순서를 따라야 하며, 허용되지 않은 전이는 거부(409)되어야 한다. | Existing | README "이송 상태 머신" | A |
| REQ-TR-004 | 동일 `request_id`에 대한 물리 실행(CARLA trigger)은 최대 1회여야 한다(commit 멱등성). | Derived | 하나의 request_id = 하나의 물리 이송 | A |
| REQ-TR-005 | 논리적 멤버십 이동은 물리 합류 완료 보고(`carla_complete`) 이후에만, 진행 중 상태에서만 일어나야 한다. | Existing | README "7. 브리지 서버에 carla_complete 보고 및 논리적 멤버십 이동" | A |
| REQ-TR-006 | commit에 대한 HTTP 200은 "실행 접수"를 의미하며 이송 완료를 의미하지 않는다. 완료 판단은 transfer `status`로 한다. | Derived | commit 이후 비동기 trigger + 진행 보고 구조 | A |
| REQ-TR-007 | CARLA trigger 호출 실패(연결 실패·timeout·non-2xx) 시 transfer는 `trigger_failed`가 되어야 한다. | Existing | README "trigger_failed : 브리지가 CARLA 트리거 서버 호출 실패" | A |
| REQ-TR-008 | 실패한 transfer(`trigger_failed`, `merge_failed`)는 platoon을 점유하지 않아야 하며 새 요청이 가능해야 한다. | Derived | `ACTIVE_TRANSFER_STATUSES`에 실패 상태 미포함 | A |
| REQ-TR-009 | CARLA 진행 보고가 전혀 없는 committed transfer는 `merge_timeout_s` 후 `merge_failed`(reason: timeout)가 되어야 한다. | Existing | README "merge_failed : CARLA 물리 합류 실패 또는 타임아웃", `config/simulation.json` `timeouts.merge_timeout_s` | A |
| REQ-TR-010 | 실패한 transfer는 `/retry`로 재실행할 수 있어야 한다. | Existing | `/retry` 엔드포인트 | A |
| REQ-TR-011 | CARLA 측 실패 보고(`/failed`) 시 `merge_failed`가 되고 멤버십은 변하지 않아야 한다(부분 실패 포함). | Existing | `/failed` 엔드포인트, README | A |
| REQ-TR-012 | 한 platoon에는 동시에 하나의 active transfer만 존재해야 한다. | Existing | `_active_transfer_for` → 409 | A |
| REQ-TR-013 | 같은 차량의 새 요청은 pending/accepted 상태의 이전 요청을 `replaced`로 대체한다. | Existing | takeover 로직 | A |
| REQ-TR-014 | `trigger_failed`는 "전달 미확인"이므로, 이후 도착하는 실제 CARLA 진행 보고는 거부하지 않는다. | Derived (이번 검증의 설계 결정) | 시나리오는 trigger가 아닌 `/snapshot` polling으로 시작 | A |
| REQ-TR-016 | commit timeout으로 실패한 transfer라도 이후 도착한 실제 CARLA 진행 보고는 받아들여야 한다. 단 CARLA가 직접 보고한 실패는 최종이다. | Derived (DEF-12) | 시나리오는 갭 정렬 후에야 `/splitting`을 보고 | A |
| REQ-TR-015 | `MOCK_CARLA=true` 모드는 계속 동작해야 한다. | Existing | README "Mock CARLA 모드" | A |

## Dialogue guard (agent 대화 게이트)

| ID | 요구사항 | 출처 | 검증 상태 |
|---|---|---|---|
| REQ-DG-001 | 에이전트는 자신이 멘션되고 실행 가능한 내용이 있을 때만 응답한다. 확인/대기 같은 단순 응답은 차단해 ACK 루프를 막는다. | Existing (guard docstring) | A |
| REQ-DG-002 | 대화에서 교환된 목적지 목록 기준으로 목적지가 맞는 follower만 이송 후보가 되며 리더(truck0)는 제외된다. | Existing | A |

## Proposed (미구현 / 미검증)

| ID | 요구사항 | 상태 |
|---|---|---|
| REQ-TR-P01 | splitting/merging 단계(물리 기동 중)에도 상한 시간이 있어야 한다. | **DEFERRED** — 실제 기동 시간이 CARLA 없이 측정되지 않았고, 시나리오에 abort 경로가 없어 bridge만 timeout 시 논리/물리 불일치 위험 |
| REQ-TR-P02 | Agent → bridge 요청에 클라이언트 `correlation_id`를 실어 Agent 로그와 bridge 상태를 연결한다. | C — 미구현. 현재 `request_id`는 bridge에서 생성되어 bridge→CARLA→bridge 구간만 추적 가능(B) |
| REQ-TR-P03 | `POST /readiness`는 임의 필드 덮어쓰기를 허용하지 않아야 한다. | C — 미검증 |
| REQ-TR-P04 | 시나리오의 `TransferState.ABORT`/`MERGE_TIMEOUT_S`가 실제로 사용되어 물리 측 실패를 bridge에 보고해야 한다. | C — 현재 미사용(B). CARLA 필요 |
