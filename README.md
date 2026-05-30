# Truckclaw 🚛 — Platoon Transfer Negotiation · Post-project Integration & Verification

## Project
CARLA(Town06)에서 주행하는 두 트럭 군집 사이의 차량 이송 시스템이다.

1. 두 OpenClaw AI agent가 Discord에서 목적지를 협상한다.
2. REST bridge가 이송 상태를 관리한다.
3. CARLA 시나리오가 실제 차선 변경과 합류를 수행한다.

## Architecture
```text
Agent(Discord) ─▶ bridge REST :18801 ─(commit)─▶ HTTP trigger :18802 ─▶ CARLA scenario ─▶ CARLA
                     ▲                                                     │
                     └──── POST /transfers/<id>/splitting|merging|carla_complete ◀┘
상태: pending → accepted → committed → splitting → merging → carla_complete  (실패: trigger_failed / merge_failed)
```

## Original Research
연구 당시에는 다음을 구현하고 CARLA에서 시연했다. 아래 "Original Research Documentation"은 당시 README 원문이며 수정하지 않았다.

- AI agent 협상
- bridge 상태 관리
- 이중 갭 확보, 차선 변경, CACC 합류

연구 당시 코드는 tag [`research-baseline`](https://github.com/jsy202/Truckclaw-improve/tree/research-baseline) (`3a9788f`)에 있다.

## Post-project Validation (연구 종료 후)
여러 컴포넌트가 연결된 시스템에서 **Interface, State, Failure가 올바르게 이어지는지**를 검증했다.

- 검증 방법은 **FakeCarlaScenario를 이용한 HTTP integration validation**이다. bridge와 CARLA 시나리오 사이의 기존 HTTP 계약(trigger 수신, 진행 보고)을 구현한 Fake를 실제 bridge 코드에 연결했다.
- **실제 CARLA로 다시 검증한 것은 아니다.**
- production 변경은 `bridge/platoon_bridge_server.py` 한 파일뿐이다. 시나리오, agent, 설정은 바꾸지 않았다.

## Key Findings (모두 이번 검증에서 테스트로 재현)
| ID | 결함 | 수정 |
|---|---|---|
| DEF-05 (+03, 06) | 상태 전이 검사가 없어, pending 상태에서 `carla_complete`를 받으면 **물리 이송 없이 멤버십이 이동**했다. accept 없이 commit하거나, 완료 후 상태가 되돌아가는 것도 가능했다 | `aee1a82` 상태 전이 표 |
| DEF-09, 10 | CARLA trigger 실패가 transfer에 반영되지 않았다(`trigger_failed`는 README에만 있음). 그 결과 platoon이 `/reload` 전까지 잠겼다 | `ee9568a` |
| DEF-04 | 같은 request_id로 commit하면 CARLA trigger가 2번 나갔다 | `bf35524` |
| DEF-01, 02, 07, 08 | 알 수 없는 차량을 받아들였고, 알 수 없는 platoon, `/failed`, 배열 body에는 응답 없이 연결이 끊겼다 | `d534709` `b241214` `7189c1c` |
| DEF-11 | timeout 설정(`merge_timeout_s`)은 있지만 쓰이지 않았다 → 무한 대기 | `a9e643d` |
| DEF-12 | **이번 timeout 수정이 만든 회귀.** Fake 모델에서 재현했고 수정했다. 실제 시나리오에서의 영향 범위는 [limitations](validation/limitations.md)를 참고 | `319b49f` |

## Verification
- 결함마다 요구 동작을 검사하는 테스트를 먼저 `xfail(strict=True)`로 commit했다(production 변경 0).
- 결함 하나 또는 원인이 같은 결함 묶음 하나마다 수정 commit을 하나씩 만들었다. 각 수정에서 해당 테스트를 XFAIL에서 PASS로 바꿨다.
- 같은 회귀 테스트를 원본 bridge에도 실행해, 원래 맞던 동작과 이번에 고친 동작을 구분했다.
- negative control을 했다. Fake를 실패 모드로 바꾸거나 수정 코드 일부를 제거하면 테스트가 실제로 실패한다.
- 테스트 구성: 정상 흐름, 잘못된 입력, 중복, 잘못된 상태 전이, 외부 의존성 장애(trigger 다운, 500 응답, CARLA 실패 보고, 부분 실패), timeout, 회복(retry), dialogue guard unit.
- 문서: [requirements](validation/requirements.md) · [interface spec](validation/interface_spec.md) · [state machine](validation/state_machine.md) · [test cases](validation/test_cases.md) · [traceability](validation/traceability_matrix.md) · [test report](validation/test_report.md)

## Test Result
| 테스트 | PASS | XFAIL | FAILED |
|---|---|---|---|
| 36 (integration 26, unit 10) | 36 | 0 | 0 |

Python 3.10, 로컬 실행. 10회 연속 실행에서 매회 같은 결과였다. GitHub Actions 결과는 workflow `tests`를 참고한다.

## Limitations
- **수정된 bridge를 실제 CARLA 시나리오, OpenClaw, Discord와 함께 재검증하지 않았다.**
- Fake는 HTTP 계약만 구현한다. 실제 시나리오의 `/snapshot` polling 타이밍은 재현하지 않는다.
- 동작이 바뀐 부분(정적 분석, CARLA에서 미확인):
  - **일시적** trigger 실패 시 이제 `/retry`가 필요하다.
  - commit timeout(120 s) 뒤에는 시나리오가 그 transfer를 조용히 포기한다. 실제 갭 정렬 시간이 120 s 안에 들어오는지는 측정하지 않았다.
- 물리 기동 중의 timeout, correlation_id, 시나리오의 ABORT 경로는 DEFERRED다. 자세한 내용: [limitations.md](validation/limitations.md)

## How to Run Tests (CARLA·Discord·Docker 불필요)
```bash
pip install -r requirements-test.txt
python3 -m pytest            # unit + FakeCarlaScenario integration
```

---

## Original Research Documentation (연구 당시 README 원문)


**AI 에이전트가 협상하는 트럭 군집 차량 이송 시뮬레이션**

CARLA 자율주행 시뮬레이터(Town06 고속도로)에서 두 트럭 군집이 실시간으로 주행하는 동안,
Discord AI 봇(OpenClaw)이 서로 목적지 정보를 교환하고 협상하여 차량 이송을 결정합니다.
협상이 완료되면 CARLA 시뮬레이터에서 실제 차선 변경과 군집 합류가 자동으로 진행됩니다.

---

## 데모

```
[Discord 협상]
TRUCKCLAW2 (Platoon A): Platoon A 목적지 공유할게.
                         - platoon_a_truck0: dest_a
                         - platoon_a_truck1: dest_b   ← B 방향!
                         - platoon_a_truck2: dest_a
                         너희 목적지도 같은 형식으로 알려줘.

TRUCKCLAW1 (Platoon B): Platoon B 목적지 공유할게.
                         - platoon_b_truck0: dest_b
                         - platoon_b_truck1: dest_b
                         - platoon_b_truck2: dest_b

TRUCKCLAW2:              비교 결과 platoon_a_truck1은 너희 목적지 dest_b와 일치해.
                         브리지 안전 확인 후 transfer 요청 생성할게.
                         request_id: tr_xxxxxxxx / status: pending
                         수락/commit 부탁해.

TRUCKCLAW1:              request_id tr_xxxxxxxx commit 완료.

[자동 트리거 → CARLA 물리 합류 시작]
```

---

## 시나리오 개요

고속도로 주행 중 두 군집(각 3대)이 분기점 이전에 차량 이송을 협상합니다.

```
          분기점(x=658)
             │
  ──────────────────────────→  dest_a (직진)
  P1: [truck0][truck1][truck2]
                              ↘
  P2: [truck0][truck1][truck2]  dest_b (우측 분기)
```

`platoon_a_truck1`의 목적지가 `dest_b`이므로, Platoon B로 이송하는 것이 효율적입니다.
두 AI 봇이 이를 판단하고 협상 → 물리 합류까지 자동으로 수행합니다.

### 이송 대상 차량 (기본 설정)

| 차량 ID | 소속 | 역할 | 목적지 |
|---------|------|------|--------|
| platoon_a_truck0 | Platoon A | 리더 | dest_a |
| **platoon_a_truck1** | **Platoon A** | **팔로워** | **dest_b ← 이송 대상** |
| platoon_a_truck2 | Platoon A | 팔로워 | dest_a |
| platoon_b_truck0 | Platoon B | 리더 | dest_b |
| platoon_b_truck1 | Platoon B | 팔로워 | dest_b |
| platoon_b_truck2 | Platoon B | 팔로워 | dest_b |

---

## 주요 개선 사항 (improve 버전)

| 기능 | 설명 |
|------|------|
| **중간 차량 이송** | 꼬리 차량뿐 아니라 중간/선두 차량도 이송 가능 |
| **이중 갭 확보** | 이송 차량 앞뒤 양쪽 20m 간격 동시 확보 후 분리 |
| **Follower 이송** | 현재 CARLA 시나리오는 truck0 리더 이송을 제외하고 follower 이송만 수행 |
| **Mock CARLA 모드** | `MOCK_CARLA=true`로 CARLA 없이 협상 흐름만 테스트 |
| **군집 해산 처리** | 군집이 비면 `dissolved` 상태로 자동 표시 |
| **사전 경로 계산** | 분기점에서 잘못된 출구 선택 방지를 위한 직진 경로 사전 계산 |

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                      Discord 채널                        │
│   TRUCKCLAW2 (Platoon A)  ↔  TRUCKCLAW1 (Platoon B)     │
└────────────┬────────────────────────┬────────────────────┘
             │                        │
             ▼                        ▼
┌────────────────────────────────────────────────────────┐
│              브리지 서버 (포트 18801)                   │
│  pending → accepted → committed → splitting → merging  │
│                              → carla_complete           │
│  실패: trigger_failed / merge_failed                    │
│                    │                                    │
│             commit 감지 시                              │
│         POST :18802/start_merge  ──────────────────────┼──→ CARLA 시나리오
└────────────────────────────────────────────────────────┘
                                                           │
                                              ┌────────────▼──────────────┐
                                              │    CARLA Town06 (포트 2000)│
                                              │  P1 [차선=-3]  P2 [차선=-5]│
                                              │  차선 변경 → 합류 완료     │
                                              └───────────────────────────┘
```

### 구성 요소

| 구성 요소 | 역할 |
|-----------|------|
| **CARLA 시뮬레이터** | Town06 고속도로에서 트럭 6대 물리 시뮬레이션 |
| **브리지 서버** | 협상 상태 관리 REST API. 봇과 CARLA 사이의 중재자 |
| **TRUCKCLAW2** (Platoon A 봇) | 시작자 — 먼저 목적지를 공개하고 이송 요청 생성 |
| **TRUCKCLAW1** (Platoon B 봇) | 응답자 — 수락 및 commit, CARLA 트리거 전송 |

---

## 전체 흐름

### 1단계 — 협상 (Discord)

1. 사용자가 봇에게 `군집 합류 가능한지 확인후 필요시 행동부탁` 입력
2. TRUCKCLAW2가 브리지에서 최신 목적지를 조회하여 Discord에 공개
3. TRUCKCLAW1이 Platoon B 목적지 목록으로 응답
4. TRUCKCLAW2가 목적지 비교 → 이송 필요 차량 판단 → 브리지 안전 확인 → 이송 요청 생성
5. TRUCKCLAW1이 수락(accept) → commit

### 2단계 — 물리 합류 (CARLA)

1. 브리지 서버가 commit 감지 → `POST :18802/start_merge` 자동 전송
2. CARLA 시나리오가 브리지 preflight로 이송 대상 차량 확인
3. P1 속도를 유지하고 P2를 빠르게 당겨 나란히 정렬
4. **이중 갭 확보**: 이송 차량 앞뒤 20m 간격 확보 → `split()` 분리
5. 차선 변경 (PID 컨트롤러로 수동 조향)
6. P2 꼬리 뒤에 합류 (CACC 추종 재개)
7. 브리지 서버에 `carla_complete` 보고 및 논리적 멤버십 이동

### 이송 상태 머신

```
pending → accepted → committed → splitting → merging → carla_complete
  ↑요청생성   ↑B수락     ↑B커밋    ↑갭확보중    ↑차선변경    ↑물리합류완료

trigger_failed : 브리지가 CARLA 트리거 서버 호출 실패
merge_failed   : CARLA 물리 합류 실패 또는 타임아웃
```

---

## 프로젝트 구조

```
Truckclaw-improve/
├── scenario/                              # CARLA 시뮬레이션
│   ├── examples/
│   │   └── two_platoon_truck_scenario.py  # 메인 시나리오 스크립트
│   └── src/PlatooningSimulator/           # 군집주행 컨트롤러 라이브러리
│       ├── Core.py                        # 차량/군집 기본 클래스
│       ├── PlatooningControllers.py       # CACC, LeadNavigator 등
│       └── ScenarioAgents.py             # 시나리오 에이전트
│
├── bridge/                                # 협상 브리지 서버
│   ├── platoon_bridge_server.py           # REST API 서버 (포트 18801)
│   └── platoon_bridge_ctl.py             # CLI 클라이언트 (봇이 사용)
│
├── agents/                                # OpenClaw 에이전트 설정
│   ├── platoon-a/                         # Platoon A (시작자, TRUCKCLAW2)
│   │   ├── SOUL.md                        # 에이전트 역할/행동 지침
│   │   ├── AGENTS.md                      # 에이전트 메타데이터
│   │   ├── TOOLS.md                       # 사용 가능한 도구 목록
│   │   ├── data/platoon_decision_context.json  # 차량/목적지 정보
│   │   └── skills/platoon-negotiator/SKILL.md  # 협상 스킬 단계별 지침
│   └── platoon-b/                         # Platoon B (응답자, TRUCKCLAW1)
│       ├── SOUL.md
│       ├── AGENTS.md
│       ├── TOOLS.md
│       ├── data/platoon_decision_context.json
│       └── skills/platoon-negotiator/SKILL.md
│
├── config/
│   ├── platoons.json                      # 군집 및 차량 목적지 설정
│   └── simulation.json                    # 속도/간격/타임아웃 파라미터
│
├── docs/                                  # 시나리오 다이어그램 이미지
├── docker-compose.yml                     # 봇 컨테이너 실행 설정
├── .env.example                           # 환경변수 예시
└── README.md
```

---

## 실행 방법

### 사전 요구사항

- [CARLA](https://carla.org/) 0.9.x (UE4 에디터 또는 패키지 버전)
- Python 3.10+, `carla` Python 패키지
- [OpenClaw](https://openclaw.ai) 이미지 (Docker)
- Discord 봇 토큰 2개 (Platoon A용, Platoon B용)

### 1단계 — 환경변수 설정

```bash
cp .env.example .env
# .env 편집: Discord 봇 토큰, OpenClaw 게이트웨이 토큰 입력
```

### 2단계 — CARLA 시뮬레이터 실행

```bash
# 패키지 버전 (헤드리스)
./CarlaUE4.sh -RenderOffScreen

# 또는 UE4 에디터에서 Play 버튼 클릭
```

### 3단계 — 브리지 서버 시작

```bash
python3 bridge/platoon_bridge_server.py
# → http://127.0.0.1:18801 에서 대기
```

### 4단계 — OpenClaw 봇 실행

```bash
docker compose up -d
```

### 5단계 — CARLA 시나리오 실행

```bash
export PYTHONPATH=$PYTHONPATH:/path/to/carla/PythonAPI/carla
python3 scenario/examples/two_platoon_truck_scenario.py
# → 포트 18802 트리거 서버 자동 시작
# → 양 군집 20 km/h로 주행 시작
```

### 6단계 — Discord에서 협상 시작

Discord 채널에서 아무 봇에게 입력:
```
군집 합류 가능한지 확인후 필요시 행동부탁
```

이후 모든 과정은 자동입니다.

---

## CARLA 없이 테스트 (Mock 모드)

CARLA 시뮬레이터 없이 협상 흐름과 브리지 상태 머신만 테스트할 수 있습니다.

```bash
# 브리지 서버를 Mock 모드로 실행
MOCK_CARLA=true python3 bridge/platoon_bridge_server.py
```

commit 후 브리지가 자동으로 `splitting → merging → carla_complete` 순서로 상태를 진행합니다. CARLA 시뮬레이터 없이 Discord 협상 전체를 검증할 수 있습니다.

### OpenClaw 협상 하네스

Discord/OpenClaw 없이도 동일한 bridge 계약을 deterministic하게 점검할 수 있습니다.

```bash
# 후보 검증만 수행
python3 tools/openclaw_negotiation_harness.py --reload --dry-run

# request -> accept -> commit까지 수행
python3 tools/openclaw_negotiation_harness.py --reload

# MOCK_CARLA=true bridge에서 carla_complete까지 대기
python3 tools/openclaw_negotiation_harness.py --reload --wait-complete
```

하네스는 leader(`truck0`)를 제외하고, bridge candidate와 목적지 일치가 확인된 follower만 요청합니다.

---

## 수동 제어 (CLI)

Discord 봇 없이 직접 명령으로 이송을 제어할 수 있습니다.

```bash
# 이송 요청 생성 (예: platoon_a의 truck1을 platoon_b로)
python3 bridge/platoon_bridge_ctl.py request platoon_a_truck1 platoon_a platoon_b

# 현재 상태 확인 (request_id 조회)
python3 bridge/platoon_bridge_ctl.py snapshot

# 수락
python3 bridge/platoon_bridge_ctl.py accept <request_id>

# 커밋 (이 순간 CARLA에서 차량이 움직이기 시작)
python3 bridge/platoon_bridge_ctl.py commit <request_id>

# 브리지 재초기화
kill $(lsof -ti:18801) 2>/dev/null; sleep 1 && python3 bridge/platoon_bridge_server.py &
```

---

## 차량 목적지 변경

다른 차량을 이송 대상으로 바꾸고 싶다면:

1. 프로젝트 루트의 `platoon_destinations.json` 파일에서 원하는 차량의 `destination_id`를 수정합니다.
2. 브리지 서버가 실행 중인 상태에서 아래 명령으로 설정을 다시 불러옵니다.

```bash
python3 bridge/platoon_bridge_ctl.py --base-url http://127.0.0.1:18801 snapshot
# 또는 브리지 서버를 재시작
```

---

## 브리지 REST API

| 엔드포인트 | 메서드 | 설명 |
|------------|--------|------|
| `/health` | GET | 서버 상태 확인 |
| `/snapshot` | GET | 전체 상태 조회 (군집 + 이송 목록 + readiness) |
| `/readiness` | GET | CARLA 물리 합류 준비 상태 조회 |
| `/readiness` | POST | CARLA가 정렬/거리/방향/준비 여부 보고 |
| `/platoons/{id}` | GET | 특정 군집 정보 조회 |
| `/platoons/{id}/transfer-candidates` | GET | 이송 후보 차량 목록 |
| `/transfers` | POST | 이송 요청 생성 |
| `/transfers/{id}/accept` | POST | 수락 |
| `/transfers/{id}/commit` | POST | 커밋 (→ CARLA 트리거 자동 발송) |
| `/transfers/{id}/merging` | POST | CARLA 합류 시작 보고 |
| `/transfers/{id}/carla_complete` | POST | 물리 합류 완료 보고 |
| `/transfers/{id}/failed` | POST | 물리 합류 실패/타임아웃 보고 |
| `/reload` | POST | `platoon_destinations.json` 재로드 |

---

## 포트 정리

| 포트 | 용도 |
|------|------|
| 2000 | CARLA 시뮬레이터 |
| 18801 | 브리지 서버 REST API |
| 18802 | CARLA 트리거 수신 엔드포인트 |
| 18789 | OpenClaw Platoon A 게이트웨이 |
| 18790 | OpenClaw Platoon B 게이트웨이 |

---

## 주요 파라미터 (`config/simulation.json`)

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `sync_speed_kmh` | 20 | 군집 기본 주행 속도 |
| `approach_fast_kmh` | 65 | 접근 시 최대 속도 |
| `target_gap_m` | 6 | 차선 변경 전 확보할 목표 갭 |
| `follow_dist_m` | 13 | CACC 추종 목표 거리 |
| `platoon_spacing_m` | 16 | 군집 내 차량 간격 |
| `merge_distance_limit_m` | 55 | 합류 트리거 최대 허용 거리 |
| `merge_timeout_s` | 120 | 합류 타임아웃 (초) |
| `post_merge_speed_kmh` | 50 | 합류 완료 후 순항 속도 |

---

## 라이선스

[LICENSE](scenario/LICENSE) 참고
