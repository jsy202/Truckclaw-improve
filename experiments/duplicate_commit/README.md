# 자소서용 검증: 중복 요청에 의한 제동 초기화와 충돌

목적: 동일 요청 두 번 → 차량 제어 재시작 → 충돌을 실제 CARLA 물리 엔진에서
재현하고, 중복 요청 방지 후 같은 조건으로 회귀 검증한다.

범위: 별도 실험용 제어기에 제동 상태 초기화 결함을 주입한다. 기존 프로젝트의
단일 coordinator가 중복 commit만으로 두 번 실행된다고 가정하지 않는다.
LLM 호출을 실제로 관찰한 실험이 아니라 동일 HTTP 요청 두 번으로 입력을 재현한다.

문제: 안전 감지로 정지한 차량에 같은 이송 요청이 재전달되면 제어기가 다시
시작되면서 제동 상태가 해제되고 앞 차량으로 가속한다.

원인: 요청을 시작할 때 제어 상태를 초기화하면서 기존 요청인지 확인하지 않는다.

수정: 같은 request_id의 재요청에는 진행 중인 상태를 그대로 유지한다.
검사와 등록은 동일 잠금 안에서 처리해 동시에 들어온 요청도 한 번만 실행한다.
시간 간격으로 차단하면 늦은 재요청을 놓치므로 요청 ID를 사용한다.

검증: pytest로 제동 유지·동시 요청 32회·다른 ID 허용을 확인한다. CARLA는
`-RenderOffScreen`으로 실행하며 RGB 센서와 충돌 센서를 사용한다.
수정 전후 차량·위치·요청 타이밍·안전 정지 입력은 동일하다.
정지 전 충돌이 발생하거나 정지에 실패하면 실험은 실패 처리한다.

실행:

```bash
python3 -m pytest tests/unit/test_duplicate_commit_executor.py -q
PYTHONPATH=/home/jsy202/carla-0.9.13/PythonAPI/carla/dist/carla-0.9.13-py3.7-linux-x86_64.egg python3.7 experiments/duplicate_commit/run_carla.py --output experiments/duplicate_commit/evidence
```

증거: `evidence/*/result.json`, `telemetry.json`, `before_duplicate.png`,
`final.png`과 충돌 시 `collision.png`. `comparison.json`으로 전후를 비교한다.
실행 결과와 범위는 별도 `REPORT.md`에 기록한다.
