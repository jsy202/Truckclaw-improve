# Limitations — Truckclaw-improve Validation

## 검증하지 못한 범위

| 항목 | 이유 | 영향 |
|---|---|---|
| CARLA 물리 시나리오 (갭 확보, 차선 변경, CACC 합류) | CARLA 미실행. 이번 검증은 bridge와 HTTP 계약까지만 다룸 | 물리 동작의 정확성, 실제 기동 시간은 검증되지 않음 |
| 수정된 bridge + 실제 시나리오 조합 | CARLA 필요 | 아래 "수정에 따른 동작 변화"가 실제 데모에 영향을 주는지 미확인 |
| OpenClaw 에이전트(LLM)의 협상 행동 | 외부 LLM·Discord 필요 | 에이전트가 SKILL.md 절차를 지키는지는 검증 범위 밖. 결정적 guard와 bridge 계약만 검증 |
| docker-compose 배포 | 미실행 | 컨테이너 환경의 설정 파일 마운트 등은 정적 확인만(B) |
| GitHub Actions 실제 실행 | push 안 함 | workflow는 로컬에서 동일 명령으로만 확인 |

## Fake의 충실도 한계

`FakeCarlaScenario`는 trigger를 받으면 곧바로 진행 보고를 보낸다. 실제 시나리오는 trigger를 무시하고, `/snapshot`을 polling하다가 갭과 인접 조건이 맞을 때 시작한다(B). 따라서 다음은 Fake로 재현되지 않는다.

- polling 타이밍
- 여러 transfer가 있을 때 `created_at` 순서로 선택하는 동작
- 시나리오의 fire-and-forget 보고가 유실되는 경우

## 수정에 따른 동작 변화 (실제 데모에서 확인 필요)

| 변화 | 연구 당시 | 현재 | 위험 |
|---|---|---|---|
| commit 없이 진행 보고 | 허용 | 409 | 시나리오는 committed/merging 상태만 집어 가므로 영향 없을 것으로 판단(B) |
| 키보드 1–4 수동 trigger (`_auto_bridge_commit`) | request→accept→commit | 동일 경로 허용 | 해당 차량이 from platoon 멤버가 아니면 404 (예: 이미 이동한 차량을 다시 선택) — 이전엔 200으로 생성되던 경우 |
| 진행 보고 없는 commit | 무한 대기 | 120 s 후 merge_failed, 이후 실제 진행 보고가 오면 재개(DEF-12) | timeout 시점에 platoon이 해제된다. 그래서 갭 정렬이 120 s를 넘기면, 그사이 같은 platoon에 새 transfer가 생성될 수 있다. 이후 늦은 진행 보고로 이전 transfer가 재개되면 같은 platoon에 active transfer가 2개가 될 수 있다(테스트하지 않음). **실제 갭 정렬 시간은 측정되지 않았다.** |
| trigger 실패 | committed 유지 | trigger_failed (진행 보고는 계속 허용) | 시나리오는 committed만 새로 집어 가므로, trigger 서버가 꺼져 있는 상태에서 commit되면 시나리오가 그 transfer를 시작하지 않는다. 연구 당시에는 시나리오가 나중에 시작해도 `/reload`로 transfer가 지워졌으므로 실질 차이는 작다고 판단(B) |
| **일시적** trigger 실패 (시나리오는 실행 중, POST만 실패) | 시나리오가 `/snapshot` polling으로 committed transfer를 가져가 **정상 진행** | `trigger_failed`가 되어 시나리오가 가져가지 않음 → **`/retry` 필요** | **이번 수정에 따른 동작 후퇴 가능성(B).** 시나리오의 trigger 수신부가 별도 스레드여서 실행 중에 POST가 실패할 가능성은 낮다고 보지만, 측정하지는 않았다 |
| commit timeout 이후 시나리오 동작 | – | 시나리오는 CRUISE에서 매 tick마다 `committed`/`merging` transfer를 다시 조회한다. 그래서 timeout(`merge_failed`) 뒤에는 그 transfer를 **조용히 포기**한다. 그 사이 `_set_follow_gap`으로 넓힌 차간 거리는 되돌리지 않는다 | 정적 분석(B), CARLA에서 미확인 |

## DEF-12에 대한 정정 (최종 검수에서 추가)

DEF-12는 "timeout 뒤에 실제 진행 보고가 늦게 도착한다"는 상황이다. 이것은 FakeCarlaScenario의 동작 모델에서 재현했다. Fake는 trigger를 받으면 transfer 상태와 상관없이 진행 보고를 보낸다.

실제 시나리오는 매 tick 상태를 다시 읽고 `committed`일 때만 split을 시작한다(B). 그래서 실제로 늦은 보고가 생기는 경우는, 시나리오가 상태를 읽은 직후부터 `/splitting`을 보내기 전까지(같은 함수 호출 안)의 짧은 경쟁 구간에 timeout이 걸릴 때로 한정된다. DEF-12 수정은 이 경우에도 해가 없지만, 실제 영향은 Fake로 보인 것보다 작다. **테스트와 Fake가 같은 가정을 공유한 사례**로 기록한다.

## DEFERRED

| 항목 | 이유 |
|---|---|
| splitting/merging 단계 timeout | 실제 기동 시간이 측정되지 않았고, 시나리오에 abort/`/failed` 보고 경로가 없다. bridge만 timeout시키면 논리/물리 상태가 어긋날 수 있다 |
| 시나리오 `ABORT`/`MERGE_TIMEOUT_S` 활성화 | CARLA 물리 코드 수정이 필요하고 CARLA 없이 검증할 수 없음 |
| Agent→bridge `correlation_id`, structured logging | 기존 로그 형식(print)을 바꾸는 변경이라 이번 범위에서 제외. 현재는 `request_id`로 bridge↔CARLA 구간만 추적 가능 |
| `POST /readiness` 입력 검증 | 재현된 결함이 아니므로 수정하지 않음 |
| 경로 매칭이 substring 기반(`"/accept" in p`) | 재현된 결함 없음. 수정하지 않음 |

## 동시성

bridge는 `HTTPServer`(단일 스레드)와 전역 `_lock`을 사용한다. 동시 요청 경합 테스트는 수행하지 않았다.
