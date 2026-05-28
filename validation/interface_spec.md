# Interface Specification — Platoon Bridge (port 18801)

구현: `bridge/platoon_bridge_server.py`. 이 문서는 validation 브랜치의 현재 동작을 기술한다.
연구 당시(research-baseline `3a9788f`)와 달라진 부분은 **[changed]** 로 표시했다.

## 공통

- Content-Type: `application/json`
- 오류 응답 형식: `{"error": "<message>"}`
- **HTTP 200은 요청 처리 완료를 뜻할 뿐 물리 이송 완료가 아니다.** 이송 완료는 transfer `status == "carla_complete"` 로만 판단한다.
- 모든 요청 처리 시작 시 commit timeout 만료 검사가 실행된다(lazy expiry) **[changed]**.

## 상태 조회 (GET)

| Path | 응답 | 상태 코드 |
|---|---|---|
| `/health` | `{"ok": true}` | 200 |
| `/snapshot` | `{"platoons", "transfers", "readiness"}` | 200 |
| `/readiness` | readiness 객체 | 200 |
| `/transfers/{request_id}` | transfer 객체 | 200 / 404 |
| `/platoons/{platoon_id}` | platoon 객체 (없으면 `{}`) | 200 |
| `/platoons/{platoon_id}/transfer-candidates` | `{"candidates": [{vehicle_id, target_platoon_id, requires_split}]}` | 200 |

## Transfer 생성 — `POST /transfers`

| 필드 | 필수 | 설명 |
|---|---|---|
| `vehicle_id` | ✔ | `from_platoon_id`의 멤버여야 함 **[changed]** |
| `from_platoon_id` | ✔ | 존재해야 함 **[changed]** |
| `to_platoon_id` | ✔ | 존재해야 함 **[changed]** |
| `reason`, `sender_agent`, `receiver_agent` | – | 수신하지만 저장하지 않음 (baseline과 동일) |

| 결과 | 코드 |
|---|---|
| 생성됨 (`status: pending`, `request_id: tr_xxxxxxxx`, `requires_split`) | 200 |
| JSON 파싱 실패 | 400 `bad json` |
| JSON이 객체가 아님 | 400 `json body must be an object` **[changed]** (baseline: 연결 끊김) |
| 필수 필드 누락 | 400 `missing fields` |
| 알 수 없는 platoon | 404 `unknown platoon` **[changed]** (baseline: 연결 끊김) |
| 차량이 from platoon 멤버 아님 | 404 **[changed]** (baseline: 200 생성) |
| 해당 platoon에 다른 active transfer 존재 | 409 |

동일 차량의 pending/accepted 요청이 있으면 그 요청은 `replaced`가 되고 새 요청이 생성된다.

## Transfer 액션 — `POST /transfers/{request_id}/{action}`

| action | 호출 주체 | 허용 출발 상태 **[changed]** | 결과 상태 | 부수 효과 |
|---|---|---|---|---|
| `accept` | 수신 platoon agent | pending | accepted | – |
| `reject` | 수신 platoon agent | pending, accepted | rejected | – |
| `commit` | 수신 platoon agent | accepted | committed | CARLA trigger 1회, commit timer 시작 |
| `commit` (반복) | – | committed, splitting, merging, carla_complete | (변화 없음) | **재trigger 없음, 현재 상태 200 반환** [changed] |
| `retry` | 운영자 | committed, trigger_failed, merge_failed | committed | CARLA trigger, commit timer 재시작 |
| `splitting` | CARLA 시나리오 | committed, trigger_failed | splitting | – |
| `merging` | CARLA 시나리오 | committed, splitting, trigger_failed | merging | – |
| `carla_complete` | CARLA 시나리오 | committed, splitting, merging, trigger_failed | carla_complete | **논리 멤버십 이동** |
| `failed` | CARLA 시나리오 | committed, splitting, merging, trigger_failed | merge_failed | `reason` 저장 |

**예외 [changed]:** commit timeout으로 `merge_failed`가 된 transfer에는 진행 액션(`splitting`/`merging`/`carla_complete`/`failed`)이 1회 허용된다. 실제 물리 진행이 timeout보다 늦게 시작된 경우이며, 이 경우 transfer는 재개된다(DEF-12). CARLA가 `/failed`로 보고한 `merge_failed`는 최종 상태다.

| 결과 | 코드 |
|---|---|
| 성공 | 200 + transfer 객체 |
| 알 수 없는 request_id | 404 (`/failed` 포함 **[changed]**, baseline: `/failed`는 연결 끊김) |
| 허용되지 않은 전이 | 409 `cannot <action> transfer in status <status>` **[changed]** (baseline: 무조건 덮어씀) |

## 기타 POST

| Path | 동작 |
|---|---|
| `/readiness` | body를 readiness에 병합 (검증 없음 — REQ-TR-P03) |
| `/reload` | 설정 파일에서 platoon 재로딩, transfers/readiness/commit timer 초기화 |

## Bridge → CARLA 시나리오 계약 (outbound)

| 항목 | 값 |
|---|---|
| URL | `CARLA_TRIGGER_URL` (기본 `http://127.0.0.1:18802/start_merge`) |
| Method / Body | `POST {"request_id": "<rid>"}` |
| Timeout | 2 s |
| 실패 판정 | 연결 실패, timeout, non-2xx → transfer가 아직 `committed`면 `trigger_failed` **[changed]** |

참고(B): 실제 시나리오(`two_platoon_truck_scenario.py`)는 trigger body를 사용하지 않고 `GET /snapshot`에서 `committed`/`merging` transfer를 polling해 시작한다. trigger는 로그용 이벤트에 가깝다. 이 때문에 `trigger_failed` 이후의 진행 보고도 허용한다(REQ-TR-014).

## 시간 제한

| 항목 | 값 | 출처 |
|---|---|---|
| `TRANSFER_TIMEOUT_S` | `config/simulation.json` `timeouts.merge_timeout_s` (120 s), 파일 없으면 120 s | 기존 설정 재사용 **[changed]** |
| 적용 범위 | `committed` 상태에서 CARLA 진행 보고가 없을 때만 | – |
| 만료 결과 | `merge_failed`, `reason: "timeout: no CARLA progress within …"` | – |
| 만료 후 | 늦게 도착한 CARLA 진행 보고는 허용되어 transfer 재개 | DEF-12 |

docker-compose의 bridge 컨테이너는 `./bridge`만 마운트하므로 기본값 120 s가 사용된다(설정값과 동일).
