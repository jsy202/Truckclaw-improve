# Traceability Matrix — Truckclaw-improve

Requirement → Production code (validation 브랜치 기준 `bridge/platoon_bridge_server.py` 라인) → Test → 결과.

결과 열의 뜻:
- **Baseline**: research-baseline `3a9788f` bridge에서 실행한 결과
- **Current**: validation 브랜치 최종 결과
- 둘 다 실제로 실행한 결과다(`test_report.md` 참조).

| REQ | Production code | Test (TC) | Baseline | Current | Fix commit |
|---|---|---|---|---|---|
| TR-001 차량/platoon 유효성 | `do_POST /transfers` L318–321 | TC-02 `test_rejects_unknown_vehicle_id`, TC-03 `test_rejects_unknown_platoon_id` | XFAIL, XFAIL | PASS, PASS | `d534709` |
| TR-002 명시적 오류 응답 | L301 (non-object body), L374 (`/failed` 404), 각 액션 `else 404` | TC-03, TC-04 `test_rejects_non_object_json_body`, TC-05 `test_failed_unknown_request_returns_error`, TC-23 | XFAIL×3, PASS | PASS×4 | `d534709`, `7189c1c`, `b241214` |
| TR-003 상태 전이 강제 | `ALLOWED_FROM` L26, `_rejects_transition` L261, 각 액션 분기 L333–375 | TC-06 `test_commit_requires_accepted_state`, TC-08, TC-09 `test_completed_transfer_cannot_regress_to_accepted`, TC-20 | XFAIL×3, PASS | PASS×4 | `aee1a82` |
| TR-004 commit 멱등성 | `COMMITTED_OR_LATER_STATUSES` L24, L346 | TC-07 `test_duplicate_commit_does_not_retrigger_carla` | XFAIL | PASS | `bf35524` |
| TR-005 논리 이동은 물리 완료 후 | `_complete_logical_transfer` L136, `carla_complete` 분기 + 전이 가드 | TC-08 `test_carla_complete_requires_valid_state`, TC-01 | XFAIL, PASS | PASS, PASS | `aee1a82` |
| TR-006 HTTP 200 ≠ 완료 | commit 분기 (비동기 trigger) | TC-01 `test_transfer_completes_end_to_end` | PASS | PASS | – (기존 동작 고정) |
| TR-007 trigger 실패 → trigger_failed | `_notify_carla_trigger` except 블록 L211–216 | TC-10 `test_trigger_failure_updates_transfer_state`, TC-13 | XFAIL, FAIL | PASS, PASS | `ee9568a` |
| TR-008 실패 transfer는 platoon 해제 | `ACTIVE_TRANSFER_STATUSES` L22 + TR-007 | TC-11 `test_trigger_failure_does_not_permanently_block_platoon`, TC-15 | XFAIL, PASS | PASS, PASS | `ee9568a` |
| TR-009 무진행 commit timeout | `TRANSFER_TIMEOUT_S` L49, `_start_commit_timer` L220, `_expire_stale_commits` L224 | TC-12 `test_transfer_times_out`, TC-16, TC-19 | XFAIL, FAIL, FAIL | PASS×3 | `a9e643d` |
| TR-010 retry | `retry` 분기, `ALLOWED_FROM["retry"]` | TC-17, TC-19 | FAIL, FAIL | PASS, PASS | `ee9568a`, `a9e643d` (실패 상태 생성이 선행 조건) |
| TR-011 CARLA 실패 보고 | `failed` 분기 | TC-14, TC-15 | PASS, PASS | PASS, PASS | – |
| TR-012 platoon당 active 1건 | `_active_transfer_for` | TC-22 | PASS | PASS | – |
| TR-013 같은 차량 takeover | takeover 로직 (`replaced`) | TC-21 | PASS | PASS | – |
| TR-014 trigger_failed 후 진행 보고 허용 | `ALLOWED_FROM` splitting/merging/carla_complete/failed | TC-18 | FAIL | PASS | `ee9568a` |
| TR-016 timeout 후 지연 진행 보고 허용 | `_timed_out`, `PROGRESS_ACTIONS` L94–95, `_rejects_transition` L264–267, `_start_commit_timer` L222 | TC-35 `test_late_carla_progress_after_timeout_is_accepted`, TC-36 `test_carla_failure_after_retry_of_timed_out_transfer_is_final` | N/A (DEF-11 수정 이후 발생한 회귀) | PASS, PASS | `319b49f` |
| TR-015 MOCK_CARLA 유지 | `_notify_carla_trigger` mock 분기 | TC-24 | PASS | PASS | – |
| DG-001 응답 게이트 | `platoon_dialogue_guard.py` `command_inbound`, `_is_confirmation_only` | TC-26, 27, 30, 31, 32 | PASS | PASS | – (변경 없음) |
| DG-002 후보 검증 | `_chat_candidate`, `command_validate_request` | TC-25, 28, 29, 33, 34 | PASS | PASS | – (변경 없음) |
| TR-P01 기동 중 timeout | – | – | – | DEFERRED | – |
| TR-P02 correlation_id | – | – | – | 미구현 | – |
| TR-P03 /readiness 검증 | – | – | – | 미검증 | – |
| TR-P04 시나리오 ABORT 보고 | – (`scenario/examples/two_platoon_truck_scenario.py`) | – | – | 미검증 (CARLA 필요) | – |

## 결함 → 원인 → 수정 매핑

| DEF | 원인 (코드 기준) | 수정 commit |
|---|---|---|
| DEF-01 | `POST /transfers`가 vehicle 멤버십을 검증하지 않음 | `d534709` |
| DEF-02 | 미존재 platoon에 `_platoons[fp]` KeyError → handler 예외 | `d534709` |
| DEF-08 | `body.get` 호출 전 dict 여부 미검사 | `7189c1c` |
| DEF-07 | `/failed` 분기에 `else 404` 누락 | `b241214` |
| DEF-04 | commit이 매번 상태 덮어쓰기 + trigger | `bf35524` |
| DEF-03, 05, 06 | 모든 액션이 출발 상태 검사 없이 상태 덮어씀 (단일 원인) | `aee1a82` |
| DEF-09, 10 | trigger 실패가 readiness에만 기록, transfer는 committed(active) 유지 (단일 원인) | `ee9568a` |
| DEF-11 | timeout 설정은 있으나 bridge/시나리오 어디서도 사용하지 않음 | `a9e643d` |
| DEF-12 | **이번 검증의 DEF-11 수정이 만든 회귀**: timeout 후 실제 진행 보고를 409로 거부 | 기록 `7ef35b6`, 수정 `319b49f` |
