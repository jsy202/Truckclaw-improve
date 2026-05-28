# State Machine — Transfer (bridge)

상태 이름은 모두 연구 당시 코드/README에 이미 존재하던 것이다. 이번 검증에서 **새 상태는 추가하지 않았다.**
추가된 것은 전이 규칙의 **강제(ALLOWED_FROM)** 와 `trigger_failed`·timeout의 **실제 설정 경로**다.

```text
             accept            commit                splitting      merging       carla_complete
 pending ───────────▶ accepted ───────▶ committed ──────────▶ splitting ───▶ merging ───────────▶ carla_complete
   │  ▲                 │                 │   │                    │             │
   │  └─ (new request for same vehicle → replaced)                 │             │
   │ reject             │ reject          │   │ trigger POST fail  │ failed      │ failed
   ▼                    ▼                 │   ▼                    ▼             ▼
 rejected            rejected             │ trigger_failed ──(late progress allowed)──▶ splitting/merging/carla_complete
                                          │   │ retry
                                          │   └──────────▶ committed
                                          │ no CARLA progress for merge_timeout_s / failed
                                          ▼
                                      merge_failed ──retry──▶ committed
```

## 상태별 정의

| 상태 | Entry condition | 허용 이벤트 → 다음 상태 | 금지 이벤트 (409) | Completion | Timeout | Failure transition | Active? |
|---|---|---|---|---|---|---|---|
| `pending` | `POST /transfers` 성공 | accept → accepted, reject → rejected, 같은 차량 새 요청 → replaced | commit, retry, splitting, merging, carla_complete, failed | – | 없음 | – | ✔ |
| `accepted` | accept | commit → committed, reject → rejected, 같은 차량 새 요청 → replaced | accept, retry, splitting, merging, carla_complete, failed | – | 없음 | – | ✔ |
| `committed` | commit / retry | splitting, merging, carla_complete, failed, retry(재trigger) | accept, reject | – | **merge_timeout_s (120 s)** 동안 진행 보고 없으면 → merge_failed | trigger 실패 → trigger_failed | ✔ |
| `splitting` | CARLA `/splitting` | merging, carla_complete, failed | accept, reject, commit(멱등, 무변화), retry | – | 없음 (DEFERRED) | failed → merge_failed | ✔ |
| `merging` | CARLA `/merging` | carla_complete, failed | accept, reject, commit(멱등), retry, splitting | – | 없음 (DEFERRED) | failed → merge_failed | ✔ |
| `carla_complete` | CARLA `/carla_complete` | – (terminal) | 모든 액션 (commit은 멱등 200) | 논리 멤버십 이동 완료 | – | – | ✘ |
| `trigger_failed` | trigger POST 실패 시 아직 committed였던 transfer | retry → committed, splitting / merging / carla_complete / failed (지연 도착한 실제 진행 보고) | accept, reject, commit | – | 없음 | – | ✘ |
| `merge_failed` | CARLA `/failed` 또는 commit timeout | retry → committed. **timeout으로 생긴 경우에만** splitting / merging / carla_complete / failed 1회 허용(지연 도착한 실제 진행, DEF-12) | 그 외 전부 | – | – | – | ✘ |
| `rejected` | reject | – (terminal) | 전부 | – | – | – | ✘ |
| `replaced` | 같은 차량에 새 요청 생성 | – (terminal) | 전부 | – | – | – | ✘ |

"Active"는 `ACTIVE_TRANSFER_STATUSES`(platoon 점유 여부)이다. 실패·종료 상태는 platoon을 점유하지 않는다.

## 연구 당시(baseline)와의 차이

| 항목 | baseline `3a9788f` | validation |
|---|---|---|
| 전이 규칙 | README에 순서만 기술, 코드는 모든 액션이 무조건 상태 덮어씀 | `ALLOWED_FROM`로 강제, 위반 시 409 |
| `trigger_failed` | README에만 존재, 설정하는 코드 없음 | trigger 실패 시 설정 |
| timeout | 설정값(`merge_timeout_s`)만 존재, 미사용 | committed 상태에 적용 |
| 중복 commit | 매번 재trigger | 멱등 |

## 시나리오 측 상태 (참고, B: 정적 분석)

`two_platoon_truck_scenario.py`의 `TransferState = CRUISE, GAP, LC, FOLLOW, DONE, ABORT`.

- `try_start`는 CRUISE에서 갭/인접 조건이 맞으면 bridge에 `/splitting`, `/merging`을 연속 보고하고 LC로 전이한다.
- `finalize_join`에서 `/carla_complete`를 보고하고 DONE으로 전이한다.
- `GAP`, `FOLLOW`, `ABORT` 상태로 전이하는 코드는 없다(`FOLLOW`는 `update()`에서 비교만 됨). `MERGE_TIMEOUT_S = 400.0`도 정의만 있고 사용되지 않는다. 즉 물리 측에서 실패를 bridge에 보고하는 경로(`/failed`)가 시나리오에는 없다 → REQ-TR-P04.
- 시나리오의 bridge 호출(`_bridge_post`)은 예외를 삼키는 fire-and-forget이다. 그래서 `carla_complete`는 `committed`에서도 허용된다.
- 이 부분은 CARLA가 필요해 이번 검증에서 실행하지 않았다.
