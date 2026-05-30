# Test Report — Truckclaw-improve (Post-project Validation)

> **이 보고서는 연구 종료 후(2026-10-01) 수행한 검증 결과다.** 연구 당시의 CARLA 데모 결과와 무관하다.
> 연구 당시 결과(실제 CARLA 합류 시연)는 이번에 재실행하지 않았다.

## 1. 실행 환경

| 항목 | 값 |
|---|---|
| OS | Linux 6.8.0 (Ubuntu 계열) |
| Python | 3.10.12 |
| pytest | 8.4.2 |
| CARLA / OpenClaw / Discord | **사용하지 않음** (FakeCarlaScenario로 대체) |
| 대상 | branch `validation`, baseline tag `research-baseline` = `3a9788f` |

## 2. 테스트 구조

```text
pytest client ──HTTP──▶ Bridge Handler (실제 production 코드, in-process, 임의 포트)
                              │ POST {request_id}  (CARLA_TRIGGER_URL → Fake로 지정)
                              ▼
                        FakeCarlaScenario ──POST /transfers/<rid>/splitting|merging|carla_complete|failed──▶ Bridge
```

- production 코드에 테스트용 분기를 추가하지 않았다.
- 테스트는 기존 `CARLA_TRIGGER_URL`과 기존 `/reload`만 사용한다.

## 3. 결과 요약 (최종 HEAD)

| 구분 | 수 |
|---|---|
| 전체 테스트 | 36 |
| PASS | 36 |
| XFAIL | 0 |
| FAILED | 0 |

명령: `python3 -m pytest -v` → `36 passed in 13.36s` (코드 기준 `319b49f`, `evidence/pytest_verbose.txt`)

## 4. 결함 발견 → 수정 이력 (git history로 검증 가능)

| 단계 | commit | 결과 |
|---|---|---|
| 테스트 인프라 + happy path | `8cd48b2` | 1 passed |
| 결함 11건 strict xfail 기록 (production 변경 0) | `53dafd0` | 1 passed, 11 xfailed |
| DEF-01, 02 수정 | `d534709` | 3 passed, 9 xfailed |
| DEF-08 수정 | `7189c1c` | 4 passed, 8 xfailed |
| DEF-07 수정 | `b241214` | 5 passed, 7 xfailed |
| DEF-04 수정 | `bf35524` | 6 passed, 6 xfailed |
| DEF-03, 05, 06 수정 | `aee1a82` | 9 passed, 3 xfailed |
| DEF-09, 10 수정 | `ee9568a` | 11 passed, 1 xfailed |
| DEF-11 수정 | `a9e643d` | 12 passed |
| 장애/회복/unit 테스트 22건 추가 | `1a5b24b` | 34 passed |
| CI workflow | `666fa8b` | – |
| DEF-12 기록: DEF-11 수정이 만든 회귀 (문서 작성 중 발견) | `7ef35b6` | 34 passed, 1 xfailed |
| DEF-12 수정 + retry 경계 테스트 | `319b49f` | 36 passed |

`53dafd0` 시점에 `pytest --runxfail`로 xfail 표시를 무시하고 실행했다. 11건 모두 결함을 검사하는 첫 assert에서 실패했다.

| DEF | 실제 실패 내용 |
|---|---|
| DEF-01 | `assert 200 in (400, 404)` |
| DEF-02, 07, 08 | `http.client.RemoteDisconnected` |
| DEF-03, 05, 06 | `assert 200 == 409` |
| DEF-04 | `assert 2 == 1` (trigger 횟수) |
| DEF-09 | 4 s 후에도 `status='committed'` |
| DEF-10 | 4 s 동안 `409` |
| DEF-11 | 2.5 s 후에도 `status='committed'` (수정 전 별도 관찰: 10 s까지 committed 유지) |

## 4-1. 이번 검증이 만든 회귀 (DEF-12)

결함은 DEF-11 timeout 수정(`a9e643d`)에서 생겼다.

- 갭 정렬이 timeout(120 s)보다 오래 걸리면 transfer가 `merge_failed`가 된다.
- 그 뒤 도착하는 실제 CARLA 진행 보고가 409로 거부된다.
- 결과적으로 차량은 물리적으로 이동했는데 논리 멤버십은 바뀌지 않는다.

limitations 문서를 쓰면서 정적으로 발견했다. 이후 xfail 테스트로 실제 재현(`409 == 200`)했고, `319b49f`에서 수정했다. 연구 당시 코드에는 timeout이 없었으므로 이 결함은 연구 당시에는 존재하지 않았다.

## 5. Baseline 교차 검증

`test_transfer_recovery.py`와 `tests/unit`을 research-baseline bridge(`git show research-baseline:bridge/platoon_bridge_server.py`)에 대해 실행했다.

결과: **17 passed, 5 failed.** (`1a5b24b` 시점 파일 기준. 이후 추가된 TC-36은 원본 bridge에 timeout이 없어 해당되지 않는다.)

실패 5건은 아래와 같고, 모두 이번 수정으로 생긴 동작을 검사하는 테스트다.

| 테스트 | 원본에서 실패한 이유 |
|---|---|
| TC-13 non-2xx | trigger_failed가 설정되지 않음 |
| TC-16 delayed | `TRANSFER_TIMEOUT_S` 속성이 없음 |
| TC-17 retry after trigger failure | trigger_failed가 설정되지 않음 |
| TC-18 late progress | trigger_failed가 설정되지 않음 |
| TC-19 retry after timeout | timeout이 없음 |

나머지 테스트는 "baseline에서도 통과"로 표기했다. 원본에서 이미 맞게 동작하던 것을 고정하는 테스트다.

## 6. Negative control

| 대상 | 방법 | 결과 |
|---|---|---|
| Happy path | Fake를 `partial` 모드로 바꿔 실행 | `status='merge_failed'`로 실패 → 테스트가 실제로 실패할 수 있음을 확인 |
| 결함 테스트 | §4의 `--runxfail` 실행 | 11건 모두 실패 |
| 회복 테스트 | §5의 baseline 실행 | 5건 실패 |

## 7. 반복 실행 (flaky 확인)

전체 스위트를 10회 연속 실행했다(`evidence/repeat_runs.txt`).

- 결과: 10/10 `36 passed` (코드 기준 `319b49f`)
- 소요 시간: 13.35 s ~ 13.96 s
- 실패·변동 없음

## 8. CI

| 항목 | 내용 |
|---|---|
| Workflow | `.github/workflows/test.yml` |
| 단계 | compileall 문법 검사 → unit → integration |
| Python | 3.10 |
| GitHub에서 실행 | **아직 실행되지 않음** (push 하지 않음) |
| 로컬 재현 | 동일 명령을 로컬에서 실행: 문법 OK, unit 10 passed, integration 26 passed (`evidence/ci_steps_local.txt`) |

## 9. 실행하지 않은 것

- 실제 CARLA 시뮬레이션(물리 합류)
- 실제 OpenClaw/Discord 협상
- docker-compose 기동

이번 수정이 실제 CARLA 데모 경로에서 회귀를 일으키지 않는지는 **CARLA로 재검증되지 않았다.** `limitations.md` 참조.

## 10. 최종 검수 (공개 전 리뷰)

`research-baseline..validation` diff를 다시 검토했다. 코드는 바꾸지 않았고 문서만 정정했다(`limitations.md`).

- 일시적 trigger 실패 시 이제 `/retry`가 필요하다. 이전에는 시나리오의 polling이 transfer를 가져가 진행했다(동작 변화 가능성, B).
- commit timeout 뒤에는 시나리오가 그 transfer를 조용히 포기하고, 넓힌 차간 거리를 되돌리지 않는다(B).
- **DEF-12는 Fake 모델의 가정(trigger 뒤 상태와 무관하게 진행 보고)에 기대어 재현한 것이다.** 실제 시나리오에서는 짧은 경쟁 구간에서만 일어날 수 있다. 테스트와 Fake가 같은 가정을 공유한 사례로 기록한다.
