# Real-CARLA Re-validation Report — Truckclaw-improve (Post-project Validation)

> **실제 CARLA 실행 결과(등급 A)** 다. FakeCarlaScenario 결과(`validation/test_report.md`)와는 별개다.
> 환경과 절차는 [test_plan.md](test_plan.md), 원시 데이터는 [raw_results.csv](raw_results.csv)와 `evidence/`에 있다.

**측정 환경(모든 수치 공통):** CARLA 0.9.13(offscreen, Low quality, run마다 서버 새로 기동), RTX 3060, Python 3.7 client, 기존 `two_platoon_truck_scenario.py`(Town06, 동기 dt 0.01), 차량 `vehicle.carlamotors.carlacola`(0.9.13에 european_hgv 없음), OpenClaw/Discord 대신 기존 negotiation harness 또는 같은 REST 호출, 수정된 bridge(validation 브랜치) — 비교 run은 research-baseline bridge.

## 1. 요약

| 시나리오 | bridge | 반복 | 성공 | 핵심 측정 |
|---|---|---|---|---|
| RC-A Normal Transfer | 현재 | 10 | **10/10** | request→carla_complete 평균 **13.87 s** (13.65–14.45), 논리·물리 일치 10/10 |
| RC-B Duplicate commit ×3 | 현재 | 5 | 5/5 | CARLA trigger **1회**/run, 물리 split 시작 **1회**/run |
| RC-B Duplicate commit ×3 | research-baseline | 3 | 3/3 | CARLA trigger **3회**/run, 물리 split 시작 **1회**/run |
| RC-C Failure → Recovery | 현재 | 5 | **5/5** | trigger 실패 → `trigger_failed` 5/5, 새 요청 수락(200) 5/5, 회복 후 완료 5/5 |
| RC-C Failure → Recovery | research-baseline | 2 (+1 중단) | – | trigger 실패에도 원 transfer가 물리 완료, 그 뒤 새 요청이 `committed`에서 정지 (§4) |

환경 오류(서버 기동 실패 등): 본 측정 중 0건. 도구 준비 단계에서 같은 서버에 반복 `load_world` 후 CARLA가 segfault한 1건이 있어, run마다 서버를 새로 띄우도록 도구를 바꾼 뒤 본 측정을 처음부터 다시 했다(중단분은 결과에서 제외, 도구 개발 이력으로만 기록).

## 2. RC-A Normal Transfer (현재 bridge, n = 10)

| 지표 | 값 |
|---|---|
| 성공 | 10/10 (`carla_complete` + 논리 멤버십 + 물리 일치) |
| request → commit | 0.18 s (harness 처리 시간) |
| commit → 물리 시작(splitting/merging 첫 관측) | 평균 9.77 s, 9.65–9.85 s |
| commit → carla_complete | 평균 13.69 s, 13.47–14.27 s |
| request → carla_complete | 평균 13.87 s, 13.65–14.45 s, σ 0.30 s |
| 최종 논리 멤버십 | A = [truck0, truck2], B = [b0, b1, b2, **a_truck1**] (10/10) |
| 물리 상태 | truck1 차선 −5 = B 차선, A 차선 −3과 다름, b2 뒤 12.6 m (10/10) |
| CARLA trigger / split 시작 / join | 1 / 1 / 1 (매 run) |

물리 결과가 10회 모두 12.6 m로 같았다. 동기 모드·고정 dt·같은 spawn에서 시나리오가 결정적으로 재현되는 것으로 보이며, **조건이 하나뿐이라 분포가 매우 좁다**는 점에 유의.

## 3. RC-B Duplicate commit (같은 request_id에 commit 3회)

| bridge | run | commit HTTP | CARLA trigger 전송 | 물리 split 시작 | 최종 |
|---|---|---|---|---|---|
| 현재 | 5 | 200, 200, 200 | **1** | 1 | carla_complete, 일치 5/5 |
| research-baseline | 3 | 200, 200, 200 | **3** | 1 | carla_complete, 일치 3/3 |

**해석:** DEF-04 수정은 실제 환경에서도 중복 CARLA trigger를 3→1로 없앴다. 그러나 **수정 전에도 물리 동작은 중복되지 않았다.** 실제 시나리오는 trigger가 아니라 `/snapshot` polling으로 시작하고, coordinator 상태(CRUISE에서만 시작)가 재진입을 막기 때문이다. 즉 이 시나리오 구성에서 DEF-04의 실제 영향은 "중복 trigger(불필요한 신호)"였지 "중복 물리 명령"이 아니었다.

## 4. RC-C Failure → Recovery

fault proxy가 bridge → 시나리오 trigger를 HTTP 503으로 실패시킨 뒤, 같은 차량에 새 요청을 보내고 proxy를 정상화했다.

### 현재 bridge (n = 5)
| 단계 | 결과 |
|---|---|
| 첫 commit 후 상태 | `trigger_failed` (5/5, reason "HTTP Error 503") |
| 원 transfer 물리 시작 | 없음 (시나리오는 committed/merging만 가져감) |
| 같은 platoon·차량 새 요청 | **200 수락** (5/5) — platoon 잠금 없음 |
| 회복 transfer | carla_complete 5/5, commit→완료 평균 13.75 s, 논리·물리 일치 5/5 |

### research-baseline bridge (비교, n = 2 완료 + 1 중단)
| 단계 | run 1 | run 2 |
|---|---|---|
| 첫 commit 후 | 상태 `committed` 유지(trigger 503) | 같음 |
| 원 transfer | **물리 완료** — +9.9 s merging, +14.3 s carla_complete | 같음 (+10.1 / +14.3 s) |
| 이미 B로 이동한 truck1에 대한 새 요청(from=platoon_a) | **200 수락** (멤버십 검증 없음, DEF-01) | 같음 |
| 그 요청 | commit 후 처리할 차량이 없어 **`committed`에서 600 s 동안 정지**(timeout 없음, DEF-11) | 같음, 최종 `committed` |
| 기록 | 도구 오류(600 s 후 물리 조회 실패 — 시나리오가 sim 시간 한도로 이미 종료) → CSV `error`, 타임라인은 `evidence/*002125_run1_events.json` | CSV에 기록. 600 s 후 차량들이 경로 끝까지 주행해 물리 판정은 무의미 |
| run 3 | 바깥 실행 시간 제한(1500 s)으로 **중단**, 결과 행 없음 | |

### 실제 CARLA에서 확인된 trade-off (중요)
- 수정 전: trigger 실패가 **실제로는 무해**했다 — 시나리오가 polling으로 transfer를 수행했다. 대신 DEF-01(이동한 차량의 재요청 수락)과 DEF-11(무기한 `committed`)이 실제로 나타났다.
- 수정 후: trigger 실패 시 `trigger_failed`가 되어 **시나리오가 그 transfer를 수행하지 않는다.** 대신 platoon이 잠기지 않아 새 요청(또는 `/retry`)으로 회복된다.
- 즉 DEF-09 수정은 "실패를 드러내고 회복 가능하게" 만들었지만, 이 시나리오에서는 **자동으로 완료됐을 transfer를 재요청이 필요하게** 만들었다. 이전에 `limitations.md`에 정적 분석(B)으로 적었던 동작 변화가 실제 실행(A)으로 확인되었다. 정책 변경(예: trigger 실패 시에도 polling 허용)은 production 동작 결정이라 이번 작업에서 하지 않았다.

## 5. Timeout 120 s의 적절성 (측정 범위 안에서만)

현재 bridge의 성공 run 20회(RC-A 10, RC-B 5, RC-C 5):

| 구간 | n | mean | median | p95 | max |
|---|---|---|---|---|---|
| commit → 물리 시작 (bridge timeout이 감시하는 구간) | 20 | 9.82 s | 9.85 s | 10.25 s | **10.26 s** |
| commit → carla_complete | 20 | 13.63 s | 13.58 s | 14.27 s | 14.27 s |

이 조건(같은 spawn, 20 km/h, carlacola, 사전 정렬 상태에서 워밍업 5 s 후 요청)에서는 120 s timeout이 관측 최대값의 약 11.7배 여유를 가진다. **다른 초기 배치·속도·차량·OpenClaw 협상 지연이 있는 조건은 측정하지 않았으므로 120 s가 일반적으로 적절하다고 결론 내릴 수 없다.**

## 6. 한계

- OpenClaw LLM agent·Discord 협상은 사용하지 않았다(협상 지연 미포함).
- 차량이 european_hgv가 아니라 carlacola다(0.9.13). 연구 당시 시연 조건과 다르다.
- 시나리오 조건이 하나(결정적 재현)라 시간 분포가 좁다.
- baseline 비교 RC-C는 2회만 완료되었고 1회는 도구 오류가 있었다.
- 물리 일치 판정은 차선·종방향 위치 기준이며 CACC 추종 품질(간격 안정성)은 평가하지 않았다.
