# Test Cases — Truckclaw-improve

모든 테스트는 CARLA·OpenClaw·Discord 없이 실행된다.

- 실제 bridge `Handler`를 프로세스 안에서 띄운다.
- CARLA 측은 `FakeCarlaScenario`(HTTP 계약 구현)로 대체한다.
- 실행: `python3 -m pytest`

Fake 모드: `complete`(splitting→merging→carla_complete), `silent`(무응답), `fail`(/failed), `partial`(splitting→merging→failed), `bad_response`(trigger에 500).
CARLA 다운은 `unreachable_trigger` fixture(아무것도 listen하지 않는 포트)로 표현한다.

"Baseline" 열은 같은 테스트를 research-baseline(`3a9788f`) bridge에서 실행한 결과다(실제 실행).

## Integration — happy path (`tests/integration/test_transfer_happy_path.py`)

| TC | 테스트 | 절차 / 기대 결과 | REQ | Baseline |
|---|---|---|---|---|
| TC-01 | `test_transfer_completes_end_to_end` | 후보 조회 → request → accept → commit(Fake hold) 시 200이지만 멤버십 불변 → release → carla_complete → truck1이 B 꼬리, trigger 1회(request_id 포함), 진행 보고 3건 200 | TR-003, 005, 006 | PASS |

## Integration — 결함 회귀 (`tests/integration/test_transfer_defects.py`)

| TC | DEF | 테스트 | 입력 | 기대 결과 | REQ | Baseline |
|---|---|---|---|---|---|---|
| TC-02 | DEF-01 | `test_rejects_unknown_vehicle_id` | vehicle `ghost_truck9` | 400/404, transfer 미생성 | TR-001 | XFAIL (200 pending) |
| TC-03 | DEF-02 | `test_rejects_unknown_platoon_id` | from `platoon_x` | 400/404 + error | TR-001, 002 | XFAIL (연결 끊김) |
| TC-04 | DEF-08 | `test_rejects_non_object_json_body` | body `[1,2]` | 400 | TR-002 | XFAIL (연결 끊김) |
| TC-05 | DEF-07 | `test_failed_unknown_request_returns_error` | `/transfers/tr_doesnotexist/failed` | 404 | TR-002 | XFAIL (연결 끊김) |
| TC-06 | DEF-03 | `test_commit_requires_accepted_state` | pending에서 commit | 409, pending 유지, trigger 0회 | TR-003 | XFAIL (200) |
| TC-07 | DEF-04 | `test_duplicate_commit_does_not_retrigger_carla` | commit 2회 | 두 번째 200 + committed, trigger 1회 | TR-004 | XFAIL (trigger 2회) |
| TC-08 | DEF-05 | `test_carla_complete_requires_valid_state` | pending에서 carla_complete | 409, 멤버십 불변 | TR-003, 005 | XFAIL (200, 멤버십 이동) |
| TC-09 | DEF-06 | `test_completed_transfer_cannot_regress_to_accepted` | 완료 후 accept | 409, carla_complete 유지 | TR-003 | XFAIL (accepted로 역행) |
| TC-10 | DEF-09 | `test_trigger_failure_updates_transfer_state` | trigger 대상 다운 | `trigger_failed` | TR-007 | XFAIL (committed 유지) |
| TC-11 | DEF-10 | `test_trigger_failure_does_not_permanently_block_platoon` | trigger 실패 후 같은 platoon 새 요청 | 200 | TR-008 | XFAIL (409 지속) |
| TC-12 | DEF-11 | `test_transfer_times_out` | Fake silent, timeout 0.5 s | `merge_failed`, reason "timeout…" | TR-009 | XFAIL (committed 지속) |
| TC-35 | DEF-12 | `test_late_carla_progress_after_timeout_is_accepted` | timeout 후 splitting/merging/carla_complete 보고 | 모두 200, 멤버십 이동 | TR-016 | N/A — DEF-11 수정(`a9e643d`) 이후 XFAIL(409), `319b49f`에서 PASS |

## Integration — 의존성 장애 / 회복 / 기존 동작 보존 (`tests/integration/test_transfer_recovery.py`)

| TC | 테스트 | 시나리오 | 기대 결과 | REQ | Baseline |
|---|---|---|---|---|---|
| TC-13 | `test_trigger_non_2xx_response_marks_trigger_failed` | trigger가 500 응답 | trigger_failed, reason에 500, 멤버십 불변 | TR-007 | FAIL |
| TC-14 | `test_carla_failure_report_marks_merge_failed_and_keeps_membership` | CARLA /failed | merge_failed, 멤버십 불변 | TR-011 | PASS |
| TC-15 | `test_partial_failure_after_split_keeps_membership_and_releases_platoons` | splitting→merging→failed | merge_failed, 멤버십 불변, 새 요청 200 | TR-008, 011 | PASS |
| TC-16 | `test_delayed_progress_within_timeout_is_not_timed_out` | 단계 간 0.3 s 지연, timeout 0.5 s | carla_complete (진행 중이면 timeout 없음) | TR-009 | FAIL (속성 없음) |
| TC-17 | `test_retry_after_trigger_failure_completes_transfer` | trigger 실패 → CARLA 복구 → retry | carla_complete, trigger 1회 | TR-010 | FAIL |
| TC-18 | `test_late_carla_progress_after_trigger_failure_is_accepted` | trigger 실패 후 실제 진행 보고 도착 | carla_complete | TR-014 | FAIL |
| TC-19 | `test_timed_out_transfer_can_be_retried` | timeout → retry | carla_complete | TR-009, 010 | FAIL |
| TC-20 | `test_reject_from_accepted_is_allowed` | accepted에서 reject | 200 rejected | TR-003 | PASS |
| TC-21 | `test_new_request_replaces_pending_request_for_same_vehicle` | 같은 차량 요청 2회 | 첫 요청 replaced | TR-013 | PASS |
| TC-22 | `test_second_transfer_on_busy_platoon_is_rejected` | 진행 중 platoon에 새 요청 | 409 | TR-012 | PASS |
| TC-23 | `test_unknown_request_id_on_action_returns_404` | 7개 액션에 미존재 id | 404 | TR-002 | PASS |
| TC-24 | `test_existing_mock_carla_mode_still_completes` | `MOCK_MODE=True` | carla_complete | TR-015 | PASS |
| TC-36 | `test_carla_failure_after_retry_of_timed_out_transfer_is_final` | timeout → retry → CARLA /failed → carla_complete 시도 | 409 (CARLA 실패는 최종) | TR-016 | N/A (timeout 없음) |

## Unit — dialogue guard (`tests/unit/test_dialogue_guard.py`)

| TC | 테스트 | REQ | Baseline |
|---|---|---|---|
| TC-25 | `test_extracts_vehicle_destinations_from_chat_text` | DG-002 | PASS |
| TC-26 | `test_confirmation_only_message_is_detected` | DG-001 | PASS |
| TC-27 | `test_message_with_machine_update_is_not_confirmation_only` | DG-001 | PASS |
| TC-28 | `test_chat_candidate_is_destination_mismatched_follower` | DG-002 | PASS |
| TC-29 | `test_chat_candidate_never_selects_leader_truck0` | DG-002 | PASS |
| TC-30 | `test_inbound_without_own_mention_is_blocked` | DG-001 | PASS |
| TC-31 | `test_inbound_ack_loop_is_blocked` | DG-001 | PASS |
| TC-32 | `test_inbound_actionable_mention_is_allowed` | DG-001 | PASS |
| TC-33 | `test_validate_request_rejects_vehicle_not_in_chat_candidates` | DG-002 | PASS |
| TC-34 | `test_validate_request_accepts_destination_compatible_vehicle` | DG-002 | PASS |

## 자동화 대상이 아닌 테스트 (CARLA 필요, 미실행)

| ID | 내용 | 상태 |
|---|---|---|
| ST-01 | 실제 CARLA Town06에서 이중 갭 확보 → 차선 변경 → 합류 → `carla_complete` 보고 | 이번 검증에서 미실행 |
| ST-02 | 실제 OpenClaw 두 봇의 Discord 협상 → commit | 이번 검증에서 미실행 |
